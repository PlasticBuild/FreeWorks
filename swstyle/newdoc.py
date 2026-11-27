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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import icons, paths
from .style import T
from .widgets import ui_font

Qt = QtCore.Qt


KINDS = (
    ("Part", "Part", "PART_TAB", "PartDesign_Body", "Part",
     "A single solid part: sketches and features in one Body."),
    ("Assembly", "Assembly", "ASSEMBLY_TAB", "Geoassembly", "Assem",
     "Parts and other assemblies placed together with joints."),
    ("Drawing", "Drawing", "", "TechDraw_PageDefault", "Draw",
     "A 2D drawing sheet with views of a part or an assembly."),
)
LAST = "NewDocumentKind"
VIEW = "NewDocumentView"
LIST_VIEW = "NewDocumentListView"  # Advanced: "icons", "list" or "details"
_counts = {}


def templates_folder():
    """Where the Advanced box's template tabs come from: one folder per tab, FCStd files inside.
    The Templates tab always holds the built-in Part, Assembly and Drawing."""
    folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Templates")
    try:
        os.makedirs(os.path.join(folder, "Templates"), exist_ok=True)
        os.makedirs(os.path.join(folder, "Tutorial"), exist_ok=True)
    except OSError as _fw_err:
        _fw_log("newdoc.py:57", _fw_err)
    return folder


def template_tabs():
    """[(tab name, [(label, kind or file path)])] for the Advanced box."""
    try:
        from . import drawtemplates              # the shipped ANSI / ISO drawing templates, made once (land177)
        drawtemplates.ensure_shipped()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: drawing templates: %s\n" % error)
    folder = templates_folder()
    tabs = []
    names = []
    try:
        names = sorted(n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n)))
    except OSError as _fw_err:
        _fw_log("newdoc.py:74", _fw_err)
    if "Templates" in names:
        names.remove("Templates")
    names.insert(0, "Templates")
    for name in names:
        entries = []
        if name == "Templates":
            entries = [(k[1], k[0]) for k in KINDS]
        try:
            for f in sorted(os.listdir(os.path.join(folder, name))):
                if f.lower().endswith(".fcstd"):
                    entries.append((os.path.splitext(f)[0], os.path.join(folder, name, f)))
        except OSError as _fw_err:
            _fw_log("newdoc.py:87", _fw_err)
        tabs.append((name, entries))
    return tabs


FROM_TEMPLATE = set()       # documents New made as a copy of a template (Options > Default Templates)
STEMS = {k[0]: k[4] for k in KINDS}


def default_part_template():
    """System Options > Default Templates > Parts, when the file is there."""
    path = paths.params().GetString("PartTemplate", "")
    return path if path and os.path.isfile(path) else ""


def make_from_template(path):
    ""

    # Open a copy, never the template itself: opening the template and clearing its FileName crashed
    # FreeCAD the second time the same template was used (drawings-land112). The copy has the new
    # document's own name, so each New from one template is its own document.
    import shutil
    import tempfile
    stem = STEMS.get(_kind_of_template(path), "Part")
    name = _next_name(stem)
    folder = os.path.join(tempfile.gettempdir(), "FreeWorksNew")
    os.makedirs(folder, exist_ok=True)
    copy = os.path.join(folder, name + ".FCStd")
    n = 1
    while os.path.exists(copy) or any(d.FileName == copy for d in App.listDocuments().values()):
        n += 1
        copy = os.path.join(folder, "%s_%d.FCStd" % (name, n))
    shutil.copyfile(path, copy)
    doc = App.openDocument(copy)
    try:
        doc.FileName = ""
    except Exception as _fw_err:
        _fw_log("newdoc.py:124", _fw_err)
    doc.Label = name
    stamp_standard(doc)         # fh255: a template with no standard of its own takes the default one
    doc.recompute()
    QtCore.QTimer.singleShot(200, _trimetric)
    return doc


def stamp_standard(doc):
    ""



    try:
        from . import migrate, options
        if migrate.doc_meta(doc) in options.STANDARDS:
            return False
        meta = dict(doc.Meta)
        meta[migrate.DOC_META_NEW] = paths.params().GetString(options.DRAFTING, "ISO")
        doc.Meta = meta
        return True
    except Exception as _fw_err:
        _fw_log("newdoc.py:stamp_standard", _fw_err)
        return False


def _icon(sw_name, fc_name):
    icon = icons.family(sw_name, large=True) if sw_name else QtGui.QIcon()     # welcomefit-1120: 48-100 px tiles
    if not icon.isNull():
        return icon
    if fc_name.startswith("TechDraw"):
        try:
            import TechDrawGui  # noqa: F401  (its icons are in its own resources)
        except Exception as _fw_err:
            _fw_log("newdoc.py:139", _fw_err)
    for path in ("icons:%s.svg" % fc_name, ":/icons/%s.svg" % fc_name, ":/icons/actions/%s.svg" % fc_name):
        icon = QtGui.QIcon(path)
        if not icon.pixmap(32).isNull():
            return icon
    return QtGui.QIcon()


def _mortarboard():
    """A graduation cap for the Tutorials button (our own drawing; the icon pack's, when it has one)."""
    icon = icons.family("SW_Tutorials")
    if not icon.isNull():
        return icon
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(48, 48)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    ink = QtGui.QColor(T.hex("text")) if hasattr(T, "hex") else QtGui.QColor("#333333")
    p.setPen(Qt.NoPen)
    p.setBrush(ink)
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(24, 8), QtCore.QPointF(46, 18),
                                   QtCore.QPointF(24, 28), QtCore.QPointF(2, 18)]))
    p.drawRoundedRect(QtCore.QRectF(12, 22, 24, 12), 3, 3)
    pen = QtGui.QPen(ink, 2.5)
    p.setPen(pen)
    p.drawLine(QtCore.QPointF(40, 20), QtCore.QPointF(40, 34))
    p.end()
    return QtGui.QIcon(pix)


def available(kind):
    have = set(Gui.listCommands())
    if kind == "Assembly":
        return "Assembly_CreateAssembly" in have or _can_load("AssemblyWorkbench")
    if kind == "Drawing":
        return "TechDraw_PageDefault" in have or _can_load("TechDrawWorkbench")
    return True


def _can_load(workbench):
    try:
        return workbench in Gui.listWorkbenches()
    except Exception:
        return False


TILE_STYLE = ("QToolButton { border: 1px solid transparent; background: transparent; }"
              "QToolButton:hover { border: 1px solid rgba(128, 128, 128, 140); background: rgba(128, 128, 128, 45); }"
              "QToolButton:checked { border: 1px solid rgba(110, 110, 110, 200); background: rgba(128, 128, 128, 110); }")


class _TileName(QtWidgets.QLabel):
    """The kind's name in bold under its picture; a click on it picks the tile, a double-click is OK."""

    def __init__(self, text, tile, parent):
        super().__init__(text, parent)
        self.tile = tile
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.setEnabled(tile.isEnabled())

    def mousePressEvent(self, event):
        if self.tile.isEnabled():
            self.tile.click()

    def mouseDoubleClickEvent(self, event):
        if self.tile.isEnabled():
            self.tile.click()
            QtCore.QTimer.singleShot(0, self.window().accept)


class NewDocumentDialog(QtWidgets.QDialog):
    TILE = 96

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWNewDocument")
        self.setWindowTitle("New FreeCAD Document")
        self.setFont(ui_font())
        self.chosen = None
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(10)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.tiles = {}
        for key, label, sw, fc, _stem, _line in KINDS:
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWNewTile" + key)
            b.setText(label)
            b.setIcon(_icon(sw, fc))
            b.setIconSize(QtCore.QSize(100, 100))

            # while hovered); the name sits under the box in bold
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setFixedSize(self.TILE + 28, self.TILE + 28)
            b.setStyleSheet(TILE_STYLE)
            b.setEnabled(available(key))
            b.installEventFilter(self)
            b.setVisible(b.isEnabled())      # a kind FreeCAD cannot make is left out, not greyed
            self.group.addButton(b)
            self.tiles[key] = b

            # thin vertical lines between the columns
            if row.count():
                sep = QtWidgets.QFrame(self)
                sep.setFrameShape(QtWidgets.QFrame.VLine)
                sep.setFrameShadow(QtWidgets.QFrame.Plain)
                sep.setObjectName("SWNewTileLine")
                row.addWidget(sep)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(4)
            col.addWidget(b, 0, Qt.AlignHCenter)
            name = _TileName(label, b, self)
            name.setObjectName("SWNewTileName" + key)
            col.addSpacing(6)
            col.addWidget(name, 0, Qt.AlignHCenter)
            col.addSpacing(6)
            desc = QtWidgets.QLabel(_line, self)
            desc.setObjectName("SWNewTileText" + key)
            desc.setWordWrap(True)
            desc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
            desc.setFixedWidth(self.TILE + 100)
            desc.setEnabled(b.isEnabled())
            desc.setVisible(b.isEnabled())
            name.setVisible(b.isEnabled())
            col.addWidget(desc)
            col.addStretch(1)
            row.addLayout(col)
        self.novice = QtWidgets.QWidget(self)
        self.novice.setLayout(QtWidgets.QVBoxLayout())
        self.novice.layout().setContentsMargins(0, 0, 0, 0)

        # under the text, not at the box's foot)
        self.novice.layout().addStretch(1)
        self.novice.layout().addLayout(row)
        self.novice.layout().addStretch(1)
        self.line = QtWidgets.QLabel(self)
        self.line.setWordWrap(True)
        self.line.setVisible(False)
        self.novice.layout().addWidget(self.line)

        self.tutorials = QtWidgets.QPushButton("FreeCAD Tutorials", self.novice)
        self.tutorials.setObjectName("SWNewTutorials")
        self.tutorials.setIcon(_mortarboard())

        self.tutorials.setIconSize(QtCore.QSize(40, 40))
        self.tutorials.setMinimumHeight(56)
        self.tutorials.setMinimumWidth(300)
        big = QtGui.QFont(self.font())
        big.setPointSizeF(big.pointSizeF() * 1.5 if big.pointSizeF() > 0 else 14)
        self.tutorials.setFont(big)
        self.tutorials.setToolTip("Step-by-step lessons")
        self.tutorials.clicked.connect(self._tutorials)
        self.novice.layout().addSpacing(8)
        self.novice.layout().addWidget(self.tutorials, 0, Qt.AlignHCenter)
        lay.addWidget(self.novice)

        self.advanced = QtWidgets.QWidget(self)
        adv = QtWidgets.QHBoxLayout(self.advanced)
        adv.setContentsMargins(0, 0, 0, 0)
        self.tabs = QtWidgets.QTabWidget(self.advanced)
        self.tabs.setObjectName("SWNewTemplateTabs")
        # filedlg2-1119: the template tabs share the row (names shortened if need be) instead of Qt's scroll
        # arrows, one of them always greyed
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setElideMode(Qt.ElideRight)
        self.lists = []
        for name, entries in template_tabs():
            lst = QtWidgets.QListWidget(self.tabs)
            lst.setObjectName("SWNewTemplates_" + name)
            lst.setViewMode(QtWidgets.QListWidget.IconMode)
            lst.setIconSize(QtCore.QSize(48, 48))
            lst.setGridSize(QtCore.QSize(96, 80))
            lst.setResizeMode(QtWidgets.QListWidget.Adjust)
            for label, target in entries:
                item = QtWidgets.QListWidgetItem(label)
                item.setData(Qt.UserRole, target)
                kind = target if target in self.tiles else _kind_of_template(target)
                spec = next((k for k in KINDS if k[0] == kind), KINDS[0])
                item.setIcon(_icon(spec[2], spec[3]))
                if target in self.tiles and not available(target):
                    continue                     # left out rather than greyed
                lst.addItem(item)
            lst.currentItemChanged.connect(lambda cur, _p: self._template_picked(cur))
            lst.itemDoubleClicked.connect(lambda item: (self._template_picked(item), QtCore.QTimer.singleShot(0, self.accept)))
            if not lst.count() and self.tabs.count():
                lst.deleteLater()           # fh266: a template folder with no templates in it: no empty tab
                continue
            self.tabs.addTab(lst, name)
            self.lists.append(lst)

        views = QtWidgets.QWidget(self.tabs)
        vl = QtWidgets.QHBoxLayout(views)
        vl.setContentsMargins(0, 0, 4, 0)
        vl.setSpacing(1)
        self.view_buttons = {}
        view_group = QtWidgets.QButtonGroup(views)
        for mode, tip in (("icons", "Large Icons"), ("list", "List"), ("details", "List Details")):
            vb = QtWidgets.QToolButton(views)
            vb.setObjectName("SWNewView_" + mode)
            vb.setToolTip(tip)
            vb.setCheckable(True)
            vb.setAutoRaise(True)
            vb.setIcon(_view_icon(mode))
            vb.setIconSize(QtCore.QSize(16, 16))
            vb.clicked.connect(lambda checked=False, m=mode: self.set_list_view(m))
            view_group.addButton(vb)
            vl.addWidget(vb)
            self.view_buttons[mode] = vb
        self.tabs.setCornerWidget(views, Qt.TopRightCorner)
        adv.addWidget(self.tabs, 1)

        group = QtWidgets.QGroupBox("Preview", self.advanced)
        group.setObjectName("SWNewPreviewGroup")
        group.setFixedWidth(200)
        side = QtWidgets.QVBoxLayout(group)
        side.setContentsMargins(8, 8, 8, 8)
        self.preview = QtWidgets.QLabel(group)
        self.preview.setObjectName("SWNewPreview")
        self.preview.setFixedSize(160, 160)
        self.preview.setAlignment(Qt.AlignCenter)
        side.addWidget(self.preview, 0, Qt.AlignHCenter)
        side.addStretch(1)
        adv.addWidget(group)
        lay.addWidget(self.advanced)
        self.template = None          # a template file picked in Advanced, else None (a kind)
        bottom = QtWidgets.QHBoxLayout()
        self.switch = QtWidgets.QPushButton("Advanced", self)
        self.switch.setObjectName("SWNewSwitch")
        self.switch.clicked.connect(self.toggle_view)
        bottom.addWidget(self.switch)

        self.tutorials_small = QtWidgets.QPushButton("Tutorials", self)
        self.tutorials_small.setObjectName("SWNewTutorialsAdvanced")
        self.tutorials_small.setIcon(_mortarboard())
        self.tutorials_small.setToolTip("Step-by-step lessons")
        self.tutorials_small.clicked.connect(self._tutorials)
        self.tutorials_small.setVisible(False)
        bottom.addWidget(self.tutorials_small)
        bottom.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self._help)
        for sb in buttons.buttons():
            sb.setIcon(QtGui.QIcon())
        bottom.addWidget(buttons)
        lay.addLayout(bottom)
        self.group.buttonToggled.connect(self._toggled)
        self.set_list_view(paths.params().GetString(LIST_VIEW, "icons"))
        self._set_view(paths.params().GetString(VIEW, "novice"))
        self.setStyleSheet(
            "QToolButton[objectName^='SWNewTile'] { border: 1px solid transparent; border-radius: 2px; padding: 4px; }"
            "QToolButton[objectName^='SWNewTile']:hover { background: %s; border-color: %s; }"
            "QToolButton[objectName^='SWNewTile']:checked { background: %s; border-color: %s; }"
            % (T.hex("hover"), T.hex("hover_line"), T.hex("selection"), T.hex("accent")))
        last = paths.params().GetString(LAST, "Part")
        start = self.tiles.get(last) if last in self.tiles and self.tiles[last].isEnabled() else self.tiles["Part"]
        start.setChecked(True)
        start.setFocus()

    def set_list_view(self, mode):
        """Large Icons, List or List Details for every template tab (kept for the next time)."""
        mode = mode if mode in ("icons", "list", "details") else "icons"
        for lst in self.lists:
            if mode == "icons":
                lst.setViewMode(QtWidgets.QListView.IconMode)
                lst.setIconSize(QtCore.QSize(48, 48))
                lst.setGridSize(QtCore.QSize(96, 80))
            else:
                lst.setViewMode(QtWidgets.QListView.ListMode)
                lst.setIconSize(QtCore.QSize(16, 16))
                lst.setGridSize(QtCore.QSize())
            for i in range(lst.count()):
                item = lst.item(i)
                name = item.data(Qt.UserRole + 1) or item.text()
                item.setData(Qt.UserRole + 1, name)
                item.setText(_detail_text(name, item.data(Qt.UserRole)) if mode == "details" else name)
        for key, vb in getattr(self, "view_buttons", {}).items():
            vb.setChecked(key == mode)
        paths.params().SetString(LIST_VIEW, mode)

    def _toggled(self, button, on):
        if not on:
            return
        for key, _label, _sw, _fc, _stem, line in KINDS:
            if self.tiles[key] is button:
                self.chosen = key
                self.template = None
                self.line.setText(line)

    # --- Novice / Advanced
    def is_advanced(self):
        return self.advanced.isVisible()

    def _set_view(self, view):
        advanced = view == "advanced"
        self.novice.setVisible(not advanced)
        self.advanced.setVisible(advanced)
        self.switch.setText("Novice" if advanced else "Advanced")
        if hasattr(self, "tutorials_small"):
            self.tutorials_small.setVisible(advanced)      # startup-1120 N5b
        paths.params().SetString(VIEW, "advanced" if advanced else "novice")
        if advanced and self.lists and self.lists[0].currentItem() is None:
            for i in range(self.lists[0].count()):
                if self.lists[0].item(i).data(Qt.UserRole) == self.chosen:
                    self.lists[0].setCurrentRow(i)
                    break
        self._sw_size()

    def _sw_size(self):
        ""


        try:
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            sw, sh = screen.width(), screen.height()
        except Exception:
            sw, sh = 1920, 1040
        hint = self.sizeHint()
        self.resize(min(max(730, hint.width()), int(sw * 0.9)), min(max(520, hint.height()), int(sh * 0.9)))

    def toggle_view(self):
        self._set_view("novice" if self.is_advanced() else "advanced")

    def _template_picked(self, item):
        if item is None:
            return
        target = item.data(Qt.UserRole)
        if target in self.tiles:
            self.template = None
            self.chosen = target
            self.tiles[target].setChecked(True)
            spec = next(k for k in KINDS if k[0] == target)
            self.preview.setPixmap(_icon(spec[2], spec[3]).pixmap(QtCore.QSize(96, 96)))
            self.preview.setText("")
        else:
            self.template = target
            self.chosen = _kind_of_template(target)
            self.preview.setText("")
            png = b""
            try:
                from . import fcstdinfo
                png = fcstdinfo.thumbnail(target)
            except Exception as _fw_err:
                _fw_log("newdoc.py:370", _fw_err)
            pix = QtGui.QPixmap()
            if png and pix.loadFromData(png):
                scale = max([1.0] + [float(s.devicePixelRatio()) for s in QtGui.QGuiApplication.screens()])
                pix = pix.scaled(int(140 * scale), int(140 * scale), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pix.setDevicePixelRatio(scale)           # sharp at 175 %
                self.preview.setPixmap(pix)
            else:
                self.preview.setPixmap(QtGui.QPixmap())
                self.preview.setText("No preview")

    def _tutorials(self):
        try:
            from . import helpmenu
            self.reject()
            helpmenu.show("tutorials")
        except Exception as _fw_err:
            _fw_log("newdoc.py:384", _fw_err)

    def _help(self):
        try:
            from . import helpmenu
            from . import helpguide
            if helpguide.show_topic("new document") is None:
                helpmenu.show("home", search="new document")
        except Exception as _fw_err:
            _fw_log("newdoc.py:391", _fw_err)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.MouseButtonDblClick and obj in self.tiles.values() and obj.isEnabled():
            obj.setChecked(True)
            QtCore.QTimer.singleShot(0, self.accept)
            return True
        return False


def _detail_text(name, target):
    """List Details: the template's name, then its file, size and date (a built-in kind says so)."""
    if not target or not os.path.isfile(str(target)):
        return "%s    (built-in %s template)" % (name, name.split(" ")[0].lower())
    import time
    st = os.stat(target)
    return "%s    %s    %d KB    %s" % (name, os.path.basename(target), max(1, st.st_size // 1024),
                                     time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)))


def _view_icon(mode):
    """Our drawn 16 px pictures for the three view buttons, at the screen's scale."""
    try:
        scale = max([1.0] + [float(s.devicePixelRatio()) for s in QtGui.QGuiApplication.screens()])
    except Exception:
        scale = 1.0
    pix = QtGui.QPixmap(int(round(16 * scale)), int(round(16 * scale)))
    pix.setDevicePixelRatio(scale)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    ink = QtGui.QColor(T.text)          # startdlg-1120 Y1: the theme's text colour (the grey vanished on Dark)
    blue = QtGui.QColor(40, 110, 220)
    if mode == "icons":
        p.setPen(Qt.NoPen)
        p.setBrush(blue)
        for x, y in ((1, 1), (9, 1), (1, 9), (9, 9)):
            p.drawRect(QtCore.QRectF(x, y, 6, 6))
    else:
        for i, y in enumerate((2.5, 7.5, 12.5)):
            p.setPen(Qt.NoPen)
            p.setBrush(blue)
            p.drawRect(QtCore.QRectF(1, y - 1.5, 3, 3))
            p.setPen(QtGui.QPen(ink, 1.2))
            p.drawLine(QtCore.QPointF(6, y), QtCore.QPointF(10 if mode == "details" else 15, y))
            if mode == "details":
                p.drawLine(QtCore.QPointF(12, y), QtCore.QPointF(15, y))
    p.end()
    return QtGui.QIcon(pix)


def _next_name(stem):
    taken = {d.Label for d in App.listDocuments().values()}
    n = _counts.get(stem, 0)
    while True:
        n += 1
        if "%s%d" % (stem, n) not in taken:
            _counts[stem] = n
            return "%s%d" % (stem, n)


def assembly_template():
    """System Options > Default Templates > Assemblies, when the file is there."""
    path = paths.params().GetString("AssemblyTemplate", "")
    return path if path and os.path.isfile(path) else ""


def template_prompt():
    """Default Templates: Prompt user to select document template (else Always use these)."""
    return paths.params().GetBool("TemplatePrompt", False)


def pick_template(kind):
    """The template a command that makes a document without the New box uses (Make Assembly from
    Part): the default one, or with Prompt user to select document template the New box (Advanced)
    asks. Returns a file path, "" for a blank document, or None when the box is cancelled."""
    default = assembly_template() if kind == "Assembly" else ""
    if not template_prompt():
        return default
    box = NewDocumentDialog()
    box.setWindowTitle("New FreeCAD Document: %s" % kind)      # startup-1120 N3b
    for key, tile in box.tiles.items():
        tile.setEnabled(key == kind)
        tile.setVisible(key == kind)         # only the kind being made (no greyed tiles)
        for name in ("SWNewTileName", "SWNewTileText"):
            w = box.findChild(QtWidgets.QWidget, name + key)
            if w is not None:
                w.setVisible(key == kind)
    if kind in box.tiles:
        box.tiles[kind].setChecked(True)
    box._set_view("advanced")
    if box.exec() != QtWidgets.QDialog.Accepted:
        return None
    if box.template and _kind_of_template(box.template) == kind:
        return box.template
    return default                       # the Assembly tile: the default assembly template


UNITS_PARAMS = "User parameter:BaseApp/Preferences/Units"


def set_doc_units(doc, index):
    """Document Properties > Units of this document only. FreeCAD also wrote the new unit system into the user's
    own (Tools > Options), so every later new document came out in it; the user's own one is kept."""
    names = doc.getEnumerationsOfProperty("UnitSystem") if hasattr(doc, "UnitSystem") else []
    if not 0 <= index < len(names) or doc.UnitSystem == names[index]:
        return False
    grp = App.ParamGet(UNITS_PARAMS)
    keep = grp.GetInt("UserSchema", 0)
    doc.UnitSystem = names[index]
    if grp.GetInt("UserSchema", 0) != keep:
        grp.SetInt("UserSchema", keep)
    return True


def user_units(doc):
    ""


    try:
        i = App.ParamGet(UNITS_PARAMS).GetInt("UserSchema", 0)
        if set_doc_units(doc, i):
            App.Units.setSchema(i)          # the status bar and the new document's fields at once
    except Exception as _fw_err:
        _fw_log("newdoc.py:user units", _fw_err)
    stamp_standard(doc)     # fh255: and the default drafting standard, kept as the document's own


def _template_units(doc, path):
    ""


    try:
        import re
        import zipfile
        with zipfile.ZipFile(path) as z:
            xml = z.read("Document.xml").decode("utf-8", "replace")
        m = re.search(r'<Property name="UnitSystem"[^>]*>\s*<Integer value="(\d+)"', xml)
        if m is None or not hasattr(doc, "UnitSystem"):
            return False
        i = int(m.group(1))
        if set_doc_units(doc, i):
            if App.ActiveDocument is doc:
                App.Units.setSchema(i)      # the status bar shows it at once
        return True
    except Exception as _fw_err:
        _fw_log("newdoc.py:template units", _fw_err)
        return False


def apply_template(doc, path):
    """The template's contents and custom properties into the new document doc; returns the
    assembly it brought, if any."""
    if not path or not os.path.isfile(path):
        return None
    before = {o.Name for o in doc.Objects}
    doc.mergeProject(path)
    try:
        src = App.openDocument(path, True)
        meta = dict(doc.Meta)
        for k, v in dict(src.Meta).items():
            meta.setdefault(k, v)
        doc.Meta = meta
        App.closeDocument(src.Name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: template properties: %s\n" % error)
    _template_units(doc, path)
    asm = next((o for o in doc.Objects if o.Name not in before and o.TypeId == "Assembly::AssemblyObject"), None)
    if asm is not None and asm.Label == os.path.splitext(os.path.basename(path))[0]:
        asm.Label = doc.Label            # the template's assembly takes the new document's name
    doc.recompute()
    return asm


def up_axis_choice():
    """System Options > Default Templates > Up axis for new parts and assemblies: "Y" (default) or "Z"."""
    try:
        from . import paths
        v = paths.params().GetString("NewDocUpAxis", "Y")
    except Exception:
        v = "Y"
    return "Z" if str(v).upper().startswith("Z") else "Y"


def apply_up_axis(doc):
    ""

    if up_axis_choice() != "Z" or doc is None:
        return False
    try:
        from . import namedviews
        if namedviews.turned(doc):
            return False
        return namedviews.set_up_axis("Z", doc, None)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: up axis: %s\n" % error)
        return False


def make(kind):
    ""
    stem = STEMS[kind]
    template = default_part_template() if kind == "Part" else ""
    if template:
        # Default Templates > Parts: the new part is a copy of the template, so its Document

        # template into an empty part left them out and doubled its rows (Body001, Top Plane001)
        doc = make_from_template(template)
        FROM_TEMPLATE.add(doc.Name)
        Gui.activateWorkbench("PartDesignWorkbench")
        try:
            from . import material, multibody
            from . import surfacebodies
            surfacebodies.ensure_folder(doc)
            multibody.ensure_folder(doc)
            # right after the open the rows' Python side may not be back yet: look at their properties
            if material.row(doc) is None and not any(o.TypeId == "App::FeaturePython" and "MaterialName" in o.PropertiesList
                                                     for o in doc.Objects):
                material.make(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Solid Bodies/Material rows not made: %s\n" % error)
        body = next((o for o in doc.Objects if o.TypeId == "PartDesign::Body"), None)
        if body is None:
            body = doc.addObject("PartDesign::Body", "Body")
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        doc.recompute()
        from . import optionsextras
        optionsextras.after_new_part(doc, body)
        apply_up_axis(doc)
        QtCore.QTimer.singleShot(700, lambda name=doc.Name: frame_new_part(name))
        return doc
    name = _next_name(stem)
    doc = App.newDocument(name)
    doc.Label = name
    user_units(doc)
    if kind == "Part":
        Gui.activateWorkbench("PartDesignWorkbench")
        try:

            from . import material, multibody
            from . import surfacebodies
            surfacebodies.ensure_folder(doc)
            multibody.ensure_folder(doc)
            material.make(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Solid Bodies/Material rows not made: %s\n" % error)
        body = doc.addObject("PartDesign::Body", "Body")
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        doc.recompute()
        from . import optionsextras
        optionsextras.after_new_part(doc, body)     # Options > Sketch > Create sketch on new part
    elif kind == "Assembly":
        Gui.activateWorkbench("AssemblyWorkbench")
        asm = apply_template(doc, assembly_template())     # Options > Default Templates > Assemblies
        if asm is None:
            Gui.runCommand("Assembly_CreateAssembly", 0)
        else:
            from . import asmui
            asmui.activate(asm)
            asmui.refresh()
    elif kind == "Drawing":
        Gui.activateWorkbench("TechDrawWorkbench")
        page = new_sheet(doc)
        ask_sheet_format(page)
        try:
            from . import drawings
            start = getattr(drawings, "start_model_view", None)      # drawings-land24; honours its option
        except Exception:
            start = None
        if start is not None:
            try:
                start(page)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Model View at new drawing: %s\n" % error)
    if kind in ("Part", "Assembly"):
        apply_up_axis(doc)

    # (FreeCAD's views take no "ViewIsometric" message: that printed "Unknown view command" and
    # left the part in the Top view)
    QtCore.QTimer.singleShot(200, _trimetric)
    if kind == "Part":
        # FreeCAD opens an empty document with its camera about 4 mm tall, so the 50 mm planes and

        # the three planes whole in the middle of the view.
        QtCore.QTimer.singleShot(700, lambda name=doc.Name: frame_new_part(name))
    return doc


PART_VIEW = 2.4     # camera height per plane side: the planes fill about the middle third


def frame_new_part(name=None):
    ""

    try:
        doc = App.getDocument(name) if name else App.ActiveDocument
        gdoc = Gui.getDocument(doc.Name)
        for obj in doc.Objects:
            shape = getattr(obj, "Shape", None)
            if obj.TypeId == "PartDesign::Body" and shape is not None and not shape.isNull() \
                    and shape.Volume > 1e-9:
                return False
        side = 50.0
        try:
            from . import planes
            body = next(o for o in doc.Objects if o.TypeId == "PartDesign::Body")
            front = next(o for o in body.Origin.OriginFeatures if getattr(o, "Role", "") == "XZ_Plane")
            c = planes.corners(front)
            side = max((c[1] - c[0]).Length, (c[3] - c[0]).Length, 1.0)
        except Exception as _fw_err:
            _fw_log("newdoc.py:603", _fw_err)
        cam = gdoc.ActiveView.getCameraNode()
        if not hasattr(cam, "height"):
            return False
        height = side * PART_VIEW
        # keep the viewing direction, move the camera so it looks at the origin from the same distance
        from pivy import coin
        rot = cam.orientation.getValue()
        look = rot.multVec(coin.SbVec3f(0, 0, -1))
        dist = float(cam.focalDistance.getValue()) or height * 2
        cam.position.setValue(coin.SbVec3f(0, 0, 0) - look * dist)
        cam.height.setValue(height)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: new part view not framed: %s\n" % error)
        return False


def _trimetric():
    for name in ("SWStyle_StandardTrimetric", "Std_ViewTrimetric"):
        try:
            if Gui.Command.get(name) is not None:
                Gui.runCommand(name, 0)
                return
        except Exception:
            continue



SHEET_FORMAT = ("ASME", "ANSIA_Landscape.svg")


SHEET_FORMAT_METRIC = ("ISO", "A3_Landscape_ISO5457_minimal.svg")


def _sheet_format():
    ""


    try:
        from . import options
        if options._read_standard() != "ANSI":
            return SHEET_FORMAT_METRIC
    except Exception as _fw_err:
        _fw_log("newdoc.py:647", _fw_err)
    return SHEET_FORMAT


def sheet_template():
    for root in (App.getResourceDir(), os.path.join(App.getResourceDir(), "share")):
        path = os.path.join(root, "Mod", "TechDraw", "Templates", *_sheet_format())
        if os.path.isfile(path):
            try:
                from . import drawsheet
                return drawsheet.own_format(path) or path
            except Exception as _fw_err:
                _fw_log("newdoc.py:660", _fw_err)
                return path
    try:
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files").GetString("TemplateFile", "") \
            or None
    except Exception as _fw_err:
        _fw_log("newdoc.py:666", _fw_err)
        return None


ASK_SHEET_FORMAT = None


def ask_sheet_format(page):
    ""
    want = ASK_SHEET_FORMAT
    if want is None:
        want = not os.environ.get("SWCHECK_OUT")
    if not want:
        return None
    try:
        from . import drawsheet
    except ImportError:
        return None
    try:
        return drawsheet.ask_sheet_format(page)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet format box: %s\n" % error)
        return None


def new_sheet(doc, show=True):
    ""
    if not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
        try:
            from . import drawtree
            drawtree.ensure_folder(doc)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Annotations folder: %s\n" % error)
    page = doc.addObject("TechDraw::DrawPage", "Sheet1")
    page.Label = "Sheet1"
    path = sheet_template()
    if path:
        tpl = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
        tpl.Template = path
        page.Template = tpl
    doc.recompute()
    if show:
        show_sheet(page)
    return page


def show_sheet(page):
    try:
        page.ViewObject.doubleClicked()
    except Exception as _fw_err:
        _fw_log("newdoc.py:713", _fw_err)


def source_document():
    """The part or assembly the Make ... from Part/Assembly commands start from: the active one."""
    doc = App.ActiveDocument
    if doc is None:
        return None
    try:
        from . import asmcore
        if asmcore.part_object(doc) is not None:
            return doc
    except Exception as _fw_err:
        _fw_log("newdoc.py:726", _fw_err)
    for obj in doc.Objects:
        if obj.TypeId in ("PartDesign::Body", "Assembly::AssemblyObject") or obj.isDerivedFrom("Part::Feature"):
            return doc
    return None


def _source_shape(doc):
    """What the drawing views show: the assembly, else every visible body (or the tip solid)."""
    try:
        from . import drawings           # the same answer for every drawing view (drawings-land01)
        return drawings.model_shapes(doc)
    except ImportError:
        pass
    tops = [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]
    if tops:
        return tops[:1]
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if bodies:
        shown = [b for b in bodies if getattr(b, "Visibility", True)]
        return shown or bodies
    # a view of this part in another file links to it: that InList is no reason to skip the shape
    return [o for o in doc.Objects if o.isDerivedFrom("Part::Feature") and o.Visibility
            and not any(i.Document is doc for i in o.InList)][:20]


def _saved(source, what):
    ""

    if source.FileName:
        return True
    if what == "a drawing":
        try:
            from . import drawings
            return drawings.save_source_first(source)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: save before the drawing: %s\n" % error)
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "FreeCAD",
                                "%s must be saved before you can make %s from it.\n\nSave it now?"
                                % (source.Label, what), QtWidgets.QMessageBox.NoButton, Gui.getMainWindow())
    save = box.addButton("Save", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
    box.setObjectName("FW_SaveSource")
    box.exec()
    if box.clickedButton() is not save:
        return False
    try:
        from . import drawings
        return drawings.save_model(source)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s not saved: %s\n" % (source.Label, error))
    return bool(source.FileName)


def _save_drawing(doc, source, path=None):
    ""


    if path is None:
        start = os.path.join(os.path.dirname(source.FileName), source.Label + " Drawing.FCStd")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Drawing As", start,
                                                        "FreeCAD drawing (*.FCStd)")
        if not path:
            return False
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
    doc.saveAs(path)
    return True


def _serial_projections():
    """TechDraw works out each view's lines on Qt's shared thread pool, all three views at once,
    and OpenCASCADE's hidden-line code can crash when two of them read the same part together
    (bench: a crash in HLRBRep_HLRToShape in about one run in five). The pool runs one job at a
    time until the views are done, then gets its own size back."""
    pool = QtCore.QThreadPool.globalInstance()
    if getattr(_serial_projections, "size", None) is not None:
        return
    _serial_projections.size = pool.maxThreadCount()
    pool.setMaxThreadCount(1)
    timer = QtCore.QTimer()
    _serial_projections.timer = timer
    started = [0]

    def check():
        started[0] += 1
        if pool.activeThreadCount() == 0 and started[0] > 4 or started[0] > 600:
            timer.stop()
            pool.setMaxThreadCount(_serial_projections.size)
            _serial_projections.size = None
    timer.timeout.connect(check)
    timer.start(100)


def make_drawing_from(source=None, path=None):
    ""

    source = source or source_document()
    if source is None:
        return None
    if not _saved(source, "a drawing"):
        return None
    try:
        from . import drawings
        make = getattr(drawings, "make_drawing", None)
    except Exception:
        make = None
    if make is not None:

        # Palette open on the part (no automatic Front/Top/Right: ChatGPT D05/D07)
        try:
            return make(source, path)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Make Drawing: %s; using the three-view fallback\n" % error)
    shapes = _source_shape(source)
    stem = {k[0]: k[4] for k in KINDS}["Drawing"]
    name = _next_name(stem)
    doc = App.newDocument(name)
    doc.Label = name
    user_units(doc)
    if not _save_drawing(doc, source, path):
        App.closeDocument(doc.Name)
        return None
    try:
        Gui.activateWorkbench("TechDrawWorkbench")
    except Exception as _fw_err:
        _fw_log("newdoc.py:851", _fw_err)
    page = new_sheet(doc, show=False)
    ask_sheet_format(page)
    if shapes:
        _serial_projections()
        group = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
        page.addView(group)
        group.XSource = shapes
        group.ProjectionType = "Third angle"
        group.ScaleType = "Automatic"
        for view in ("Front", "Top", "Right"):
            group.addProjection(view)
        # the three views in the middle of the sheet's drawing area, clear of the title block
        try:
            width, height = float(page.Template.Width), float(page.Template.Height)
        except Exception:
            width, height = 279.4, 215.9
        group.X, group.Y = width * 0.42, height * 0.58
        doc.recompute()
    show_sheet(page)

    QtCore.QTimer.singleShot(300, lambda: Gui.SendMsgToActiveView("ViewFit"))
    return doc


def make_assembly_from(source=None, path=None):
    ""

    source = source or source_document()
    if source is None:
        return None
    if not _saved(source, "an assembly"):
        return None
    from . import asmpm, asmui
    template = pick_template("Assembly")
    if template is None:
        return None
    stem = {k[0]: k[4] for k in KINDS}["Assembly"]
    name = _next_name(stem)
    doc = App.newDocument(name)
    doc.Label = name
    user_units(doc)

    # untitled Assembly1 at once and asks where it goes at the first Save: a holding file until then
    # (asmpm.hold, as a new assembly from File > New; its first Save relinks the components)
    if path:
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
        doc.saveAs(path)
    else:
        asmpm.hold(doc)
        doc.Label = name
    start = paths.params().GetBool(asmpm.START_PARAM, True)
    paths.params().SetBool(asmpm.START_PARAM, False)
    try:
        asm = apply_template(doc, template)
        if asm is None:
            asmui.new_assembly(doc)
        else:
            Gui.activateWorkbench("AssemblyWorkbench")
            asmui.activate(asm)
            asmui.refresh()
            doc.save()
            if doc.Name in asmpm.HELD:          # still only in its holding file: the title keeps its *
                from . import drawings
                drawings._modified(doc)
    finally:
        paths.params().SetBool(asmpm.START_PARAM, start)
    panel = asmui.start_insert(begin=True)
    if panel is not None:
        for row in range(panel.list.count()):
            if panel.list.item(row).data(Qt.UserRole) == source.Name:
                panel.list.setCurrentRow(row)
                break
    return doc


def ask():
    """Shows the box; makes the document picked. Returns the kind made, or None."""
    box = NewDocumentDialog()
    if box.exec() != QtWidgets.QDialog.Accepted or box.chosen is None:
        return None
    paths.params().SetString(LAST, box.chosen)
    try:
        if box.template:
            make_from_template(box.template)
        else:
            make(box.chosen)
    except Exception as error:
        App.Console.PrintError("FreeCAD: new %s not made: %s\n" % (box.chosen, error))
        return None
    return box.chosen


def _kind_of_template(path):
    try:
        from . import fcstdinfo
        k = fcstdinfo.kind(path)
        return {"part": "Part", "assembly": "Assembly", "drawing": "Drawing"}.get(k, "Part")
    except Exception:
        return "Part"


class NewDocumentCommand:
    def GetResources(self):
        return {"MenuText": "New...", "ToolTip": "Starts a new part, assembly or drawing (Ctrl+N)",
                "Pixmap": "document-new", "CmdType": "ForEdit"}

    def Activated(self):
        QtCore.QTimer.singleShot(0, ask)

    def IsActive(self):
        return True


class MakeDrawingCommand:
    def GetResources(self):
        # No TechDrawGui import here: GetResources runs at start-up and loading TechDraw's GUI
        # there cost ~0.4 s before the window. FreeCAD finds the icon once TechDraw is loaded.
        return {"MenuText": "Make Drawing from Part/Assembly", "Pixmap": "actions/TechDraw_PageDefault",
                "ToolTip": "Makes a drawing of the active part or assembly with its standard three views."}

    def Activated(self):
        QtCore.QTimer.singleShot(0, make_drawing_from)

    def IsActive(self):
        return source_document() is not None


class MakeAssemblyCommand:
    def GetResources(self):
        return {"MenuText": "Make Assembly from Part/Assembly", "Pixmap": "Geoassembly",
                "ToolTip": "Makes a new assembly and starts Begin Assembly with the active part picked."}

    def Activated(self):
        QtCore.QTimer.singleShot(0, make_assembly_from)

    def IsActive(self):
        return source_document() is not None


def register():
    Gui.addCommand("SWStyle_NewDocument", NewDocumentCommand())
    Gui.addCommand("SWStyle_MakeDrawingFromPart", MakeDrawingCommand())
    Gui.addCommand("SWStyle_MakeAssemblyFromPart", MakeAssemblyCommand())
