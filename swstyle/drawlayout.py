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
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawviews as DV


def picked_views():
    out = []
    for o in Gui.Selection.getSelection():
        if o.TypeId == "TechDraw::DrawProjGroup":
            out += [v for v in o.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]
        elif o.isDerivedFrom("TechDraw::DrawViewPart"):
            out.append(o)
    return out


# --------------------------------------------------------------------------- Update View
def update_views(page, views=None):
    """Update View: the picked views (else every view on the sheet) made again from the model."""
    views = views or [v for v in D.views_of(page)]
    for v in views:
        try:
            v.touch()
        except Exception as _fw_err:
            _fw_log("drawlayout.py:43", _fw_err)
    from . import drawviews as DV
    DV.project_now(page, views)       # also on a sheet with Update View off (TechDraw skips its views there)
    for v in views:
        try:
            from . import drawviewcmds, drawshade
            drawviewcmds.refresh_tangents(v)         # the With Font tangent lines and a shaded picture
            drawshade.refresh(v)                     # follow the model too
        except Exception as _fw_err:
            _fw_log("drawlayout.py:52", _fw_err)
    page.Document.recompute()
    return views


# --------------------------------------------------------------------------- Replace Model
def replace_model(views, doc):
    """Replace Model: the views (and the views made from them) show doc's model instead."""
    shapes = D.model_shapes(doc)
    if not shapes:
        return []
    done = []
    todo = list(views)
    while todo:
        v = todo.pop()
        if v in done:
            continue
        if not D.saved_source(doc, v.Document):
            return done
        v.XSource = list(shapes)
        try:
            v.Source = []
        except Exception as _fw_err:
            _fw_log("drawlayout.py:75", _fw_err)
        done.append(v)
        for o in v.Document.Objects:
            if o.isDerivedFrom("TechDraw::DrawViewPart") and (getattr(o, "SWParent", "") == v.Name or
                                                            getattr(o, "BaseView", None) is v):
                todo.append(o)
    views[0].Document.recompute()
    return done


class ReplaceModelPanel(D._SourcePick, D._Panel):
    TITLE = "Replace Model"
    PIXMAP = "TechDraw_View"

    def build(self):
        self.say("Select the drawing views to change, and the new model, then OK.")
        box, lay = D._group("Selected Views", self.form)
        self.views_list = QtWidgets.QListWidget(box)
        self.views_list.setObjectName("SWReplaceViews")
        self.views_list.setMaximumHeight(80)
        lay.addWidget(self.views_list)
        self.all_views = QtWidgets.QRadioButton("All views", box)
        self.all_views.setObjectName("SWReplaceAll")
        self.sel_views = QtWidgets.QRadioButton("Selected views", box)
        self.sel_views.setObjectName("SWReplaceSelected")
        self.sel_views.setChecked(True)
        lay.addWidget(self.sel_views)
        lay.addWidget(self.all_views)
        self.lay.addWidget(box)
        self.source_group()
        for v in picked_views():
            self.views_list.addItem(v.Label)
        self.picked = picked_views()
        if not self.picked:                 # nothing picked: All views, until views are picked in the sheet
            self.all_views.setChecked(True)
        self._timer = QtCore.QTimer(self.form)
        self._timer.timeout.connect(self._follow_selection)
        self._timer.start(400)

    def _follow_selection(self):
        now = picked_views()
        if now and [v.Name for v in now] != [v.Name for v in self.picked]:
            self.picked = now
            self.views_list.clear()
            for v in now:
                self.views_list.addItem(v.Label)
            self.sel_views.setChecked(True)

    def finish(self):
        doc = self.source()
        if doc is None:
            return
        views = D.views_of(self.page) if self.all_views.isChecked() else self.picked
        if views:
            self.made = []
            replace_model(views, doc)


# --------------------------------------------------------------------------- Format Painter
STYLE_PROPS = ("Fontsize", "Font", "Color", "LineWidth", "Arrowsize", "ArrowStyle", "LineStyle", "TextColor")


def paint_format(src, dst):
    """Format Painter: src's look (font, size, colour, line width, arrows) onto dst."""
    n = 0
    a, b = getattr(src, "ViewObject", None), getattr(dst, "ViewObject", None)
    if a is None or b is None:
        return 0
    for name in STYLE_PROPS:
        if name in a.PropertiesList and name in b.PropertiesList:
            try:
                setattr(b, name, getattr(a, name))
                n += 1
            except Exception as _fw_err:
                _fw_log("drawlayout.py:149", _fw_err)
    for name in ("SWNoteFormat", "SWNoteFontSize"):
        if name in src.PropertiesList and name in dst.PropertiesList:
            try:
                setattr(dst, name, getattr(src, name))
                n += 1
            except Exception as _fw_err:
                _fw_log("drawlayout.py:156", _fw_err)
    return n


class FormatPainterPanel(D._Panel):
    TITLE = "Format Painter"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Select the dimension or annotation to copy the format from, then the ones to paste it to.")
        box, lay = D._group("Source", self.form)
        self.src_label = QtWidgets.QLabel("(none)", box)
        self.src_label.setObjectName("SWPainterSource")
        lay.addWidget(self.src_label)
        self.lay.addWidget(box)
        box, lay = D._group("Destination", self.form)
        self.dst_list = QtWidgets.QListWidget(box)
        self.dst_list.setObjectName("SWPainterTargets")
        self.dst_list.setProperty("swpickbox", True)
        self.dst_list.setMaximumHeight(90)
        lay.addWidget(self.dst_list)
        self.lay.addWidget(box)
        self.src = None
        self.timer = QtCore.QTimer(self.form)      # goes with the PM, however it closes
        self.timer.timeout.connect(self.poll)
        self.timer.start(150)
        self.seen = set()

    def poll(self):
        try:
            self.src_label.objectName()
        except RuntimeError:                        # the PM was closed by another command: stop
            try:
                self.timer.stop()
            except RuntimeError as _fw_err:
                _fw_log("drawlayout.py:190", _fw_err)
            return
        try:
            sel = [o for o in Gui.Selection.getSelection() if o.ViewObject is not None and
                   not o.isDerivedFrom("TechDraw::DrawViewPart") and o.TypeId != "TechDraw::DrawPage"]
        except Exception:
            return
        for o in sel:
            if o.Name in self.seen:
                continue
            self.seen.add(o.Name)
            if self.src is None:
                self.src = o
                self.src_label.setText(o.Label)
                self.say("Now select the dimensions or annotations to paste the format to; OK when done.")
            elif o is not self.src:
                paint_format(self.src, o)
                self.dst_list.addItem(o.Label)
                self.doc.recompute()
        if not sel:
            self.seen = set()

    def accept(self):
        self.timer.stop()
        return super().accept()

    def reject(self):
        self.timer.stop()
        return super().reject()


# --------------------------------------------------------------------------- Title Block Fields
class TitleBlockDialog(QtWidgets.QDialog):
    """Title Block Fields: the sheet format's fields and their text."""

    def __init__(self, page, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWTitleBlockFields")
        self.setWindowTitle("Title Block Fields")
        self.page = page
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget(self)
        self.table.setObjectName("SWTitleBlockTable")
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Field", "Text"])
        texts = dict(getattr(page.Template, "EditableTexts", {}) or {})
        texts.update({k: v for k, v in field_links(page).items() if k in texts})
        from . import drawtitleblock as TB
        self.keys = [k for k in TB.fields(page) if k in texts] + sorted(k for k in texts if k not in TB.fields(page))
        self.table.setRowCount(len(self.keys))
        for r, k in enumerate(self.keys):
            it = QtWidgets.QTableWidgetItem(k)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(texts[k]))
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QtWidgets.QHBoxLayout()
        self.link = QtWidgets.QPushButton("Link to Property...", self)
        self.link.setObjectName("SWTitleBlockLink")
        self.link.setToolTip("Fills the picked field from a custom property of the drawing or of the model in the "
                             "sheet's views, and keeps it up to date")
        self.link.clicked.connect(self.pick_link)
        row.addWidget(self.link)
        for text, name, step in (("Move Up", "SWTitleBlockUp", -1), ("Move Down", "SWTitleBlockDown", 1)):
            b = QtWidgets.QPushButton(text, self)
            b.setObjectName(name)
            b.setToolTip("The Tab order of the title block fill-in")
            b.clicked.connect(lambda _=False, s=step: self.move(s))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        box = QtWidgets.QGroupBox("Hotspot", self)
        box.setToolTip("The title block area a click on the sheet opens, in sheet mm")
        hl = QtWidgets.QHBoxLayout(box)
        hs = TB.hotspot(page) or (0.0, 0.0, 0.0, 0.0)
        self.hot = []
        for i, (lbl, v) in enumerate(zip(("Left", "Bottom", "Right", "Top"), hs)):
            sp = QtWidgets.QDoubleSpinBox(box)
            sp.setObjectName("SWTitleBlockHotspot%d" % i)
            sp.setRange(-10000, 10000)
            sp.setValue(float(v))
            hl.addWidget(QtWidgets.QLabel(lbl + ":", box))
            hl.addWidget(sp)
            self.hot.append(sp)
        auto = QtWidgets.QPushButton("Auto", box)
        auto.setObjectName("SWTitleBlockHotspotAuto")
        auto.setToolTip("Round the title block's fields")
        auto.clicked.connect(self.auto_hotspot)
        hl.addWidget(auto)
        lay.addWidget(box)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 420)

    def move(self, step):
        r = self.table.currentRow()
        n = r + step
        if r < 0 or not 0 <= n < len(self.keys):
            return
        for c in (0, 1):
            a, b = self.table.takeItem(r, c), self.table.takeItem(n, c)
            self.table.setItem(r, c, b)
            self.table.setItem(n, c, a)
        self.keys[r], self.keys[n] = self.keys[n], self.keys[r]
        self.table.setCurrentCell(n, 1)

    def auto_hotspot(self):
        from . import drawtitleblock as TB
        keep = list(getattr(self.page, "SWTitleHotspot", []) or [])
        if keep:
            self.page.SWTitleHotspot = []
        hs = TB.hotspot(self.page) or (0.0, 0.0, 0.0, 0.0)
        if keep:
            self.page.SWTitleHotspot = keep
        for sp, v in zip(self.hot, hs):
            sp.setValue(float(v))

    def properties(self, model):
        from . import drawannot as DA
        doc = DA.model_document(self.page) if model else self.page.Document
        names = ["Label", "CreatedBy", "Company", "Comment", "LastModifiedBy", "CreationDate", "LastModifiedDate"]
        try:
            from . import customprops          # the custom properties by name (File > Properties)
            names += [n for n, _k, _v in customprops.read(doc)]
        except Exception as _fw_err:
            _fw_log("drawlayout.py:318", _fw_err)
        try:
            names += sorted(str(k) for k in dict(doc.Meta) if not str(k).startswith("CustomProperty:"))
        except Exception as _fw_err:
            _fw_log("drawlayout.py:322", _fw_err)
        seen = set()
        names = [n for n in names if not (n in seen or seen.add(n))]
        try:
            from . import drawannot as _DA
            extra = list(_DA.SYSTEM_PROPS) + ([] if model else list(_DA.SHEET_PROPS))
        except Exception:
            extra = [] if model else ["FW-Sheet Name", "FW-Sheet Scale", "FW-Current Sheet", "FW-Total Sheets",
                                      "FW-File Name", "FW-Title"]
        names += [n for n in extra if n not in names]
        return names

    def link_property(self, name, model=False):
        """The picked field's text becomes a link to property name ($PRPSHEET: the model's, $PRP: the drawing's)."""
        r = self.table.currentRow()
        if r < 0:
            r = 0
        self.table.item(r, 1).setText('$%s:"%s"' % ("PRPSHEET" if model else "PRP", name))

    def pick_link(self):
        where, ok = QtWidgets.QInputDialog.getItem(self, "Link to Property", "Use custom properties from:",
                                                   ["Current document", "Model found here"], 0, False)
        if not ok:
            return
        model = where.startswith("Model")
        name, ok = QtWidgets.QInputDialog.getItem(self, "Link to Property", "Property name:",
                                                  self.properties(model), 0, True)
        if ok and name:
            self.link_property(name, model)

    def apply(self):
        texts = dict(getattr(self.page.Template, "EditableTexts", {}) or {})
        links = {}
        for r, k in enumerate(self.keys):
            t = self.table.item(r, 1).text()
            if "$PRP" in t:
                links[k] = t
            texts[k] = t
        doc = self.page.Document
        doc.openTransaction("Title Block Fields")
        try:
            from . import drawtitleblock as TB
            TB.set_order(self.page, self.keys)
            hs = [sp.value() for sp in self.hot]
            TB.set_hotspot(self.page, hs if hs[2] > hs[0] and hs[3] > hs[1] else [])
            set_field_links(self.page, links)
            self.page.Template.EditableTexts = resolve_fields(self.page, texts)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
        self.accept()


def field_links(page):
    import json
    try:
        return json.loads(getattr(page, "SWFieldLinks", "") or "{}")
    except ValueError:
        return {}


def set_field_links(page, links):
    import json
    if "SWFieldLinks" not in page.PropertiesList:
        page.addProperty("App::PropertyString", "SWFieldLinks", "FreeCAD", "title block fields linked to properties")
    page.SWFieldLinks = json.dumps(links, sort_keys=True)


def soft_fields(page):
    """The title block fields linked softly (the sheet format's default links): an empty property leaves the
    field's own text."""
    return list(getattr(page, "SWFieldSoft", []) or [])


def set_soft_fields(page, names):
    if "SWFieldSoft" not in page.PropertiesList:
        page.addProperty("App::PropertyStringList", "SWFieldSoft", "FreeCAD", "title block fields linked softly")
        page.setPropertyStatus("SWFieldSoft", ["Hidden"])
    page.SWFieldSoft = list(names)


def _field_shown(page):
    """Softly linked fields: {field: [the format's own text, the property value last shown]}."""
    import json
    try:
        return json.loads(getattr(page, "SWFieldShown", "") or "{}")
    except ValueError:
        return {}


def _set_field_shown(page, shown):
    import json
    try:
        if "SWFieldShown" not in page.PropertiesList:
            page.addProperty("App::PropertyString", "SWFieldShown", "FreeWorks",
                             "softly linked title block fields: own text and the value shown")
            page.setPropertyStatus("SWFieldShown", ["Hidden"])
        text = json.dumps(shown, sort_keys=True)
        if page.SWFieldShown != text:
            page.SWFieldShown = text
    except Exception as _fw_err:
        _fw_log("drawlayout.py:field_shown", _fw_err)


def resolve_fields(page, texts):
    ""


    from . import drawannot as DA
    out = dict(texts)
    soft = set(soft_fields(page))
    shown = _field_shown(page)
    before = dict((k, list(v)) for k, v in shown.items())
    for k, raw in field_links(page).items():
        if k in out:
            v = DA.resolve_properties(page, raw)
            if k in soft and not str(v).strip():
                own, last = (shown.get(k) or [None, None])[:2]
                if own is not None and out[k] == last:
                    out[k] = own
                    shown.pop(k, None)
                elif "$PRP" in str(out[k]):
                    # usage run 11-27: Title Block Fields' OK wrote the link itself as the field's own text, so the

                    out[k] = ""
                continue
            if k in soft:
                if k in shown:
                    shown[k][1] = v
                elif out[k] != v:
                    shown[k] = [out[k], v]
            out[k] = v
    if shown != before:
        _set_field_shown(page, shown)
    return out


def refresh_fields(page):
    """The linked title block fields read their properties again (after a property changed)."""
    tpl = page.Template
    if tpl is None or not field_links(page):
        return False
    texts = dict(getattr(tpl, "EditableTexts", {}) or {})
    new = resolve_fields(page, texts)
    if new != texts:
        tpl.EditableTexts = new
        return True
    return False


def editing_format(page):
    try:
        from . import drawsheet
        return drawsheet.editing_format(page)
    except Exception:
        return False


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawUpdateView": ("Update View", "TechDraw_View",
                                 "Updates the picked views (else every view on the sheet) from the model."),
    "FreeWorks_DrawReplaceModel": ("Replace Model", "TechDraw_View",
                                   "Changes the model the picked views show."),
    "FreeWorks_DrawFormatPainter": ("Format Painter", "TechDraw_Annotation",
                                    "Copies the look of one dimension or annotation onto others."),
    "FreeWorks_DrawTitleBlockFields": ("Title Block Fields", "TechDraw_PageTemplate",
                                       "Edits the title block's fields (while editing the sheet format)."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawTitleBlockFields":
            return editing_format(page)
        if self.name == "FreeWorks_DrawReplaceModel":
            return bool(picked_views()) or bool(D.views_of(page))
        if self.name == "FreeWorks_DrawUpdateView":
            return bool(D.views_of(page))
        return True

    def Activated(self):
        page = D.active_page()
        if page is None:
            return
        if self.name == "FreeWorks_DrawUpdateView":
            doc = page.Document
            doc.openTransaction("Update View")
            try:
                update_views(page, picked_views())
                refresh_fields(page)
                try:
                    from . import drawdimpm
                    drawdimpm.refresh_dimensions(doc)
                    QtCore.QTimer.singleShot(300, lambda d=doc: drawdimpm.refresh_beyond(d))
                    from . import drawdimtools
                    drawdimtools.refresh_symmetric(doc)
                    from . import drawdocprops
                    drawdocprops.broken_marks(doc)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Update View: %s\n" % error)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
        elif self.name == "FreeWorks_DrawReplaceModel":
            D._show(ReplaceModelPanel(page))
        elif self.name == "FreeWorks_DrawFormatPainter":
            D._show(FormatPainterPanel(page))
        elif self.name == "FreeWorks_DrawTitleBlockFields":
            TitleBlockDialog(page).exec_()


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
