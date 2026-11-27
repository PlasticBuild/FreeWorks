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

PART_VIEWS = ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem", "TechDraw::DrawViewSection",
              "TechDraw::DrawViewDetail", "TechDraw::DrawComplexSection")


def is_view(o):
    try:
        return o is not None and o.isDerivedFrom("TechDraw::DrawViewPart")
    except Exception:
        return False


def parent_of(v):
    ""
    doc = v.Document
    for name in ("SWParent",):
        n = getattr(v, name, "") or ""
        if n and doc.getObject(n) is not None:
            return doc.getObject(n)
    base = getattr(v, "BaseView", None)
    if is_view(base):
        return base
    for o in v.InList:
        if o.TypeId == "TechDraw::DrawProjGroup" and getattr(o, "Anchor", None) is not None and o.Anchor is not v:
            return o.Anchor
    return None


def children_of(v):
    doc = v.Document
    out = []
    for o in doc.Objects:
        if is_view(o) and o is not v and parent_of(o) is v:
            out.append(o)
    return out


def group_of(v):
    for o in v.InList:
        if o.TypeId == "TechDraw::DrawProjGroup":
            return o
    return None


def scale_holder(v):
    """What carries a view's scale: a projection group's member scales with its group."""
    return group_of(v) or v


def apply_scale(v, mode, custom=None):
    ""
    h = scale_holder(v)
    if mode == "Sheet":
        h.ScaleType = "Page"
    elif mode == "Parent":
        p = parent_of(v)
        if p is not None:
            D.follow_parent_scale(h, scale_holder(p))
        else:
            h.ScaleType = "Page"
    else:
        h.ScaleType = "Custom"
        if custom is not None:
            h.Scale = float(custom)
    D.set_scale_mode(h, mode)
    if h is not v:
        D.set_scale_mode(v, mode)
    for c in children_of(v):
        if getattr(c, "SWScaleMode", "Parent") == "Parent" and scale_holder(c) is not h:
            apply_scale(c, "Parent")


def scale_mode(v):
    h = scale_holder(v)
    mode = getattr(v, "SWScaleMode", "") or getattr(h, "SWScaleMode", "")
    if mode:
        return mode
    return "Sheet" if getattr(h, "ScaleType", "") == "Page" else "Custom"


def set_orientation(v, name):
    d, x = D.ORIENTATIONS[name]
    v.Direction = D._unit(d)
    v.XDirection = D._unit(x)
    if "SWOrientation" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWOrientation", "FreeCAD", "named view")
    v.SWOrientation = name


def _set(v, name, value, doc="Drawing View option"):
    if name not in v.PropertiesList:
        v.addProperty("App::PropertyString", name, "FreeCAD", doc)
    setattr(v, name, value)


def save_view_as(v, path=None):
    """Drawing View PM > Save View as: the one view written to a DXF file."""
    if path is None:
        import os
        start = os.path.join(os.path.dirname(v.Document.FileName or os.path.expanduser("~")), v.Label + ".dxf")
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save View as", start, "DXF (*.dxf)")
    if not path:
        return None
    import TechDraw
    TechDraw.writeDXFView(v, path)
    return path


def _setb(v, name, value):
    if name not in v.PropertiesList:
        v.addProperty("App::PropertyBool", name, "FreeCAD", "Drawing View option")
    setattr(v, name, bool(value))


SCALE_LIST = ("1:1", "1:2", "1:4", "1:5", "1:10", "1:20", "1:50", "2:1", "4:1", "5:1", "10:1", "User Defined")


class DrawingViewPanel:
    ""

    def __init__(self, view):
        self.view = view
        self.doc = view.Document
        self.page = self._page()
        self.started = False
        self.closing = False
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDrawPM")
        self.form.setWindowTitle(view.Label)
        self.form.setProperty("swstyle_pm_title", view.Label)
        self.form.setProperty("swstyle_no_box_header", True)       # no second "Drawing View2" group under OK
        self.form.setWindowIcon(QtGui.QIcon(":/icons/actions/TechDraw_View.svg"))
        self.lay = QtWidgets.QVBoxLayout(self.form)
        self.build()
        self.lay.addStretch(1)

    def _page(self):
        for o in self.view.InListRecursive:
            if o.TypeId == "TechDraw::DrawPage":
                return o
        return D.active_page()

    def _group(self, title, folded=None):
        box, lay = D._group(title, self.form, folded)
        self.lay.addWidget(box)
        return box, lay

    def build(self):
        v = self.view
        parent = parent_of(v)
        derived = v.TypeId in ("TechDraw::DrawViewSection", "TechDraw::DrawViewDetail", "TechDraw::DrawComplexSection")
        box, lay = self._group("Reference Configuration")
        self.config = QtWidgets.QComboBox(box)
        self.config.setObjectName("SWViewPMConfiguration")
        self.config.addItem((getattr(v, "SWConfiguration", "") or "Default") +
                            (" <Link to parent>" if parent is not None else ""))
        lay.addWidget(self.config)
        if parent is not None and not derived:
            self.arrow_group(v, parent)
        # Orientation: a view of its own (not projected, not a section or detail) can be turned to a named view
        box, lay = self._group("Orientation")
        self.orient = QtWidgets.QButtonGroup(box)
        grid = QtWidgets.QGridLayout()
        cur = getattr(v, "SWOrientation", "") or self._named()
        lay.addWidget(QtWidgets.QLabel("Standard views:", box))
        more = []
        for n, name in enumerate(D.ORIENTATIONS):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            D.orient_look(b, name)
            b.setCheckable(True)
            b.setObjectName("SWViewPMOrient" + name)
            b.setChecked(name == cur)
            self.orient.addButton(b, n)
            if name in D.CROSS:
                grid.addWidget(b, *D.CROSS[name])
            else:
                b.hide()
                more.append(b)
        lay.addLayout(grid)
        if more:
            self.more_label = QtWidgets.QLabel("More views:", box)
            lay.addWidget(self.more_label)
            self.more = QtWidgets.QListWidget(box)
            self.more.setObjectName("SWViewPMMoreViews")
            self.more.setMaximumHeight(52)
            for b in more:
                it = QtWidgets.QListWidgetItem("*" + b.text())
                it.setData(QtCore.Qt.UserRole, b.objectName())
                self.more.addItem(it)
                if b.isChecked():
                    self.more.setCurrentItem(it)
            self.more.itemClicked.connect(
                lambda it: next((b.click() for b in more if b.objectName() == it.data(QtCore.Qt.UserRole)), None))
            lay.addWidget(self.more)
        own = parent is None and not derived and group_of(v) is None
        # a projected or derived view follows its parent: no orientation buttons to grey out, only the note
        for b in self.orient.buttons():
            # only the standard views cross shows; the More views buttons stay hidden behind their list
            # (shown, they had no place in the grid and sat over the group's title: look audit W1)
            b.setVisible(own and b not in more)
        if getattr(self, "more", None) is not None:
            self.more.setVisible(own)
            self.more_label.setVisible(own)
        if not own:
            box.hide()
        self.orient.buttonClicked.connect(self.orientation_changed)
        if v.TypeId in ("TechDraw::DrawViewSection", "TechDraw::DrawComplexSection"):
            self.section_groups(v)
        elif v.TypeId == "TechDraw::DrawViewDetail":
            self.detail_groups(v)
        own_view = parent is None and not derived and group_of(v) is None
        if own_view:
            box, lay = self._group("Mirror")
            self.mirror = QtWidgets.QCheckBox("Mirror view", box)
            self.mirror.setObjectName("SWViewPMMirror")
            cur = getattr(v, "SWMirror", "") or ""
            self.mirror.setChecked(bool(cur))
            row = QtWidgets.QHBoxLayout()
            self.mirror_h = QtWidgets.QRadioButton("Horizontal", box)
            self.mirror_h.setObjectName("SWViewPMMirrorHorizontal")
            self.mirror_v = QtWidgets.QRadioButton("Vertical", box)
            self.mirror_v.setObjectName("SWViewPMMirrorVertical")
            (self.mirror_v if cur == "Vertical" else self.mirror_h).setChecked(True)
            row.addWidget(self.mirror_h)
            row.addWidget(self.mirror_v)
            lay.addWidget(self.mirror)
            lay.addLayout(row)
            for w in (self.mirror_h, self.mirror_v):
                # live, never greyed: picking a side turns Mirror view on
                w.clicked.connect(lambda *_: self.mirror.isChecked() or self.mirror.setChecked(True))
            for w in (self.mirror, self.mirror_h, self.mirror_v):
                w.toggled.connect(lambda *_: self.change(self._mirror))
        if own_view:
            self.import_group(v)
        box, lay = self._group("Display State")
        self.display_state = QtWidgets.QComboBox(box)
        self.display_state.setObjectName("SWViewPMDisplayState")
        self.display_state.addItem(getattr(v, "SWDisplayState", "") or "<Default>_Display State 1")
        lay.addWidget(self.display_state)
        # Display Style
        box, lay = self._group("Display Style")
        self.parent_style = QtWidgets.QCheckBox("Use parent style", box)
        self.parent_style.setObjectName("SWViewPMParentStyle")
        self.parent_style.setVisible(parent is not None)
        self.parent_style.setChecked(parent is not None and getattr(v, "SWStyleFromParent", "1") == "1"
                                     and getattr(v, "SWDisplayStyle", "") == getattr(parent, "SWDisplayStyle", ""))
        lay.addWidget(self.parent_style)
        self.style = D.StyleButtons(box, "SWViewPMDisplayStyle")
        self.style.setCurrentText(getattr(v, "SWDisplayStyle", "") or
                                  ("Hidden Lines Visible" if getattr(v, "HardHidden", False) else "Hidden Lines Removed"))
        lay.addWidget(self.style)          # live with Use parent style on too: a pick turns it off
        self.style.currentTextChanged.connect(self.style_changed)
        self.parent_style.toggled.connect(self.parent_style_changed)
        self.see_through = QtWidgets.QCheckBox("See through transparent components", box)
        self.see_through.setObjectName("SWViewPMSeeThrough")
        self.see_through.setChecked(bool(getattr(v, "SWSeeThrough", True)))
        self.see_through.toggled.connect(lambda on: self.change(lambda: _setb(v, "SWSeeThrough", on)))
        lay.addWidget(self.see_through)

        self.tangent = QtWidgets.QComboBox(box)
        self.tangent.setObjectName("SWViewPMTangent")
        from . import drawviewcmds
        self.tangent.addItems(["Tangent Edges " + m for m in drawviewcmds.TANGENT])
        mode = drawviewcmds.tangent_mode(v)
        self.tangent.setCurrentText("Tangent Edges " + mode)
        self.tangent.currentTextChanged.connect(self.tangent_changed)
        lay.addWidget(self.tangent)
        self.tangent.hide()
        # Scale
        box, lay = self._group("Scale")
        self.use_parent = QtWidgets.QRadioButton("Use parent scale", box)
        self.use_parent.setObjectName("SWViewPMUseParentScale")
        self.use_sheet = QtWidgets.QRadioButton("Use sheet scale", box)
        self.use_sheet.setObjectName("SWViewPMUseSheetScale")
        self.use_custom = QtWidgets.QRadioButton("Use custom scale", box)
        self.use_custom.setObjectName("SWViewPMUseCustomScale")
        self.use_parent.setVisible(parent is not None)
        for b in (self.use_parent, self.use_sheet, self.use_custom):
            lay.addWidget(b)

        self.scale = QtWidgets.QComboBox(box)
        self.scale.setObjectName("SWViewPMScale")
        self.scale.setEditable(False)
        self.scale.addItems(SCALE_LIST)
        lay.addWidget(self.scale)
        self.ratio = QtWidgets.QLineEdit(box)
        self.ratio.setObjectName("SWViewPMScaleRatio")
        self.ratio.setMaximumWidth(90)
        lay.addWidget(self.ratio)
        self._show_scale()
        mode = scale_mode(v)
        if mode == "Parent" and parent is None:
            mode = "Sheet"
        {"Parent": self.use_parent, "Sheet": self.use_sheet}.get(mode, self.use_custom).setChecked(True)
        self._scale_enable()
        for b in (self.use_parent, self.use_sheet, self.use_custom):
            b.toggled.connect(self.scale_mode_changed)
        self.scale.activated.connect(lambda *a: self.scale_changed())
        self.ratio.editingFinished.connect(self.ratio_changed)
        # Dimension Type
        box, lay = self._group("Dimension Type")
        self.dim_projected = QtWidgets.QRadioButton("Projected", box)
        self.dim_projected.setObjectName("SWViewPMDimProjected")
        self.dim_true = QtWidgets.QRadioButton("True", box)
        self.dim_true.setObjectName("SWViewPMDimTrue")
        (self.dim_true if getattr(v, "SWDimensionType", "") == "True" else self.dim_projected).setChecked(True)
        lay.addWidget(self.dim_projected)
        lay.addWidget(self.dim_true)
        self.dim_true.toggled.connect(lambda on: self.change(lambda: _set(v, "SWDimensionType",
                                                                          "True" if on else "Projected")))
        # Cosmetic Thread Display
        box, lay = self._group("Cosmetic Thread Display")
        self.thread_high = QtWidgets.QRadioButton("High quality", box)
        self.thread_high.setObjectName("SWViewPMThreadHigh")
        self.thread_draft = QtWidgets.QRadioButton("Draft quality", box)
        self.thread_draft.setObjectName("SWViewPMThreadDraft")
        (self.thread_high if getattr(v, "SWCosmeticThreads", "") == "High quality" else self.thread_draft).setChecked(True)
        lay.addWidget(self.thread_high)
        lay.addWidget(self.thread_draft)
        self.thread_high.toggled.connect(lambda on: self.change(lambda: _set(v, "SWCosmeticThreads",
                                                                             "High quality" if on else "Draft quality")))
        box, lay = self._group("Automatic View Update", folded=parent is None and not derived)
        self.exclude = QtWidgets.QCheckBox("Exclude from automatic update", box)
        self.exclude.setObjectName("SWViewPMExcludeUpdate")
        self.exclude.setChecked(bool(getattr(v, "SWExcludeUpdate", False)))
        self.exclude.toggled.connect(lambda on: self.change(lambda: _setb(v, "SWExcludeUpdate", on)))
        lay.addWidget(self.exclude)
        if v.isDerivedFrom("TechDraw::DrawViewPart"):
            box, lay = self._group("Save View as")
            sv = QtWidgets.QPushButton("Save As...", box)
            sv.setObjectName("SWViewPMSaveViewAs")
            sv.clicked.connect(lambda *_: save_view_as(v))
            lay.addWidget(sv)
        more = QtWidgets.QPushButton("More Properties...", self.form)
        more.setObjectName("SWViewPMMoreProperties")
        more.clicked.connect(self.more_properties)
        self.lay.addWidget(more)

    def _arrow_items(self, v):
        if self.page is None:
            return []
        return [o for o in self.page.Views if getattr(o, "SWArrowOf", "") == v.Name or
                (getattr(o, "SWLabelOf", "") == v.Name and str(o.Label).startswith("VIEW "))]

    def arrow_group(self, v, parent):
        """[ ] Arrow (on the parent, pointing at it, lettered) and VIEW X over this view, as the Projected View PM."""
        D.arrow_group(self, self.page, "SWViewPM")
        have = [o for o in self._arrow_items(v) if getattr(o, "SWArrowOf", "") == v.Name]
        if have:                 # before redo is connected: showing the arrow it has changes nothing
            self.arrow_label.setText(str(have[0].Label).replace("View Arrow ", ""))
            self.arrow.setChecked(True)

        def redo(*_):
            on, letter = self.arrow.isChecked(), self.arrow_label.text().strip()

            def fn():
                for o in self._arrow_items(v):
                    self.doc.removeObject(o.Name)
                if on and letter:
                    D.view_arrow(self.page, parent, v, letter)
            self.change(fn)
        self.arrow.toggled.connect(redo)
        self.arrow_label.editingFinished.connect(redo)

    def import_group(self, v):
        ""

        box, lay = self._group("Import options")
        self.imp = QtWidgets.QCheckBox("Import annotations", box)
        self.imp.setObjectName("SWViewPMImportAnnotations")
        self.imp_design = QtWidgets.QCheckBox("Design annotations", box)
        self.imp_design.setObjectName("SWViewPMImportDesign")
        self.imp_dimxpert = QtWidgets.QCheckBox("DimXpert annotations", box)
        self.imp_dimxpert.setObjectName("SWViewPMImportDimXpert")
        self.imp_hidden = QtWidgets.QCheckBox("Include items from hidden features", box)
        self.imp_hidden.setObjectName("SWViewPMImportHidden")
        self.imp.setChecked(bool(getattr(v, "SWImportAnnotations", False)))
        self.imp_design.setChecked(bool(getattr(v, "SWImportDesign", True)))
        self.imp_dimxpert.setChecked(bool(getattr(v, "SWImportDimXpert", True)))
        self.imp_hidden.setChecked(bool(getattr(v, "SWImportHidden", False)))
        for w in (self.imp, self.imp_design, self.imp_dimxpert, self.imp_hidden):
            lay.addWidget(w)
        for w in (self.imp_design, self.imp_dimxpert, self.imp_hidden):
            # live, never greyed: turning a kind on turns Import annotations on
            w.clicked.connect(lambda *_, w=w: w.isChecked() and not self.imp.isChecked() and self.imp.setChecked(True))
        self.imp.toggled.connect(lambda on: self.change(lambda: self._import(v, on)))
        # the kinds kept on the view; changed with Import annotations on, the view's annotations are brought in
        # again with them (pkg-drawings land95: they did nothing)
        for w, prop in ((self.imp_design, "SWImportDesign"), (self.imp_dimxpert, "SWImportDimXpert"),
                        (self.imp_hidden, "SWImportHidden")):
            w.toggled.connect(lambda on, prop=prop: self.change(lambda: self._import_kind(v, prop, on)))

    def _import_kind(self, v, prop, on):
        _setb(v, prop, on)
        if getattr(v, "SWImportAnnotations", False):
            self._import(v, True)

    def _import(self, v, on):
        _setb(v, "SWImportAnnotations", on)
        if not on or not (self.imp_design.isChecked() or self.imp_dimxpert.isChecked()):
            return
        from . import drawannot as DA
        page = next((o for o in v.InList if o.TypeId == "TechDraw::DrawPage"), None)
        if page is None:
            return
        try:
            DA.model_items(page, [v], marked=self.imp_design.isChecked(), hidden=self.imp_hidden.isChecked())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Import annotations: %s\n" % error)

    def _mirror(self):
        from . import drawviews as DV
        how = ("Vertical" if self.mirror_v.isChecked() else "Horizontal") if self.mirror.isChecked() else ""
        DV.set_mirror(self.view, how)

    def more_properties(self):
        from . import drawviewcmds
        drawviewcmds.ViewPropertiesDialog(self.view).exec_()

    # ----------------------------------------------------------------- a picked section / detail view
    def section_groups(self, v):
        ""
        from . import drawviews as DV
        box, lay = self._group("Section Line")
        flip = QtWidgets.QPushButton("Flip Direction", box)
        flip.setObjectName("SWViewPMSectionFlip")
        flip.clicked.connect(lambda: self.change(lambda: self._flip_section(v)))
        lay.addWidget(flip)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Label:", box))
        self.section_label = QtWidgets.QLineEdit(str(getattr(v, "SectionSymbol", "") or ""), box)
        self.section_label.setObjectName("SWViewPMSectionLabel")
        self.section_label.editingFinished.connect(lambda: self.change(lambda: self._relabel_section(v)))
        row.addWidget(self.section_label)
        lay.addLayout(row)
        box, lay = self._group("Section View")
        self.sec_boxes = {}
        for text, name, prop in (("Slice section", "SWViewPMSectionOnlyCut", "SWOnlyCutFaces"),
                                 ("Scale hatch pattern", "SWViewPMSectionScaleHatch", "SWScaleHatch"),
                                 ("Emphasize outline", "SWViewPMSectionEmphasize", "SWEmphasizeOutline")):
            b = QtWidgets.QCheckBox(text, box)
            b.setObjectName(name)
            b.setChecked(bool(getattr(v, prop, False)))
            b.toggled.connect(lambda *_: self.change(self._reoption_section))
            lay.addWidget(b)
            self.sec_boxes[prop] = b
        box, lay = self._group("Hatch")
        grid = QtWidgets.QGridLayout()
        self.hatch_scale = QtWidgets.QDoubleSpinBox(box)
        self.hatch_scale.setObjectName("SWViewPMHatchScale")
        self.hatch_scale.setRange(0.01, 100)
        k = DV.view_scale(v) if getattr(v, "SWScaleHatch", False) else 1.0
        self.hatch_scale.setValue(float(getattr(v, "HatchScale", 1.0)) / (k or 1.0))
        self.hatch_angle = QtWidgets.QDoubleSpinBox(box)
        self.hatch_angle.setObjectName("SWViewPMHatchAngle")
        self.hatch_angle.setRange(-360, 360)
        self.hatch_angle.setSuffix("\u00b0")
        self.hatch_angle.setValue(float(getattr(v, "HatchRotation", 0.0)))
        grid.addWidget(QtWidgets.QLabel("Hatch pattern scale:", box), 0, 0)
        grid.addWidget(self.hatch_scale, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Hatch pattern angle:", box), 1, 0)
        grid.addWidget(self.hatch_angle, 1, 1)
        self.hatch_scale.valueChanged.connect(lambda *_: self.change(self._reoption_section))
        self.hatch_angle.valueChanged.connect(lambda *_: self.change(self._reoption_section))
        lay.addLayout(grid)
        box, lay = self._group("Section Depth")
        self.depth_on = QtWidgets.QCheckBox("Section depth", box)
        self.depth_on.setObjectName("SWViewPMSectionDepthOn")
        self.depth = QtWidgets.QDoubleSpinBox(box)
        self.depth.setObjectName("SWViewPMSectionDepth")
        self.depth.setRange(0.01, 100000)
        self.depth.setSuffix("mm")
        cur = float(getattr(v, "SWSectionDepth", 0.0) or 0.0)
        self.depth.setValue(cur or 10.0)
        self.depth_on.setChecked(cur > 0)
        # live, never greyed: a depth typed in turns Section depth on
        self.depth.editingFinished.connect(lambda: self.depth_on.isChecked() or self.depth_on.setChecked(True))
        apply_depth = lambda *_: self.change(lambda: DV.set_section_depth(
            v, self.depth.value() if self.depth_on.isChecked() else 0.0))
        self.depth_on.toggled.connect(apply_depth)
        self.depth.editingFinished.connect(apply_depth)
        lay.addWidget(self.depth_on)
        lay.addWidget(self.depth)

    def _flip_section(self, s):
        want = -App.Vector(s.Direction)
        s.SectionNormal = -App.Vector(s.SectionNormal)
        if (App.Vector(s.Direction) - want).Length > 1e-9:
            s.Direction = want
        s.XDirection = -App.Vector(s.XDirection)          # seen from the other side, still upright

    def _relabel_section(self, s):
        t = self.section_label.text().strip()
        if t:
            s.SectionSymbol = t
            s.Label = "Section View %s-%s" % (t, t)

    def _reoption_section(self):
        from . import drawviews as DV
        b = self.sec_boxes
        DV.section_options(self.view, b["SWOnlyCutFaces"].isChecked(), b["SWScaleHatch"].isChecked(),
                           b["SWEmphasizeOutline"].isChecked(), self.hatch_scale.value(), self.hatch_angle.value())

    def detail_groups(self, dt):
        ""
        from . import drawviews as DV
        box, lay = self._group("Detail Circle")
        self.detail_style = QtWidgets.QComboBox(box)
        self.detail_style.setObjectName("SWViewPMDetailStyle")
        self.detail_style.addItems(DV.DETAIL_STYLES)
        self.detail_style.setCurrentText(getattr(dt, "SWDetailStyle", "") or "Per Standard")
        self.detail_style.currentTextChanged.connect(
            lambda t: self.change(lambda: DV.detail_style(self.page, dt, t)))
        lay.addWidget(self.detail_style)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Label:", box))
        self.detail_label = QtWidgets.QLineEdit(str(dt.Reference), box)
        self.detail_label.setObjectName("SWViewPMDetailLabel")
        self.detail_label.editingFinished.connect(lambda: self.change(self._relabel_detail))
        row.addWidget(self.detail_label)
        lay.addLayout(row)
        box, lay = self._group("Detail View")
        self.no_outline = QtWidgets.QCheckBox("No outline", box)
        self.no_outline.setObjectName("SWViewPMDetailNoOutline")
        self.full_outline = QtWidgets.QCheckBox("Full outline", box)
        self.full_outline.setObjectName("SWViewPMDetailFullOutline")
        self.jagged = QtWidgets.QCheckBox("Jagged outline", box)
        self.jagged.setObjectName("SWViewPMDetailJagged")
        jag = int(getattr(dt, "SWDetailJagged", 0) or 0)
        self.full_outline.setChecked(bool(getattr(dt, "ShowMatting", False)) and not jag)
        self.jagged.setChecked(bool(jag))
        self.no_outline.setChecked(bool(getattr(dt, "SWDetailNoOutline", False)))
        trio = (self.no_outline, self.full_outline, self.jagged)
        for b in trio:
            b.toggled.connect(lambda on, b=b: self._outline(b, on, trio))
            lay.addWidget(b)
        self.pin = QtWidgets.QCheckBox("Pin position", box)
        self.pin.setObjectName("SWViewPMDetailPin")
        self.pin.setChecked(bool(getattr(dt, "LockPosition", False)))
        self.pin.toggled.connect(lambda on: self.change(lambda: setattr(dt, "LockPosition", on)))
        lay.addWidget(self.pin)

    def _relabel_detail(self):
        dt = self.view
        t = self.detail_label.text().strip()
        if t:
            from . import drawviews as DV
            dt.Reference = t
            a, b = DV._ratio(float(dt.Scale))
            dt.Label = "Detail View %s (%s : %s)" % (t, a, b)

    def _outline(self, b, on, trio):
        from . import drawviews as DV
        dt = self.view
        if on:
            for o in trio:
                if o is not b:
                    o.blockSignals(True)
                    o.setChecked(False)
                    o.blockSignals(False)

        def go():
            _setb(dt, "SWDetailNoOutline", self.no_outline.isChecked())
            try:
                dt.ShowMatting = self.full_outline.isChecked()
            except Exception as _fw_err:
                _fw_log("drawselect.py:562", _fw_err)
            DV.detail_jagged(self.page, dt, 3 if self.jagged.isChecked() else 0)
        self.change(go)

    def _named(self):
        d = D._unit(self.view.Direction)
        for name, (nd, _) in D.ORIENTATIONS.items():
            if (D._unit(nd) - d).Length < 1e-6:
                return name
        return ""

    # ----------------------------------------------------------------- live changes
    def change(self, fn):
        if not self.started:
            self.doc.openTransaction("Drawing View")
            self.started = True
        try:
            fn()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Drawing View: %s\n" % error)
        self.doc.recompute()

    def orientation_changed(self, b):
        self.change(lambda: set_orientation(self.view, b.text()))

    def _style_to(self, v, style):
        D.set_display_style(v, style)
        for c in children_of(v):
            if getattr(c, "SWStyleFromParent", "1") == "1":
                self._style_to(c, style)

    def style_changed(self, style):
        if self.parent_style.isChecked():
            self.parent_style.blockSignals(True)
            self.parent_style.setChecked(False)     # a style picked here is the view's own
            self.parent_style.blockSignals(False)
        self.change(lambda: (_set(self.view, "SWStyleFromParent", "0"), self._style_to(self.view, style)))

    def parent_style_changed(self, on):
        p = parent_of(self.view)

        def go():
            _set(self.view, "SWStyleFromParent", "1" if on else "0")
            if on and p is not None:
                style = getattr(p, "SWDisplayStyle", "") or "Hidden Lines Removed"
                self.style.blockSignals(True)
                self.style.setCurrentText(style)
                self.style.blockSignals(False)
                self._style_to(self.view, style)
        self.change(go)

    def tangent_changed(self, text):
        from . import drawviewcmds
        self.change(lambda: drawviewcmds.set_tangent_edges(self.view, text.replace("Tangent Edges ", "")))

    def _show_scale(self):
        """The list on the view's scale (User Defined for one not in it) and the ratio box showing it."""
        h = scale_holder(self.view)
        text = D.scale_text(h.getScale() if hasattr(h, "getScale") else h.Scale)
        i = self.scale.findText(text)
        self.scale.blockSignals(True)
        self.scale.setCurrentIndex(i if i >= 0 else self.scale.findText("User Defined"))
        self.scale.blockSignals(False)
        self.ratio.setText(text)

    def _scale_enable(self):
        """Nothing greyed: a scale picked from the list, or a ratio typed, makes it the view's custom scale."""
        self.scale.setEnabled(True)
        self.ratio.setEnabled(True)

    def scale_mode_changed(self, on):
        if not on:
            return
        self._scale_enable()
        if self.use_custom.isChecked():
            self.scale_changed()
            return
        mode = "Parent" if self.use_parent.isChecked() else "Sheet"
        self.change(lambda: apply_scale(self.view, mode))
        self._show_scale()

    def scale_changed(self):
        self._scale_enable()
        if not self.use_custom.isChecked():
            self.use_custom.setChecked(True)        # scale_mode_changed applies the picked scale
            return
        text = self.scale.currentText()
        if text == "User Defined":
            self.ratio.selectAll()
            self.ratio.setFocus()
            return
        s = D.parse_scale(text)
        if s is None or s <= 0:
            return
        self.ratio.setText(text)
        self.change(lambda: apply_scale(self.view, "Custom", s))

    def ratio_changed(self):
        """User Defined: the ratio typed in ("1:3", "1:1.5")."""
        s = D.parse_scale(self.ratio.text())
        if s is None or s <= 0:
            self._show_scale()
            return
        h = scale_holder(self.view)
        now = h.getScale() if hasattr(h, "getScale") else h.Scale
        if self.use_custom.isChecked() and abs(float(now) - s) < 1e-9:
            return                                  # focus left the box, nothing typed
        i = self.scale.findText(D.scale_text(s))
        self.scale.blockSignals(True)
        self.scale.setCurrentIndex(i if i >= 0 else self.scale.findText("User Defined"))
        self.scale.blockSignals(False)
        if not self.use_custom.isChecked():
            for b in (self.use_parent, self.use_sheet, self.use_custom):
                b.blockSignals(True)
            self.use_custom.setChecked(True)
            for b in (self.use_parent, self.use_sheet, self.use_custom):
                b.blockSignals(False)
        self.change(lambda: apply_scale(self.view, "Custom", s))

    # ----------------------------------------------------------------- the task dialog
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _end(self, keep):
        if self.closing:
            return
        self.closing = True
        if self.started:
            if keep:
                self.doc.commitTransaction()
            else:
                self.doc.abortTransaction()
            self.started = False
        self.doc.recompute()
        if D.VIEW_PM and D.VIEW_PM[0] is self:
            D.VIEW_PM[:] = []

    def accept(self):
        self._end(True)
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._end(False)
        Gui.Control.closeDialog()
        try:
            if any(o.Name == self.view.Name for o in Gui.Selection.getSelection()):
                Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("drawselect.py:reject", _fw_err)
        return True

    def close_quietly(self):
        ""
        self._end(True)


# --------------------------------------------------------------------------- opening it
# --------------------------------------------------------------------------- Shift/Ctrl+drag a dimension to a view
_DRAG_FROM = []        # (dimension Name, X, Y) when the mouse went down


def drag_dimension_done(page, p, copy):
    """After a Shift+drag (move) or Ctrl+drag (copy) of a picked dimension that ended over another view."""
    from . import drawviews as DV, drawannot as DA
    target = DV.view_at(page, p)
    if target is None:
        return None
    start = {n: (x, y) for n, x, y in _DRAG_FROM}
    for o in Gui.Selection.getSelection():
        if o.TypeId != "TechDraw::DrawViewDimension" or not o.References2D:
            continue
        if o.References2D[0][0] is target:
            continue
        if o.Name in start:              # TechDraw dragged its text: back where it was
            o.X, o.Y = start[o.Name]
        return DA.move_dimension(o, target, at=p, copy=copy)
    return None


# --------------------------------------------------------------------------- model dimensions (Modify box)
MODIFY_ANSWER = [None]      # checks: a value the Modify box takes without showing


def model_sketch(dim):
    """The part sketch and constraint index a Model Items dimension shows, else (None, None)."""
    key = getattr(dim, "SWModelItemKey", "") or ""
    if "/" not in key or ":" not in key:
        return None, None
    vname, rest = key.split("/", 1)
    skname, ci = rest.rsplit(":", 1)
    try:
        ci = int(ci)
    except ValueError:
        return None, None
    view = dim.Document.getObject(vname)
    docs = []
    if view is not None:
        try:
            from . import drawviews as DV
            docs = [o.Document for o in DV.source_shapes(view)]
        except Exception:
            docs = []
    docs += [d for d in App.listDocuments().values() if d not in docs]
    for d in docs:
        sk = d.getObject(skname)
        if sk is not None and sk.TypeId.startswith("Sketcher::") and ci < len(sk.Constraints):
            return sk, ci
    return None, None


def model_feature(dim):
    """The part feature and property a Model Items feature dimension shows (an extrude's depth "feature:Pad.Length",
    a linear pattern's spacing "feature:LPattern.Spacing"), else (None, None) (drawings-land279)."""
    key = getattr(dim, "SWModelItemKey", "") or ""
    if not key.startswith("feature:") or "." not in key:
        return None, None
    name, prop = key[len("feature:"):].rsplit(".", 1)
    name = name.split("~")[-1]                 # "Component~Feature" in an assembly drawing
    docs = []
    try:
        from . import drawviews as DV
        views = [o for o in (dim.References2D[0][0],)] if dim.References2D else []
        for v in views:
            docs += [o.Document for o in DV.source_shapes(v)]
    except Exception as _fw_err:
        _fw_log("drawselect.py:model_feature", _fw_err)
    docs += [d for d in App.listDocuments().values() if d not in docs]
    for d in docs:
        f = d.getObject(name)
        if f is None:
            continue
        if prop == "Spacing":
            if getattr(f, "SWStyleKind", "") == "LinearPattern" and hasattr(f, "Spacing1"):
                prop = "Spacing1"
            elif getattr(f, "Mode", "") == "Spacing" and hasattr(f, "Offset"):
                prop = "Offset"
            else:
                return None, None              # an overall-length pattern: its spacing is not a value of its own
        if hasattr(getattr(f, prop, None), "Value"):
            return f, prop
    return None, None


def picked_model_dimension():
    for o in Gui.Selection.getSelection():
        if o.TypeId == "TechDraw::DrawViewDimension" and (model_sketch(o)[0] is not None or
                                                           model_feature(o)[0] is not None):
            return o
    return None


def modify_model_dimension(dim):
    ""

    sk, ci = model_sketch(dim)
    if sk is None:
        feat, prop = model_feature(dim)
        if feat is None:
            return False

        from . import featuredimshow
        sk, ci = featuredimshow._Adapter(feat, prop, "Distance"), 0
    if not sk.Constraints[ci].Driving:
        D._status("A driven dimension shows a value; it cannot be changed.")
        return False
    part = sk.Document
    part.openTransaction("Modify")
    try:
        ok = False
        try:
            from . import featuredimshow
            box = featuredimshow._box_class()(sk, ci)
            if MODIFY_ANSWER[0] is not None:
                box.set_value(MODIFY_ANSWER[0])
                box.accept()
                ok = bool(getattr(box, "success", True))
            else:
                ok = box.run()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Modify: %s\n" % error)
            try:
                from .fwsketch import modifybox
                box = modifybox.ModifyBox(sk, ci)
                ok = box.run()
            except Exception:
                ok = False
    except BaseException:
        try:
            part.abortTransaction()
        except Exception:
            pass
        raise
    part.commitTransaction()
    if ok:
        changed = getattr(sk, "feature", sk)       # the sketch, or the feature behind a feature dimension
        changed.touch()
        part.recompute()
        for o in part.Objects:
            if changed in getattr(o, "OutListRecursive", []):
                o.touch()
        part.recompute()
        for v in D.views_of(D.active_page()) if D.active_page() is not None else []:
            v.touch()
        dim.Document.recompute()
    return ok


def picked_view():
    sel = Gui.Selection.getSelection()
    if len(sel) != 1:
        return None
    o = sel[0]
    if o.TypeId == "TechDraw::DrawProjGroup":
        o = getattr(o, "Anchor", None)
    return o if is_view(o) else None


def _keep_keys(panel):
    ""

    try:
        panel.form.setProperty("swKeepKeys", True)
    except Exception as _fw_err:
        _fw_log("drawselect.py:keep_keys", _fw_err)


def open_for(view):
    """Shows the Drawing View PM of view (replacing the one of another view)."""
    if view is None:
        return None
    if D.VIEW_PM:
        if D.VIEW_PM[0].view is view and Gui.Control.activeDialog():
            return D.VIEW_PM[0]
        D.VIEW_PM[0].close_quietly()
        D.VIEW_PM[:] = []
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
    elif Gui.Control.activeDialog():
        return None             # another PropertyManager is open: picking a view belongs to it
    panel = DrawingViewPanel(view)
    _keep_keys(panel)
    _hold_sheet()                   # sheethold-1121: the sheet stays still as the PM opens
    Gui.Control.showDialog(panel)
    D.VIEW_PM[:] = [panel]
    return panel


class _HoldSheet(QtCore.QObject):
    """sheethold-1121: for a moment after a PropertyManager opens, a resize of the sheet's window (the left pane
    taking a few more pixels) puts the scroll position back, so the sheet does not jump (TechDraw re-scrolls on
    resize). A changed zoom is left alone."""

    def __init__(self, gv):
        super().__init__(gv)
        self.gv = gv
        self.h, self.v = gv.horizontalScrollBar().value(), gv.verticalScrollBar().value()
        self.tr = QtGui.QTransform(gv.transform())
        gv.installEventFilter(self)     # sheethold2-1121: for good, on the sheet window itself (before it re-scrolls)

    def eventFilter(self, obj, ev):
        if isinstance(ev, QtCore.QEvent) and ev.type() == QtCore.QEvent.Resize and obj is self.gv:
            try:
                old, new = ev.oldSize(), ev.size()
                small = old.isValid() and abs(new.width() - old.width()) <= 60 and abs(new.height() - old.height()) <= 60
            except Exception:
                small = False
            if small:
                self.h, self.v = self.gv.horizontalScrollBar().value(), self.gv.verticalScrollBar().value()
                self.tr = QtGui.QTransform(self.gv.transform())
                QtCore.QTimer.singleShot(0, self.back)
        return False

    def back(self):
        try:
            if self.gv.transform() == self.tr:
                self.gv.horizontalScrollBar().setValue(self.h)
                self.gv.verticalScrollBar().setValue(self.v)
        except RuntimeError:
            pass

    def done(self):
        try:
            self.gv.viewport().removeEventFilter(self)
            self.deleteLater()
        except RuntimeError:
            pass


def _hold_sheet():
    try:
        from . import drawextras
        gv = drawextras.page_view_widget()
        if gv is not None and not gv.property("fwSheetHold"):     # sheethold2-1121: one per sheet window
            gv.setProperty("fwSheetHold", True)
            _HoldSheet(gv)
    except Exception as _fw_err:
        _fw_log("drawselect.py:sheethold-1121", _fw_err)


def close_open():
    if D.VIEW_PM:
        panel = D.VIEW_PM[0]
        if Gui.Control.activeDialog():
            panel.accept()
        else:
            D.VIEW_PM[:] = []


ENABLED = [True]
FROM_ANYWHERE = [False]     # checks: open on any pick, wherever the pointer is


class _Watcher:
    """Opens the Drawing View PM when a view is picked on a sheet or in the tree; closes it when the pick is cleared."""

    def __init__(self):
        self.pending = False

    def _later(self):
        if not self.pending:
            self.pending = True
            QtCore.QTimer.singleShot(50, self.update)

    def addSelection(self, doc, obj, sub, pnt):
        self._later()

    def removeSelection(self, doc, obj, sub):
        self._later()

    def setSelection(self, doc):
        self._later()

    def clearSelection(self, doc):
        self._later()

    def update(self):
        self.pending = False
        if not ENABLED[0]:
            return
        try:
            sel = Gui.Selection.getSelection()
            if sel and all(o.TypeId == "TechDraw::DrawViewDimension" for o in sel):

                page = D.active_page()
                gv = D.page_view(page) if page is not None else None
                under = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
                if gv is not None and (under is gv.viewport() or FROM_ANYWHERE[0]):
                    from . import drawdimpm
                    hook_page(page)
                    drawdimpm.open_for(sel[0], sel[1:])
                return
            if len(sel) == 1 and getattr(sel[0], "SWAnnotation", "") == "Note" and \
                    "SWNoteOptions" in sel[0].PropertiesList:

                page = D.active_page()
                gv = D.page_view(page) if page is not None else None
                under = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
                if gv is not None and (under is gv.viewport() or FROM_ANYWHERE[0]) and \
                        not Gui.Control.activeDialog():
                    from . import drawannot
                    hook_page(page)
                    drawannot.edit_note(sel[0], page)
                return
            v = picked_view()
            if v is not None:
                sel = Gui.Selection.getSelectionEx()
                subs = sel[0].SubElementNames if sel else ()
                if any(n.startswith(("Edge", "Vertex")) for n in subs):
                    # an edge or a vertex picked inside a view: a pick for a tool, not the view (a face or the

                    return
                page = D.active_page()
                gv = D.page_view(page) if page is not None else None
                if gv is None:
                    return
                # a pick on the sheet opens it; a pick in the tree only highlights the view (the PM would cover
                # the tree in the same pane), a double-click there opens it
                under = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
                if under is not gv.viewport() and not FROM_ANYWHERE[0]:
                    hook_page(page)
                    hook_tree()
                    return
                open_for(v)
                hook_page(page)
            elif D.VIEW_PM and not Gui.Selection.getSelection():
                close_open()
            elif not Gui.Selection.getSelection():
                close_note_edit()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Drawing View PM: %s\n" % error)


def close_note_edit():
    ""
    try:
        from . import drawannot
    except Exception:
        return
    if not drawannot.NOTE_EDIT:
        return
    pn = drawannot.NOTE_EDIT[0]
    drawannot.NOTE_EDIT[:] = []
    if D.SHOWN and D.SHOWN[0] is pn and Gui.Control.activeDialog():
        pn.accept()


class _DoubleClick(QtCore.QObject):
    """A double-click on a view (sheet or tree) opens the Drawing View PM instead of TechDraw's own view editor."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick):
                p = _sheet_point(obj, event)
                page = D.active_page()
                if p is not None and page is not None:
                    from . import drawtableedit
                    if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                        from . import drawdimpm
                        if drawdimpm.arrow_press(page, p):          # the arrow dot of a picked dimension
                            return True
                    if event.type() == QtCore.QEvent.MouseButtonPress:
                        _DRAG_FROM[:] = [(o.Name, float(o.X), float(o.Y)) for o in page.Document.Objects
                                         if o.TypeId == "TechDraw::DrawViewDimension"]
                        drawtableedit.sheet_press(page, p, bool(event.modifiers() & QtCore.Qt.ShiftModifier))
                    elif ENABLED[0] and drawtableedit.sheet_double_click(page, p):
                        return True
        except Exception as _fw_err:
            _fw_log("drawselect.py:933", _fw_err)
        try:
            if event.type() == QtCore.QEvent.MouseButtonRelease and ENABLED[0] and \
                    event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier):
                p = _sheet_point(obj, event)
                page = D.active_page()
                if p is not None and page is not None:
                    copy = bool(event.modifiers() & QtCore.Qt.ControlModifier)
                    QtCore.QTimer.singleShot(0, lambda page=page, p=p, copy=copy: drag_dimension_done(page, p, copy))
        except Exception as _fw_err:
            _fw_log("drawselect.py:943", _fw_err)
        try:
            if event.type() == QtCore.QEvent.MouseButtonDblClick and ENABLED[0]:
                dim = picked_model_dimension()
                if dim is not None:
                    QtCore.QTimer.singleShot(0, lambda d=dim: modify_model_dimension(d))
                    return True
                v = picked_view()
                if v is not None and D.active_page() is not None:
                    QtCore.QTimer.singleShot(0, lambda v=v: open_for(v))
                    return True
        except Exception as _fw_err:
            _fw_log("drawselect.py:955", _fw_err)
        return False


def _sheet_point(viewport, event):
    """The sheet point (mm) under a mouse event on a page view's viewport, else None."""
    gv = viewport.parent()
    if not isinstance(gv, QtWidgets.QGraphicsView) or not isinstance(viewport, QtWidgets.QWidget):
        return None
    try:
        sp = gv.mapToScene(event.pos())
    except Exception:
        return None
    return sp.x() / D.REZ, -sp.y() / D.REZ


_FILTER = []
_HOOKED = set()


def _filter():
    if not _FILTER:
        _FILTER.append(_DoubleClick())
    return _FILTER[0]


def hook_page(page):
    gv = D.page_view(page)
    if gv is None or id(gv) in _HOOKED:
        return
    _HOOKED.add(id(gv))
    gv.viewport().installEventFilter(_filter())
    try:
        from . import drawselfilter          # presses off an annotation's lines go to what is under it
        drawselfilter.hook(gv)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet picks: %s\n" % error)
    try:
        from . import drawscene
        drawscene.hook(gv, page)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet look: %s\n" % error)
    try:
        from . import drawkeys
        drawkeys.hook(gv)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet keys: %s\n" % error)
    gv.destroyed.connect(lambda *a, k=id(gv): _HOOKED.discard(k))


def hook_tree():
    """FreeCAD's model tree and the add-on's FeatureManager tree (SWFeatureTree)."""
    mw = Gui.getMainWindow()
    for tw in mw.findChildren(QtWidgets.QTreeView):
        if id(tw) in _HOOKED:
            continue
        if isinstance(tw, QtWidgets.QTreeWidget) or tw.objectName() == "SWFeatureTree":
            _HOOKED.add(id(tw))
            tw.viewport().installEventFilter(_filter())
            tw.destroyed.connect(lambda *a, k=id(tw): _HOOKED.discard(k))


# --------------------------------------------------------------------------- sketch buttons on a sheet
SKETCH_ON_SHEET = {
    "FreeWorks_Line": "FreeWorks_DrawSketchLine", "FreeWorks_Centerline": "FreeWorks_DrawSketchCenterline",
    "FreeWorks_CornerRectangle": "FreeWorks_DrawSketchRectangle",
    "FreeWorks_CenterRectangle": "FreeWorks_DrawSketchRectangle",
    "FreeWorks_Circle": "FreeWorks_DrawSketchCircle", "FreeWorks_PerimeterCircle": "FreeWorks_DrawSketchCircle",
    "FreeWorks_CenterArc": "FreeWorks_DrawSketchArc", "FreeWorks_ThreePointArc": "FreeWorks_DrawSketchArc",
    "FreeWorks_TangentArc": "FreeWorks_DrawSketchTangentArc", "FreeWorks_Spline": "FreeWorks_DrawSketchSpline",

    "FreeWorks_CenterpointStraightSlot": "FreeWorks_DrawSketchCenterSlot",
    "FreeWorks_ThreePointArcSlot": "FreeWorks_DrawSketchArcSlot",
    "FreeWorks_CenterpointArcSlot": "FreeWorks_DrawSketchCenterArcSlot",
    "SWStyle_Parallelogram": "FreeWorks_DrawSketchParallelogram", "SWStyle_Conic": "FreeWorks_DrawSketchConic",
    "Sketcher_CreateArcOfEllipse": "FreeWorks_DrawSketchPartialEllipse",
    "Sketcher_CreateArcOfParabola": "FreeWorks_DrawSketchParabola",
    "SWStyle_Segment": "FreeWorks_DrawSegment", "Sketcher_Extend": "FreeWorks_DrawExtend",
    "Sketcher_Split": "FreeWorks_DrawSplitEntities", "SWStyle_JogLine": "FreeWorks_DrawJogLine",
    "SWStyle_StretchEntities": "FreeWorks_DrawStretchEntities", "SWStyle_EditPolygon": "FreeWorks_DrawEditPolygon",
    "SWStyle_DynamicMirror": "FreeWorks_DrawDynamicMirror", "SWStyle_ScanEqual": "FreeWorks_DrawScanEqual",
    "SWStyle_SectionProperties": "FreeWorks_DrawSectionProperties",
    "Sketcher_BSplineInsertKnot": "FreeWorks_DrawInsertSplinePoint",
}


def sheet_in_front():
    try:
        return D.in_drawing()
    except Exception as _fw_err:
        _fw_log("drawselect.py:1048", _fw_err)
        return False


def smart_dimension():
    ""

    try:
        from . import drawdimtools
        drawdimtools.smart_dimension()
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Smart Dimension: %s\n" % error)
    close_open()
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    for name in ("TechDraw_Dimension", "TechDraw_LengthDimension"):
        if name in Gui.listCommands():
            Gui.runCommand(name, 0)
            return True
    return False


_COMMANDS = set()


def _has_command(name):
    """name is a FreeCAD command. Gui.listCommands() builds the whole list each call, and the toolbars ask this for
    every sketch button on each refresh (bench engine drawing: 126 calls, 51 ms in one part edit), so the names seen
    are kept; commands are only ever added."""
    if name not in _COMMANDS:
        _COMMANDS.update(Gui.listCommands())
    return name in _COMMANDS


class SheetHook:
    """fwsketch.commands HOOKS entry: the part sketch buttons, pressed while a sheet is in front."""

    def claims(self, name):
        if not sheet_in_front():
            return None
        try:
            from .fwsketch import commands
            if commands.sketch_in_edit():
                return None
        except Exception as _fw_err:
            _fw_log("drawselect.py:1085", _fw_err)
        if name == "FreeWorks_SmartDimension":
            return True
        target = SKETCH_ON_SHEET.get(name)
        if target is not None:
            return _has_command(target)
        return False

    def run(self, name):
        if name == "FreeWorks_SmartDimension":
            smart_dimension()
            return
        target = SKETCH_ON_SHEET.get(name)
        if target:
            close_open()
            Gui.runCommand(target, 0)


_STARTED = []


def start():
    if _STARTED:
        return
    _STARTED.append(_Watcher())
    Gui.Selection.addObserver(_STARTED[0])
    try:
        from .fwsketch import commands
        if not any(isinstance(h, SheetHook) for h in commands.HOOKS):
            commands.HOOKS.append(SheetHook())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet sketch hook: %s\n" % error)
    QtCore.QTimer.singleShot(2000, hook_tree)
    try:
        from . import drawpalette
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        mdi.subWindowActivated.connect(
            lambda *a: QtCore.QTimer.singleShot(0, lambda: drawpalette.note_source(App.ActiveDocument)))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Palette source: %s\n" % error)


# --------------------------------------------------------------------------- View > Display on a sheet
def picked_views():
    out = []
    for o in Gui.Selection.getSelection():
        if o.TypeId == "TechDraw::DrawProjGroup":
            out += [v for v in o.Views if is_view(v)]
        elif is_view(o):
            out.append(o)
    return out


def display_style(style):
    ""

    page = D.active_page()
    if page is None:
        return []
    views = picked_views() or [v for v in D.views_of(page)]
    if not views:
        return []
    doc = page.Document
    doc.openTransaction("Display Style")
    try:
        for v in views:
            D.set_display_style(v, style)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return views


def tangent_edges(mode):
    """View > Display > Tangent Edges Visible / With Font / Removed on a drawing's picked views (else all)."""
    from . import drawviewcmds
    page = D.active_page()
    if page is None:
        return []
    views = picked_views() or [v for v in D.views_of(page)]
    doc = page.Document
    doc.openTransaction("Tangent Edges")
    try:
        for v in views:
            drawviewcmds.set_tangent_edges(v, mode)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return views
