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
from . import drawtables as DT

KIND = "FamilyTable"
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"


def letter(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, len(LETTERS))
        s = LETTERS[r] + s
    return s


def model_of(view):
    for o in DV.source_shapes(view) if view is not None else []:
        o = getattr(o, "LinkedObject", o) or o
        return o.Document
    return None


def _table(model):
    from . import configmanager as cm
    return cm.table(model) if model is not None else None


def _text(sheet, cell):
    try:
        v = sheet.get(cell)
    except Exception:
        return ""
    if isinstance(v, float) and abs(v - round(v)) < 1e-9:
        v = int(round(v))
    return str(getattr(v, "UserString", v))


def parameters(model):
    """The design table's parameter names (column aliases or header text), in the table's order."""
    t = _table(model)
    if t is None:
        return []
    out = []
    for c in t.columns():
        cell = "%s%d" % (c, t.first - 1)
        try:
            name = t.sheet.getAlias(cell) or _text(t.sheet, cell)
        except Exception:
            name = _text(t.sheet, cell)
        if name:
            out.append((name, c))
    return out


def configurations(model):
    t = _table(model)
    if t is None:
        return []
    names = []
    for r in range(t.first, t.last + 1):
        n = _text(t.sheet, "%s%d" % (t.col, r))
        if n:
            names.append(n)
    return names


def values(model):
    """{configuration: {parameter: text}}."""
    t = _table(model)
    if t is None:
        return {}
    cols = parameters(model)
    out = {}
    for r in range(t.first, t.last + 1):
        n = _text(t.sheet, "%s%d" % (t.col, r))
        if n:
            out[n] = {name: _text(t.sheet, "%s%d" % (c, r)) for name, c in cols}
    return out


def _number(text):
    try:
        return float(str(text).split()[0].replace(",", "."))
    except Exception:
        return None


def _dim_value(dim):
    try:
        return float(dim.getRawValue())
    except Exception:
        return None


def match(dim, model, used=()):
    """The parameter a dimension shows: its value equals that parameter's value in the configuration shown
    (one parameter only), else None."""
    t = _table(model)
    v = _dim_value(dim)
    if t is None or v is None:
        return None
    active = t.active()
    row = values(model).get(active) or {}
    hits = [p for p, text in row.items() if p not in used and _number(text) is not None and abs(_number(text) - v) < 1e-6]
    return hits[0] if len(hits) == 1 else None


def rows(model, params, configs=None, letters=None, names=False):
    """The table: Configuration and a column per parameter (its letter, or its name), a row per configuration;
    names adds the parameter names under the letters."""
    vals = values(model)
    configs = [c for c in (configs or configurations(model)) if c in vals]
    letters = letters or {}
    head = ["Configuration"] + [letters.get(p) or p for p in params]
    out = [head]
    if names and letters:
        out.append([""] + list(params))
    for c in configs:
        out.append([c] + [vals[c].get(p, "") for p in params])
    return out


def _dims_of(t):
    """{parameter: dimension} as stored on the table ("parameter=DimensionName")."""
    out = {}
    for entry in getattr(t, "SWFamilyDims", []) or []:
        p, _, name = entry.partition("=")
        o = t.Document.getObject(name)
        if o is not None:
            out[p] = o
    return out


def show_letter(dim, text):
    """The dimension shows its letter in place of its value (the value is kept to put back)."""
    if not hasattr(dim, "SWFamilyFormat"):
        dim.addProperty("App::PropertyString", "SWFamilyFormat", "FreeCAD", "the format before the family letter")
        dim.SWFamilyFormat = "%d|%s" % (int(bool(getattr(dim, "Arbitrary", False))), dim.FormatSpec)
    dim.Arbitrary = True               # TechDraw shows FormatSpec as the text, not the value
    dim.FormatSpec = text


def show_value(dim):
    if hasattr(dim, "SWFamilyFormat"):
        arb, _, spec = dim.SWFamilyFormat.partition("|")
        dim.FormatSpec = spec
        dim.Arbitrary = arb == "1"
        dim.removeProperty("SWFamilyFormat")


def make_family_table(page, view, params=None, configs=None, dims=None, as_letters=True, names=False, at=None):
    """Insert > Tables > Family Table for the model in view. params: the parameters (columns), all by default;
    dims: {parameter: dimension} shown as that column's letter."""
    model = model_of(view)
    if model is None:
        raise ValueError("Pick a drawing view of a part or assembly with configurations.")
    allp = [p for p, _c in parameters(model)]
    if not allp:
        raise ValueError("%s has no design table, so it has no family to tabulate." % model.Label)
    params = [p for p in (params or allp) if p in allp]
    letters = {p: letter(i) for i, p in enumerate(params)} if as_letters else {}
    rs = rows(model, params, configs, letters, names)
    if at is None:
        a, b, c, d = DV.view_box(view)
        at = (a, b - 10 - 4 * len(rs))
    t = DT.make_table(page, rs, at, "Family Table", KIND, [40] + [22] * len(params))
    t.addProperty("App::PropertyString", "SWBomView", "FreeCAD", "the view the table is of")
    t.SWBomView = view.Name
    t.addProperty("App::PropertyStringList", "SWFamilyParams", "FreeCAD", "the design table parameters (columns)")
    t.SWFamilyParams = params
    t.addProperty("App::PropertyStringList", "SWFamilyConfigs", "FreeCAD", "the configurations listed (empty: all)")
    t.SWFamilyConfigs = list(configs or [])
    t.addProperty("App::PropertyBool", "SWFamilyLetters", "FreeCAD", "dimensions shown as letters")
    t.SWFamilyLetters = bool(as_letters)
    t.addProperty("App::PropertyBool", "SWFamilyNames", "FreeCAD", "parameter names under the letters")
    t.SWFamilyNames = bool(names)
    t.addProperty("App::PropertyStringList", "SWFamilyDims", "FreeCAD", "parameter=dimension")
    dims = dict(dims or {})
    t.SWFamilyDims = ["%s=%s" % (p, d.Name) for p, d in dims.items() if p in params]
    if as_letters:
        for p, d in dims.items():
            if p in letters:
                show_letter(d, letters[p])
    return t


def refresh(t):
    """Update Table / the design table changed: the rows again, the letters kept."""
    view = t.Document.getObject(getattr(t, "SWBomView", "") or "")
    model = model_of(view)
    if model is None:
        return False
    allp = [p for p, _c in parameters(model)]
    params = [p for p in t.SWFamilyParams if p in allp]
    letters = {p: letter(i) for i, p in enumerate(params)} if t.SWFamilyLetters else {}
    rs = rows(model, params, list(t.SWFamilyConfigs) or None, letters, t.SWFamilyNames)
    if rs != DT.rows_of(t):
        DT.set_rows(t, rs)
        return True
    return False


def release(t):
    """The table deleted: its dimensions show their values again."""
    for d in _dims_of(t).values():
        show_value(d)


class FamilyTablePanel(D._Panel):
    TITLE = "Family Table"
    LAYER = True
    PIXMAP = "TechDraw_SpreadsheetView"

    def build(self):
        self.say("Click the drawing view of the part family, pick the columns and the dimensions that show letters, "
                 "then click where the table goes.")
        DT._template_group(self, ("standard family table",), "standard family table")
        DT._position_group(self, False)
        box, lay = D._group("Configurations", self.form)
        self.configs = QtWidgets.QListWidget(box)
        self.configs.setObjectName("SWFamilyConfigs")
        self.configs.setMaximumHeight(110)
        lay.addWidget(self.configs)
        self.lay.addWidget(box)
        box, lay = D._group("Columns", self.form)
        self.columns = QtWidgets.QListWidget(box)
        self.columns.setObjectName("SWFamilyColumns")
        self.columns.setMaximumHeight(130)
        lay.addWidget(self.columns)
        tip = QtWidgets.QLabel("Pick a dimension on the sheet to show the picked column's letter on it.", box)
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.lay.addWidget(box)
        box, lay = D._group("Options", self.form)
        self.as_letters = QtWidgets.QCheckBox("Display dimensions as letters", box)
        self.as_letters.setObjectName("SWFamilyAsLetters")
        self.as_letters.setChecked(True)
        self.names = QtWidgets.QCheckBox("Show parameter names", box)
        self.names.setObjectName("SWFamilyNames")
        lay.addWidget(self.as_letters)
        lay.addWidget(self.names)
        self.lay.addWidget(box)
        DT._border_group(self)
        self.view = None
        self.model = None
        self.table = None
        self.dims = {}
        Gui.Selection.addObserver(self)
        self._picks_were = None
        try:            # picks on the sheet belong to this PM: no Dimension or Drawing View PM in its place
            from . import drawselect
            self._picks_were = drawselect.ENABLED[0]
            drawselect.ENABLED[0] = False
        except Exception as _fw_err:
            _fw_log("drawfamily.py:284", _fw_err)
        v = DT._picked_view(self.page) if [o for o in Gui.Selection.getSelection()
                                          if o.isDerivedFrom("TechDraw::DrawViewPart")] else None
        if v is not None:
            self.use_view(v)

    # ---- picks
    def use_view(self, v):
        model = model_of(v)
        if model is None or not parameters(model):
            self.say("That view's model has no design table. Click a view of a part with configurations.")
            return False
        self.view, self.model = v, model
        self.configs.clear()
        for c in configurations(model):
            it = QtWidgets.QListWidgetItem(c)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            self.configs.addItem(it)
        self.columns.clear()
        for p, _c in parameters(model):
            it = QtWidgets.QListWidgetItem(p)
            it.setData(QtCore.Qt.UserRole, p)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            self.columns.addItem(it)
        if self.columns.count():
            self.columns.setCurrentRow(0)
        # dimensions of the view whose value is one parameter's: tied on their own
        used = set()
        for o in self.doc.Objects:
            if o.isDerivedFrom("TechDraw::DrawViewDimension") and o in self.page.Views:
                refs = getattr(o, "References2D", []) or []
                if refs and refs[0][0] is v:
                    p = match(o, model, used)
                    if p:
                        self.dims[p] = o
                        used.add(p)
        self.label_columns()
        self.say("Pick dimensions for the columns, then click where the table goes (or OK for the anchor point).")
        return True

    def label_columns(self):
        params = self.params()
        for i in range(self.columns.count()):
            it = self.columns.item(i)
            p = it.data(QtCore.Qt.UserRole)
            mark = ("%s  " % letter(params.index(p))) if p in params else ""
            d = self.dims.get(p)
            it.setText("%s%s%s" % (mark, p, ("  (%s)" % d.Label) if d is not None else ""))

    def params(self):
        return [self.columns.item(i).data(QtCore.Qt.UserRole) for i in range(self.columns.count())
                if self.columns.item(i).checkState() == QtCore.Qt.Checked]

    def picked_configs(self):
        return [self.configs.item(i).text() for i in range(self.configs.count())
                if self.configs.item(i).checkState() == QtCore.Qt.Checked]

    def tie(self, dim):
        it = self.columns.currentItem()
        if it is None:
            return
        p = it.data(QtCore.Qt.UserRole)
        for k, d in list(self.dims.items()):
            if d is dim:
                del self.dims[k]
        self.dims[p] = dim
        self.label_columns()

    def addSelection(self, doc, name, sub, pos):
        if self.view is None or doc != self.doc.Name:
            return
        o = self.doc.getObject(name)
        if o is not None and o.isDerivedFrom("TechDraw::DrawViewDimension"):
            self.tie(o)

    def sheet_click(self, p):
        if self.table is not None:
            return False
        if self.view is None:
            v = DV.view_at(self.page, p)
            if v is None:
                self.say("Click the drawing view of the part family.")
                return True
            self.use_view(v)
            return True
        self.make(p)
        return True

    # ---- table
    def make(self, at):
        all_configs = self.picked_configs()
        configs = all_configs if len(all_configs) < self.configs.count() else None
        self.table = make_family_table(self.page, self.view, self.params(), configs, self.dims,
                                       self.as_letters.isChecked(), self.names.isChecked(), at)
        DT._apply_border(self, self.table)
        self.made.append(self.table)
        if self.attach.isChecked():
            DT.attach(self.table)

    def finish(self):
        if self.table is None and self.view is not None:
            self.make(DT.anchor(self.page, "General") if self.attach.isChecked() else None)

    def _stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("drawfamily.py:393", _fw_err)
        if self._picks_were is not None:
            from . import drawselect
            drawselect.ENABLED[0] = self._picks_were
            self._picks_were = None

    def accept(self):
        self._stop()
        return D._Panel.accept(self)

    def reject(self):
        self._stop()
        return D._Panel.reject(self)


COMMAND = "FreeWorks_DrawFamilyTable"


class _Command:
    def GetResources(self):
        return {"MenuText": "Family Table", "Pixmap": D.pixmap("TechDraw_SpreadsheetView"),
                "ToolTip": "Adds a family table: a row per configuration with the values of the dimensions "
                           "shown as letters (a tabulated drawing)."}

    def IsActive(self):
        page = D.active_page()
        return page is not None and bool(D.views_of(page))

    def Activated(self):
        page = D.active_page()
        if page is not None:
            D._show(FamilyTablePanel(page))


class _Deleted:
    """A family table deleted: its dimensions show their values again."""

    def slotDeletedObject(self, obj):
        try:
            if getattr(obj, "SWTable", "") == KIND:
                release(obj)
        except Exception as _fw_err:
            _fw_log("drawfamily.py:435", _fw_err)


_OBSERVER = []


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Command())
    if not _OBSERVER:
        _OBSERVER.append(_Deleted())
        App.addDocumentObserver(_OBSERVER[0])
    _hook_tables()


def _hook_tables():
    """Update Table and the Tables flyout know the family table (drawtables keeps its own names)."""
    if getattr(DT.update_table, "_fw_family", False):
        return
    original = DT.update_table

    def update_table(t):
        if getattr(t, "SWTable", "") == KIND:
            return refresh(t)
        return original(t)
    update_table._fw_family = True
    update_table.__doc__ = original.__doc__
    DT.update_table = update_table
    try:
        from . import catalog
        if "DrawFamilyTable" not in catalog.BY_KEY:
            catalog.BY_KEY["DrawFamilyTable"] = catalog.c("DrawFamilyTable", "Family Table", (COMMAND,), None,
                                                          "A row per configuration with the dimensions shown as letters.")
            catalog.ALL = tuple(catalog._ALL)
        tabs = []
        for e in catalog.ANNOTATION:
            if e[0] == "large" and e[1] == "DrawGeneralTable" and e[2] and "DrawFamilyTable" not in e[2]:
                fly = list(e[2])
                at = fly.index("DrawRevisionTable") + 1 if "DrawRevisionTable" in fly else len(fly)
                fly.insert(at, "DrawFamilyTable")
                e = ("large", e[1], tuple(fly))
            tabs.append(e)
        catalog.ANNOTATION = tuple(tabs)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Family Table in the Tables flyout: %s\n" % error)
