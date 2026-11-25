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

import base64
import json
import os
import tempfile

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

from . import mbd

VIEWS = "FreeWorks:3DViews"
TEMPLATE = "User parameter:BaseApp/Preferences/Mod/FreeWorks/MBDPDF"
TEMPLATE_FIELDS = (("Company", ""), ("Title", ""), ("Author", ""), ("Revision", "A"), ("Logo", ""),
                   ("Paper", "A4"), ("Orientation", "Landscape"))
SURFACE = {"Basic": "√", "Machining required": "∀", "Machining prohibited": "⍻"}
WELDS = {"Fillet": "◺", "Square groove": "‖", "V groove": "V", "Bevel groove": "V/", "Plug": "▭", "Spot": "○"}


# --------------------------------------------------------------------------- annotations
def reference_dimension(doc, a, b):
    """Reference Dimension: the distance between two items, without tolerance, in parentheses when
    Document Properties > Dimensions > Add parentheses by default is on."""
    d = mbd.distance(mbd._el(*a), mbd._el(*b))
    text = mbd._num(d)
    if bool(mbd._dp(doc, "Dimensions", "Add parentheses by default", False)):
        text = "(%s)" % text
    return mbd.make(doc, "Reference", [a, b], text, d, 0.0, 0.0)


def note(doc, text, ref=None):
    from . import docstyle
    refs = [ref] if ref else []
    return mbd.make(doc, "Note", refs, docstyle.note_text(doc, text), 0.0, 0.0, 0.0,
                    None if refs else App.Vector(0, 0, 0))


def surface_finish(doc, ref, symbol="Machining required", roughness="3.2", method="", lay=""):
    text = "%s Ra %s" % (SURFACE.get(symbol, "√"), roughness)
    if method:
        text += "\n" + method
    if lay:
        text += " " + lay
    return mbd.make(doc, "SurfaceFinish", [ref], text, 0.0, 0.0, 0.0)


def weld_symbol(doc, ref, kind="Fillet", size="5", both=False, all_around=False, field=False):
    sym = WELDS.get(kind, kind)
    text = "%s%s %s" % ("○" if all_around else "", sym + ("/" + sym if both else ""), size)
    if field:
        text = "⚑" + text
    return mbd.make(doc, "Weld", [ref], text, 0.0, 0.0, 0.0)


# --------------------------------------------------------------------------- 3D views
def views(doc):
    try:
        return json.loads(dict(doc.Meta or {}).get(VIEWS, "[]"))
    except ValueError:
        return []


def _save_views(doc, items):
    meta = dict(doc.Meta)
    meta[VIEWS] = json.dumps(items)
    doc.Meta = meta
    refresh_pane()


def _picture(width=160, height=120):
    path = os.path.join(tempfile.mkdtemp(), "view.png")
    Gui.ActiveDocument.ActiveView.saveImage(path, width, height, "Current")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def display_states(doc):
    """(the display states Capture 3D View offers, the one to preselect); ([], None) without any."""
    try:
        from . import displaystates as ds
        shown = list(ds.listed(doc)) if hasattr(ds, "listed") else list(ds.names(doc))
        on = ds.active(doc)
        if not shown and hasattr(ds, "default_name"):
            shown = [ds.default_name(doc)]
        return shown, (on if on in shown else (shown[0] if shown else None))
    except Exception as _fw_err:
        _fw_log("mbdtab.py:display_states", _fw_err)
        return [], None


def capture(doc, name=None, annotations=None, config=None, display=None):
    """Capture 3D View: the camera, the annotations shown (or the given ones), the configuration and the display
    state (the active ones, or the given ones)."""
    items = views(doc)
    name = name or "3DView%d" % (len(items) + 1)
    shown = annotations if annotations is not None else [
        o.Name for o in doc.Objects if mbd.is_pmi(o) and o.ViewObject is not None and o.ViewObject.Visibility]
    if config is None:
        try:
            from . import configmanager
            t = configmanager.table(doc)
            config = t.active() if t else None
        except Exception as _fw_err:
            _fw_log("mbdtab.py:125", _fw_err)
    if display is None:
        display = display_states(doc)[1]
    rec = {"name": name, "camera": Gui.ActiveDocument.ActiveView.getCamera(), "shown": shown, "config": config,
           "display": display, "image": _picture() if App.GuiUp else ""}
    items = [v for v in items if v["name"] != name] + [rec]
    _save_views(doc, items)
    return rec


def activate(doc, name):
    """A 3D view shown again: its configuration, its camera, only its annotations."""
    rec = next((v for v in views(doc) if v["name"] == name), None)
    if rec is None:
        return False
    if rec.get("config"):
        try:
            from . import configmanager
            t = configmanager.table(doc)
            if t is not None and rec["config"] in t.names() and t.active() != rec["config"]:
                configmanager.show(t, rec["config"])
        except Exception as _fw_err:
            _fw_log("mbdtab.py:145", _fw_err)
    if rec.get("display"):
        try:
            from . import displaystates as ds
            if rec["display"] in ds.names(doc) and ds.active(doc) != rec["display"]:
                ds.activate(doc, rec["display"])
        except Exception as _fw_err:
            _fw_log("mbdtab.py:display", _fw_err)
    Gui.ActiveDocument.ActiveView.setCamera(rec["camera"])
    shown = set(rec.get("shown") or [])
    for o in doc.Objects:
        if mbd.is_pmi(o) and o.ViewObject is not None:
            o.ViewObject.Visibility = o.Name in shown
    return True


def update_view(doc, name):
    rec = next((v for v in views(doc) if v["name"] == name), None)
    return capture(doc, name) if rec is not None else None


def rename_view(doc, old, new):
    items = views(doc)
    if not new or any(v["name"] == new for v in items):
        return False
    for v in items:
        if v["name"] == old:
            v["name"] = new
    _save_views(doc, items)
    return True


def delete_view(doc, name):
    _save_views(doc, [v for v in views(doc) if v["name"] != name])


# --------------------------------------------------------------------------- Dynamic Annotation Views
ROW = "Display items only in the view in which they are created"


def dynamic_views(doc):
    return bool(mbd._dp(doc, "Detailing", ROW, False))


def set_dynamic_views(doc, on):
    from . import optionspages
    optionspages._doc_set("Detailing", ROW, bool(on))
    mbd.restyle_all(doc)
    return bool(on)


# --------------------------------------------------------------------------- Copy Scheme
def copy_scheme(doc, source, targets):
    """Copy Scheme: the source configuration's annotations copied to the target configurations;
    from then on each copy shows only in its own configuration."""
    made = []
    src = [o for o in doc.Objects if mbd.is_pmi(o) and (not list(o.Configurations or []) or
                                                         source in list(o.Configurations))]
    for o in src:
        if not list(o.Configurations or []):
            o.Configurations = [source]
        for t in targets:
            if t == source:
                continue
            c = mbd.make(doc, o.Kind, [(r, s) for r, subs in o.References for s in (subs or [""])], o.Text,
                         o.Value, o.Plus, o.Minus, App.Vector(o.TextPosition))
            c.Configurations = [t]
            made.append(c)
    mbd.restyle_all(doc)
    return made


# --------------------------------------------------------------------------- Auto Pair Tolerance
def auto_pair(doc, obj, sub, datums=("A", "B", "C")):
    """Auto Pair Tolerance (rough match): the hole and its pattern mates sized, and a Position frame
    to the datums, in one step."""
    f = mbd._el(obj, sub)
    holes = mbd.equal_holes(obj.Shape, f)
    first = mbd.pattern_feature(doc, obj, sub) if len(holes) > 1 else mbd.size_dimension(doc, obj, sub)
    frame = mbd.gtol(doc, obj, sub, "Position", 2 * mbd.default_tol(doc), datums, True, "MMC")
    return [first, frame]


# --------------------------------------------------------------------------- publishing
def template():
    p = App.ParamGet(TEMPLATE)
    return {k: p.GetString(k, d) for k, d in TEMPLATE_FIELDS}


def set_template(**values):
    p = App.ParamGet(TEMPLATE)
    for k, v in values.items():
        p.SetString(k, str(v))


def publish_pdf(doc, path, width=1600, height=1000):
    """Publish to 3D PDF (rough match): a page per 3D view (or the view on screen), each with the
    title block and the annotation list."""
    from PySide import QtGui as G
    tpl = template()
    items = views(doc) or [None]
    keep = Gui.ActiveDocument.ActiveView.getCamera()
    try:
        writer = G.QPdfWriter(path)
    except AttributeError:
        from PySide6 import QtGui as G6
        writer = G6.QPdfWriter(path)
        G = G6
    size = {"A3": G.QPageSize.A3, "Letter": G.QPageSize.Letter}.get(tpl["Paper"], G.QPageSize.A4)
    writer.setPageSize(G.QPageSize(size))
    writer.setPageOrientation(G.QPageLayout.Portrait if tpl["Orientation"] == "Portrait" else G.QPageLayout.Landscape)
    writer.setTitle(tpl["Title"] or doc.Label)
    writer.setCreator("FreeCAD")
    painter = G.QPainter(writer)
    pages = 0
    try:
        for i, rec in enumerate(items):
            if i:
                writer.newPage()
            if rec is not None:
                activate(doc, rec["name"])
            img = os.path.join(tempfile.mkdtemp(), "page.png")
            Gui.ActiveDocument.ActiveView.saveImage(img, width, height, "White")
            area = painter.viewport()
            w, h = area.width(), area.height()
            block = int(h * 0.12)
            pic = G.QImage(img)
            target = QtCore.QRect(0, 0, w, h - block - int(h * 0.2))
            scaled = pic.scaled(target.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            painter.drawImage(QtCore.QPoint((w - scaled.width()) // 2, 0), scaled)
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            y = h - block - int(h * 0.2) + 20
            shown = [o for o in doc.Objects if mbd.is_pmi(o) and o.ViewObject is not None and o.ViewObject.Visibility]
            line = int(painter.fontMetrics().height() * 1.2)
            for o in shown[:20]:
                painter.drawText(40, y + line, "%s   %s" % (o.Label, str(o.Text).replace("\n", "  ")))
                y += line
            painter.drawRect(0, h - block, w - 1, block - 1)
            logo = tpl.get("Logo")
            x = 20
            if logo and os.path.exists(logo):
                li = G.QImage(logo).scaledToHeight(block - 20, QtCore.Qt.SmoothTransformation)
                painter.drawImage(QtCore.QPoint(10, h - block + 10), li)
                x = li.width() + 30
            fields = [("Company", tpl["Company"]), ("Title", tpl["Title"] or doc.Label), ("Author", tpl["Author"]),
                      ("Revision", tpl["Revision"]), ("View", rec["name"] if rec else "Current view")]
            col = (w - x) // len(fields)
            for k, (label, value) in enumerate(fields):
                painter.drawText(x + k * col, h - block + line + 10, label)
                painter.drawText(x + k * col, h - block + 2 * line + 20, value)
            pages += 1
    finally:
        painter.end()
        Gui.ActiveDocument.ActiveView.setCamera(keep)
    return pages


def publish_step242(doc, path):
    """Publish STEP 242: the bodies to a STEP file in the AP242 schema."""
    import ImportGui
    import Part
    keys = ("User parameter:BaseApp/Preferences/Mod/Part/STEP", "User parameter:BaseApp/Preferences/Mod/Import/hSTEP",
            "User parameter:BaseApp/Preferences/Mod/Import")
    before = [App.ParamGet(k).GetString("Scheme", "") for k in keys]
    for k in keys:
        App.ParamGet(k).SetString("Scheme", "AP242DIS")
    try:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()] or \
            [o for o in doc.Objects if not mbd.is_pmi(o) and isinstance(getattr(o, "Shape", None), Part.Shape)
             and o.Shape.Solids and not [p for p in o.InList if not mbd.is_pmi(p) and p.isDerivedFrom("Part::Feature")]]
        ImportGui.export(bodies, path)
    finally:
        for k, v in zip(keys, before):
            App.ParamGet(k).SetString("Scheme", v or "AP214IS")
        _reset_scheme()
        for k, v in zip(keys, before):
            if not v:
                App.ParamGet(k).RemString("Scheme")
    return path


def _reset_scheme():
    """FreeCAD keeps the last STEP schema it wrote: one throwaway export puts the user's back."""
    import ImportGui
    import Part
    tmp = App.newDocument("FWStepReset", hidden=True)
    try:
        o = tmp.addObject("Part::Feature", "Box")
        o.Shape = Part.makeBox(1, 1, 1)
        path = os.path.join(tempfile.mkdtemp(), "reset.step")
        ImportGui.export([o], path)
        try:
            os.remove(path)
        except OSError as _fw_err:
            _fw_log("mbdtab.py:334", _fw_err)
    finally:
        App.closeDocument(tmp.Name)


def compare(a, b):
    """3D PMI Compare: [(annotation, text in a, text in b, "same" | "changed" | "added" | "removed")]."""
    def table(doc):
        return {o.Label: str(o.Text) for o in doc.Objects if mbd.is_pmi(o)}
    ta, tb = table(a), table(b)
    out = []
    for k in sorted(set(ta) | set(tb)):
        if k not in tb:
            out.append((k, ta[k], "", "removed"))
        elif k not in ta:
            out.append((k, "", tb[k], "added"))
        else:
            out.append((k, ta[k], tb[k], "same" if ta[k] == tb[k] else "changed"))
    return out


# =========================================================================== GUI
_pane = []


def refresh_pane():
    for p in list(_pane):
        try:
            p.refresh()
        except Exception:
            _pane.remove(p)


if Gui is not None:
    class ViewsPane(QtWidgets.QWidget):
        """The 3D Views tab: a picture per captured view; double-click activates; right-click
        Activate, Update View, Rename, Delete, Capture 3D View."""

        def __init__(self):
            super().__init__()
            self.setObjectName("SW3DViewsPane")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(2, 2, 2, 2)
            self.list = QtWidgets.QListWidget()
            self.list.setViewMode(QtWidgets.QListView.IconMode)
            self.list.setIconSize(QtCore.QSize(120, 90))
            self.list.setFlow(QtWidgets.QListView.LeftToRight)
            self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.list.customContextMenuRequested.connect(self._menu)
            self.list.itemDoubleClicked.connect(lambda it: activate(App.ActiveDocument, it.text()))
            lay.addWidget(self.list)
            _pane.append(self)
            self.refresh()

        def refresh(self):
            self.list.clear()
            doc = App.ActiveDocument
            if doc is None:
                return
            for v in views(doc):
                it = QtWidgets.QListWidgetItem(v["name"])
                if v.get("image"):
                    pm = QtGui.QPixmap()
                    pm.loadFromData(base64.b64decode(v["image"]))
                    it.setIcon(QtGui.QIcon(pm))
                self.list.addItem(it)

        def _menu(self, pos):
            doc = App.ActiveDocument
            it = self.list.itemAt(pos)
            m = QtWidgets.QMenu(self)
            if it is not None:
                n = it.text()
                m.addAction("Activate").triggered.connect(lambda: activate(doc, n))
                m.addAction("Update View").triggered.connect(lambda: update_view(doc, n))
                m.addAction("Rename").triggered.connect(lambda: self._rename(n))
                m.addAction("Delete").triggered.connect(lambda: delete_view(doc, n))
                m.addSeparator()
            m.addAction("Capture 3D View").triggered.connect(lambda: Gui.runCommand("SWStyle_MBDCapture3DView", 0))
            m.popup(self.list.viewport().mapToGlobal(pos))

        def _rename(self, old):
            new, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=old)
            if ok:
                rename_view(App.ActiveDocument, old, new.strip())

    def show_pane():
        mw = Gui.getMainWindow()
        dock = mw.findChild(QtWidgets.QDockWidget, "SW3DViewsDock")
        if dock is None:
            dock = QtWidgets.QDockWidget("3D Views", mw)
            dock.setObjectName("SW3DViewsDock")
            dock.setWidget(ViewsPane())
            mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
        dock.show()
        dock.raise_()
        dock.widget().refresh()
        return dock

    def _doc():
        return App.ActiveDocument

    def _picks():
        return mbd._picks() if hasattr(mbd, "_picks") else []

    class CapturePM:
        def __init__(self):
            doc = _doc()
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWMBDCapturePM")
            self.form.setWindowTitle("Capture 3D View")
            self.form.setProperty("swstyle_pm_title", "Capture 3D View")
            lay = QtWidgets.QFormLayout(self.form)
            self.name = QtWidgets.QLineEdit("3DView%d" % (len(views(doc)) + 1))
            self.name.setObjectName("SWMBDCaptureName")
            lay.addRow("3D view name", self.name)
            self.config = QtWidgets.QComboBox()
            self.config.setObjectName("SWMBDCaptureConfig")
            try:
                from . import configmanager
                t = configmanager.table(doc)
                cfgs, on = (list(t.names()), t.active()) if t else ([], None)
            except Exception:
                cfgs, on = [], None
            self.config.addItems(cfgs or ["Default"])
            if on in cfgs:
                self.config.setCurrentText(on)
            self.config_known = bool(cfgs)
            lay.addRow("Configuration to capture", self.config)
            self.display = QtWidgets.QComboBox()
            self.display.setObjectName("SWMBDCaptureDisplayState")
            states, on = display_states(doc)
            self.display.addItems(states)
            if on:
                self.display.setCurrentText(on)
            lay.addRow("Display state to capture", self.display)
            if not states:                  # nothing to choose: no row (never an empty box)
                self.display.hide()
                lay.labelForField(self.display).hide()
            self.annots = QtWidgets.QListWidget()
            self.annots.setObjectName("SWMBDCaptureAnnotations")
            for o in doc.Objects:
                if mbd.is_pmi(o):
                    it = QtWidgets.QListWidgetItem(o.Label)
                    it.setData(256, o.Name)
                    it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                    it.setCheckState(QtCore.Qt.Checked if o.ViewObject.Visibility else QtCore.Qt.Unchecked)
                    self.annots.addItem(it)
            lay.addRow("Annotations to capture", self.annots)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            shown = [self.annots.item(i).data(256) for i in range(self.annots.count())
                     if self.annots.item(i).checkState() == QtCore.Qt.Checked]
            Gui.Control.closeDialog()
            capture(_doc(), self.name.text().strip() or None, shown,
                    config=self.config.currentText() if self.config_known else None,
                    display=self.display.currentText() or None)
            show_pane()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    class AnnotPM(mbd.PickPM):
        """Note / Surface Finish / Weld Symbol / Reference Dimension pages on mbd's pick page."""

    def _note_extra(lay):
        e = QtWidgets.QPlainTextEdit()
        e.setObjectName("SWMBDNoteText")
        e.setMaximumHeight(80)
        lay.addRow("Text", e)
        return e

    def _sf_extra(lay):
        sym = QtWidgets.QComboBox()
        sym.addItems(list(SURFACE))
        sym.setCurrentText("Machining required")
        ra = QtWidgets.QLineEdit("3.2")
        method = QtWidgets.QLineEdit()
        lay_ = QtWidgets.QComboBox()
        lay_.addItems(["", "=", "⟂", "X", "M", "C", "R"])
        lay.addRow("Symbol", sym)
        lay.addRow("Roughness (Ra)", ra)
        lay.addRow("Production method", method)
        lay.addRow("Lay direction", lay_)
        return sym, ra, method, lay_

    def _weld_extra(lay):
        kind = QtWidgets.QComboBox()
        kind.addItems(list(WELDS))
        size = QtWidgets.QLineEdit("5")
        both = QtWidgets.QCheckBox("Both sides")
        around = QtWidgets.QCheckBox("All around")
        field = QtWidgets.QCheckBox("Field/site weld")
        lay.addRow("Weld symbol", kind)
        lay.addRow("Size", size)
        lay.addRow(both)
        lay.addRow(around)
        lay.addRow(field)
        return kind, size, both, around, field

    SPECS = {
        "SWStyle_MBDReferenceDimension": ("Reference Dimension", 2, lambda pm, p: reference_dimension(
            _doc(), p[0], p[1]), None, "Pick the two items"),
        "SWStyle_MBDNote": ("Note", 1, lambda pm, p: note(_doc(), pm.extra.toPlainText() or "NOTE", p[0]),
                            _note_extra, "Type the note, then pick where its leader goes"),
        "SWStyle_MBDSurfaceFinish": ("Surface Finish", 1, lambda pm, p: surface_finish(
            _doc(), p[0], pm.extra[0].currentText(), pm.extra[1].text(), pm.extra[2].text(), pm.extra[3].currentText()),
            _sf_extra, "Pick the face"),
        "SWStyle_MBDWeldSymbol": ("Weld Symbol", 1, lambda pm, p: weld_symbol(
            _doc(), p[0], pm.extra[0].currentText(), pm.extra[1].text(), pm.extra[2].isChecked(),
            pm.extra[3].isChecked(), pm.extra[4].isChecked()), _weld_extra, "Pick the edge or face"),
        "SWStyle_MBDAutoPair": ("Auto Pair Tolerance", 1, lambda pm, p: auto_pair(_doc(), p[0][0], p[0][1]), None,
                                "Pick a hole of the pattern"),
    }

    class _Pick:
        def __init__(self, name):
            self.name = name

        def GetResources(self):
            return {"MenuText": SPECS[self.name][0], "ToolTip": mbd.TIPS.get(self.name, SPECS[self.name][0])}   # extapps135

        def IsActive(self):
            return _doc() is not None and not Gui.Control.activeDialog()

        def Activated(self):
            title, need, run, extra, hint = SPECS[self.name]
            Gui.Control.showDialog(mbd.PickPM(title, need, run, extra, hint))

    class _Simple:
        def __init__(self, text, tip, run, active=None):
            self.text, self.tip, self.run, self.active = text, tip, run, active

        def GetResources(self):
            resources = {"MenuText": self.text, "ToolTip": self.tip}
            if self.text == "Dynamic Annotation Views":
                from . import icons
                resources["Pixmap"] = icons.pixmap_path("FW_MBD_Dynamic")
            return resources

        def IsActive(self):
            return _doc() is not None and (self.active is None or self.active())

        def Activated(self):
            self.run()

    def _ask_path(title, filt, suffix):
        doc = _doc()
        base = os.path.splitext(doc.FileName)[0] if doc.FileName else doc.Label
        return QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), title, base + suffix, filt)[0]

    def _publish_pdf():
        p = _ask_path("Publish to 3D PDF", "PDF (*.pdf)", ".pdf")
        if p:
            n = publish_pdf(_doc(), p)
            App.Console.PrintMessage("Publish to 3D PDF: %d page(s) in %s\n" % (n, p))

    def _publish_step():
        p = _ask_path("Publish STEP 242", "STEP (*.step *.stp)", ".step")
        if p:
            publish_step242(_doc(), p)

    class TemplateDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("3D PDF Template Editor")
            self.setObjectName("SWMBDTemplateEditor")
            lay = QtWidgets.QFormLayout(self)
            self.edits = {}
            now = template()
            for k, _d in TEMPLATE_FIELDS:
                if k == "Paper":
                    w = QtWidgets.QComboBox()
                    w.addItems(["A4", "A3", "Letter"])
                    w.setCurrentText(now[k])
                elif k == "Orientation":
                    w = QtWidgets.QComboBox()
                    w.addItems(["Landscape", "Portrait"])
                    w.setCurrentText(now[k])
                else:
                    w = QtWidgets.QLineEdit(now[k])
                self.edits[k] = w
                lay.addRow(k, w)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def accept(self):
            set_template(**{k: (w.currentText() if isinstance(w, QtWidgets.QComboBox) else w.text())
                            for k, w in self.edits.items()})
            super().accept()

    class CompareDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("3D PMI Compare")
            self.setObjectName("SWMBDCompare")
            self.resize(640, 380)
            lay = QtWidgets.QVBoxLayout(self)
            row = QtWidgets.QHBoxLayout()
            self.a = QtWidgets.QComboBox()
            self.b = QtWidgets.QComboBox()
            for d in App.listDocuments().values():
                self.a.addItem(d.Label, d.Name)
                self.b.addItem(d.Label, d.Name)
            if self.b.count() > 1:
                self.b.setCurrentIndex(1)
            go = QtWidgets.QPushButton("Compare")
            go.clicked.connect(self.run)
            row.addWidget(QtWidgets.QLabel("Reference"))
            row.addWidget(self.a)
            row.addWidget(QtWidgets.QLabel("Modified"))
            row.addWidget(self.b)
            row.addWidget(go)
            lay.addLayout(row)
            self.table = QtWidgets.QTableWidget(0, 4)
            self.table.setHorizontalHeaderLabels(["Annotation", "Reference", "Modified", "Result"])
            self.table.horizontalHeader().setStretchLastSection(True)
            lay.addWidget(self.table)

        def run(self):
            rows = compare(App.getDocument(self.a.currentData()), App.getDocument(self.b.currentData()))
            self.table.setRowCount(0)
            colours = {"changed": "#fff2b3", "added": "#c8f0c8", "removed": "#f6c6c6"}
            for r in rows:
                i = self.table.rowCount()
                self.table.insertRow(i)
                for c, v in enumerate(r):
                    it = QtWidgets.QTableWidgetItem(v)
                    if r[3] in colours:
                        it.setBackground(QtGui.QColor(colours[r[3]]))
                        it.setForeground(QtGui.QColor("#202020"))     # extapps133: dark text on the pastel row in every theme
                    self.table.setItem(i, c, it)
            return rows

    class CopySchemeDialog(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Copy Scheme")
            self.setObjectName("SWMBDCopyScheme")
            from . import configmanager
            t = configmanager.table(_doc())
            names = t.names() if t else ["Default"]
            lay = QtWidgets.QFormLayout(self)
            self.source = QtWidgets.QComboBox()
            self.source.addItems(names)
            if t:
                self.source.setCurrentText(t.active())
            self.targets = QtWidgets.QListWidget()
            for n in names:
                it = QtWidgets.QListWidgetItem(n)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Unchecked)
                self.targets.addItem(it)
            lay.addRow("Source configuration", self.source)
            lay.addRow("Target configurations", self.targets)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def accept(self):
            doc = _doc()
            targets = [self.targets.item(i).text() for i in range(self.targets.count())
                       if self.targets.item(i).checkState() == QtCore.Qt.Checked]
            doc.openTransaction("Copy Scheme")
            try:
                copy_scheme(doc, self.source.currentText(), targets)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            super().accept()

    def _has_pmi():
        d = _doc()
        return d is not None and any(mbd.is_pmi(o) for o in d.Objects)

    def _has_configs():
        try:
            from . import configmanager
            t = configmanager.table(_doc())
            return t is not None and len(t.names()) > 1 and _has_pmi()
        except Exception:
            return False

    COMMANDS = {
        "SWStyle_MBDCapture3DView": ("Capture 3D View", "Saves the view, its annotations and configuration as a 3D view.",
                                     lambda: Gui.Control.showDialog(CapturePM()), lambda: not Gui.Control.activeDialog()),
        "SWStyle_MBD3DViews": ("3D Views", "Shows the 3D Views tab.", show_pane, None),
        "SWStyle_MBDDynamicViews": ("Dynamic Annotation Views", "Annotations show only in the view they were made in.",
                                    lambda: set_dynamic_views(_doc(), not dynamic_views(_doc())), None),
        "SWStyle_MBDPublishPDF": ("Publish to 3D PDF", "A PDF of the 3D views with the title block and annotations.",
                                  _publish_pdf, None),
        "SWStyle_MBDPDFTemplate": ("3D PDF Template Editor", "The title block fields and paper of published PDFs.",
                                   lambda: TemplateDialog().exec_(), None),
        "SWStyle_MBDPublishSTEP": ("Publish STEP 242", "Saves the part as STEP AP242.", _publish_step, None),
        "SWStyle_MBDCompare": ("3D PMI Compare", "The annotations of two parts side by side.",
                               lambda: CompareDialog().exec_(), None),
        "SWStyle_MBDCopyScheme": ("Copy Scheme", "Copies a configuration's annotations to other configurations.",
                                  lambda: CopySchemeDialog().exec_(), _has_configs),
    }

    def register():
        have = set(Gui.listCommands())
        for name in SPECS:
            if name not in have:
                Gui.addCommand(name, _Pick(name))
        for name, (text, tip, run, active) in COMMANDS.items():
            if name not in have:
                Gui.addCommand(name, _Simple(text, tip, run, active))
        try:
            from . import checkstate
            checkstate.register("SWStyle_MBDDynamicViews", lambda: bool(_doc() is not None and dynamic_views(_doc())))
        except Exception as _fw_err:
            _fw_log("mbdtab.py:dynamic-state", _fw_err)


# key, label, command, caption, icon family
KEYS = (("MBD_RefDim", "Smart Dimension", "SWStyle_MBDReferenceDimension", "Smart\nDimension"),
        ("MBD_Note", "Note", "SWStyle_MBDNote", None),
        ("MBD_SurfaceFinish", "Surface Finish", "SWStyle_MBDSurfaceFinish", "Surface\nFinish"),
        ("MBD_Weld", "Weld Symbol", "SWStyle_MBDWeldSymbol", "Weld\nSymbol"),
        ("MBD_Capture", "Capture 3D View", "SWStyle_MBDCapture3DView", "Capture\n3D View"),
        ("MBD_Views", "3D Views", "SWStyle_MBD3DViews", "3D\nViews"),
        ("MBD_Dynamic", "Dynamic Annotation Views", "SWStyle_MBDDynamicViews", "Dynamic\nAnnotation Views"),
        ("MBD_PDF", "Publish to 3D PDF", "SWStyle_MBDPublishPDF", "Publish to\n3D PDF"),
        ("MBD_PDFTemplate", "3D PDF Template Editor", "SWStyle_MBDPDFTemplate", "3D PDF\nTemplate Editor"),
        ("MBD_STEP", "Publish STEP 242", "SWStyle_MBDPublishSTEP", "Publish\nSTEP 242"),
        ("MBD_Compare", "3D PMI Compare", "SWStyle_MBDCompare", "3D PMI\nCompare"),
        ("MBD_CopyScheme", "Copy Scheme", "SWStyle_MBDCopyScheme", "Copy\nScheme"),
        ("MBD_AutoPair", "Auto Pair Tolerance", "SWStyle_MBDAutoPair", "Auto Pair\nTolerance"))


# model), Exploded View (a part has none; an assembly's MBD tab comes from asmtabs) and Publish to eDrawings (no

# View, General Profile Tolerance under Geometric Tolerance, Auto Pair and Delete All under Show Tolerance Status.
TAB = ("MBD", (
    ("large", "MBD_Auto", None), ("large", "MBD_Location", None), ("large", "MBD_Size", None),
    ("large", "MBD_Angle", None), ("large", "MBD_BasicLocation", ("MBD_BasicLocation", "MBD_BasicSize")),
    ("large", "MBD_Datum", None), ("large", "MBD_DatumTarget", None),
    ("large", "MBD_GTol", ("MBD_GTol", "MBD_GenProfile")), ("large", "MBD_Pattern", None),
    ("large", "MBD_CopyScheme", None), ("large", "MBD_ImportScheme", None),
    ("large", "MBD_Status", ("MBD_Status", "MBD_AutoPair", "MBD_DeleteAll")),
    ("large", "MBD_SurfaceFinish", None), ("large", "MBD_Weld", None), ("large", "MBD_Note", None),
    ("large", "MBD_RefDim", None),
    ("sep",),
    ("large", "MBD_Capture", ("MBD_Capture", "MBD_Views")), ("large", "SectionView", None),
    ("large", "ModelBreakView", None), ("large", "MBD_Dynamic", None),
    ("sep",),
    ("large", "MBD_PDFTemplate", None), ("large", "MBD_PDF", None), ("large", "MBD_STEP", None),
    ("large", "MBD_Compare", None),
))
