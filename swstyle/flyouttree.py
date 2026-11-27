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

from . import icons, style
from .widgets import alive

Qt = QtCore.Qt

MARGIN = 8           # from the 3D view's top left corner
MIN_WIDTH = 200
# ${ink} and ${ink_hover} follow the 3D view's brightness, not the panes: the tree sits over the view
TREE_QSS = """
QTreeView { background: transparent; border: none; color: ${ink}; show-decoration-selected: 0; }
QTreeView::item { padding: 1px 0px; }
QTreeView::item:hover { background: ${ink_hover}; }
QTreeView::item:selected { background: rgba(47, 128, 237, 70); color: ${ink}; }
"""
OPAQUE_QSS = "QTreeView { background: ${pane}; color: ${text}; }"



def _fw_unsplit(objs):
    """objs with a drawing view's model parts read back as their model (drawviews.unsplit; Drawings land151)."""
    try:
        from . import drawviews as DV
        return DV.unsplit(list(objs or []))
    except Exception:
        return list(objs or [])

def sheet_ink():
    """flyoutink-1121: over a drawing sheet the flyout sits on TechDraw's background (Options > Colors, light by
    default), not on the 3D view: its ink follows that background."""
    try:
        value = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors").GetUnsigned("Background", 0xC3CBD6FF)
        dark_bg = style._is_dark(value)
    except Exception:
        dark_bg = False
    return {"ink": "#e6e6e6" if dark_bg else "#191919",
            "ink_hover": "rgba(255, 255, 255, 45)" if dark_bg else "rgba(255, 255, 255, 110)"}


def tree_qss(sheet=False):
    """Options > FeatureManager > Use transparent flyout FeatureManager tree: off gives the tree a
    solid pane behind it."""
    qss = TREE_QSS
    try:
        from . import optionspages
        if not optionspages.stored("FeatureManager", "Use transparent flyout FeatureManager tree in parts/assemblies",
                                   True):
            qss += OPAQUE_QSS
    except Exception as _fw_err:
        _fw_log("flyouttree.py:70", _fw_err)
    try:
        from . import optionspages      # optioncolors-1119: Options > Colors > Flyout FeatureManager Design Tree Text
        ink = optionspages.kept_hex("Flyout FeatureManager Design Tree Text")
        if ink:
            qss += "QTreeView { color: %s; } QTreeView::item:selected { color: %s; }" % (ink, ink)
    except Exception as _fw_err:
        _fw_log("flyouttree.py:tree-text", _fw_err)
    return style.fill(qss, **(sheet_ink() if sheet else {}))


HEADER_QSS = """
QToolButton { border: none; background: transparent; color: ${ink}; padding: 1px 2px; }
QToolButton:hover { background: ${ink_hover}; }
"""


def _strip():
    """The CommandManager tab row's reach over the 3D view's top (tabstrip.py), 0 when not there."""
    try:
        from . import tabstrip
        return tabstrip.top()
    except Exception:
        return 0


class FlyoutTree(QtWidgets.QWidget):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.setObjectName("SWFlyoutTree")
        self.shell = shell
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.arrow = QtWidgets.QToolButton(self)
        self.arrow.setObjectName("SWFlyoutArrow")
        self.arrow.setArrowType(Qt.RightArrow)
        self.arrow.setFixedSize(16, 20)
        self.header = QtWidgets.QToolButton(self)
        self.header.setObjectName("SWFlyoutHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setIconSize(QtCore.QSize(16, 16))
        for button in (self.arrow, self.header):
            button.setAutoRaise(True)
            button.setStyleSheet(style.fill(HEADER_QSS))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(self.toggle)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.slot = QtWidgets.QVBoxLayout()
        self.slot.setContentsMargins(14, 0, 0, 0)
        layout.addLayout(self.slot, 1)
        self.borrowed = None         # FreeCAD's tree and where it came from, while it is here
        self.expanded = False
        self.page = None             # the pane's Model page, watched for Show
        self._icon_kind = None       # "model" or "drawing": which icon the header shows
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.hide()

    def retheme(self):
        """A theme or viewport change: the header and the borrowed tree take the new ink."""
        sheet = self._icon_kind == "drawing"         # flyoutink-1121: over a sheet, the sheet's ink
        for button in (self.arrow, self.header):
            if alive(button):
                button.setStyleSheet(style.fill(HEADER_QSS, **(sheet_ink() if sheet else {})))
        tree = (self.borrowed or {}).get("tree")
        if tree is not None and alive(tree):
            tree.setStyleSheet(tree_qss(sheet=bool((self.borrowed or {}).get("own"))))

    # ---------------------------------------------------------------- state
    def host(self):
        """The 3D view, or the drawing sheet's window, the flyout sits over."""
        overlay = getattr(self.shell, "overlay", None)
        if overlay is None:
            return None
        for host in (getattr(overlay, "host", None), getattr(overlay, "sheet", None)):
            if host is not None and alive(host) and host.isVisible():
                return host
        return None

    def wanted(self):
        ""
        if not self.shell.enabled or Gui.ActiveDocument is None or self.host() is None:
            return False
        pane = getattr(self.shell, "left_pane", None)
        if pane is None or not alive(pane) or pane.current_name() != "Tasks":
            return False
        page = pane.pages.get("Model")
        return page is not None and alive(page) and not page.isVisible()

    def refresh(self):
        if not self.wanted():
            self.collapse()
            if not self.isHidden():
                self.hide()
            return
        self._watch_page()
        record = self.borrowed
        doc = App.ActiveDocument
        if record is not None and record.get("own"):
            if doc is None or record["doc"] != doc.Name or not alive(record["tree"]):
                self.collapse()      # another document came to the front
            elif drawing_rows(doc) != record["rows"]:
                self._fill_sheet_tree(record["tree"], doc)   # a view was added, renamed or deleted
        elif record is not None and record["root"] and alive(record["tree"]) and not record["tree"].rootIndex().isValid():
            self.collapse()          # its document went away
        if self.expanded and record is not None and not record.get("own"):
            self._part_root()       # the overlay's model was rebuilt: its root is reset
        text = doc.Label if doc is not None else ""
        if self.header.text() != text:
            self.header.setText(text)
            self.header.setToolTip("Show the feature tree" if not self.expanded else "Hide the feature tree")
        kind = "drawing" if is_drawing(doc) else "model"
        if self.header.icon().isNull() or self._icon_kind != kind:
            self.header.setIcon(self._document_icon(kind))
            changed = self._icon_kind != kind
            self._icon_kind = kind
            if changed:
                self.retheme()      # flyoutink-1121: a drawing's sheet and a part's view take different ink
        self.place()
        if self.isHidden():
            self.show()
        self.raise_()

    def _document_icon(self, kind="model"):
        icon = icons.family("PART") if kind == "model" else QtGui.QIcon()
        if not icon.isNull():
            return icon
        if kind == "drawing":
            icon = _object_icon(_pages(App.ActiveDocument)[:1])
            if not icon.isNull():
                return icon
        tree = self._home_tree()
        if tree is not None:
            icon = tree.model().index(0, 0).data(Qt.DecorationRole)
            if isinstance(icon, QtGui.QIcon):
                return icon
        return QtGui.QIcon()

    def _watch_page(self):
        pane = self.shell.left_pane
        page = pane.pages.get("Model") if pane is not None and alive(pane) else None
        if page is self.page:
            return
        if self.page is not None and alive(self.page):
            self.page.removeEventFilter(self)
        self.page = page
        if page is not None:
            page.installEventFilter(self)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        # The Model tab coming back takes the tree home at once, before it is painted empty
        if obj is self.page and event.type() == QtCore.QEvent.Show:
            self.collapse()
            self.hide()
        return False

    # ---------------------------------------------------------------- the tree
    def _home_tree(self):
        pane = getattr(self.shell, "left_pane", None)
        return pane.tree_widget() if pane is not None and alive(pane) else None

    def toggle(self):
        if self.expanded:
            self.collapse()
        else:
            self.expand()
        self.refresh()

    def expand(self):
        if self.expanded or not self.wanted():
            return
        if is_drawing(App.ActiveDocument):
            self._expand_sheet_tree(App.ActiveDocument)
            return
        tree = self._home_tree()
        panel = tree.parentWidget() if tree is not None else None
        layout = panel.layout() if panel is not None else None
        index = layout.indexOf(tree) if layout is not None else -1
        if index < 0:
            return
        self.borrowed = {
            "tree": tree, "panel": panel, "index": index, "hidden": tree.isHidden(),
            "qss": tree.styleSheet(), "fill": tree.viewport().autoFillBackground(),
        }
        layout.removeWidget(tree)
        tree.setParent(self)
        tree.setStyleSheet(tree_qss())
        tree.viewport().setAutoFillBackground(False)
        self.slot.addWidget(tree, 1)
        tree.show()

        root = self._document_index(tree)
        if root is not None:
            tree.setRootIndex(root)
        self.borrowed["root"] = root is not None
        self.borrowed["opened"] = self._open_bodies(tree, root)
        tree.itemExpanded.connect(self._tree_changed)
        tree.itemCollapsed.connect(self._tree_changed)
        self.expanded = True
        self.arrow.setArrowType(Qt.DownArrow)
        self.header.setToolTip("Hide the feature tree")
        self._part_root()
        self.place()

    # pkg428: the FeatureManager layout (fmtree's SWFeatureTree) is laid over the borrowed tree. Its

    # and it has more rows than FreeCAD's tree (History, Sensors, Annotations, the planes)
    def _overlay(self):
        tree = (self.borrowed or {}).get("tree")
        if tree is None or not alive(tree):
            return None
        for w in self.findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
            if alive(w) and getattr(w, "tree", None) is tree:
                return w
        return None

    def _part_root(self):
        """The overlay starts under the part's row while the flyout is open."""
        view = self._overlay()
        if view is None:
            return
        try:
            fm = view.fm
            if fm.part is None:
                return
            part = fm.index_of(fm.part)
            if part.isValid() and view.rootIndex() != part:
                view.setRootIndex(part)
                self.borrowed["overlay"] = view
        except Exception as _fw_err:
            _fw_log("flyouttree.py:part-root", _fw_err)

    def collapse(self):
        """Gives FreeCAD's tree back to its place in the pane."""
        record, self.borrowed = self.borrowed, None
        view = (record or {}).get("overlay")
        if view is not None and alive(view):
            try:
                view.setRootIndex(QtCore.QModelIndex())
            except Exception as _fw_err:
                _fw_log("flyouttree.py:part-root-back", _fw_err)
        if self.expanded:
            self.expanded = False
            self.arrow.setArrowType(Qt.RightArrow)
            self.header.setToolTip("Show the feature tree")
        if record is None:
            return
        if record.get("own"):
            tree = record["tree"]
            if alive(tree):
                self.slot.removeWidget(tree)
                tree.hide()
                tree.deleteLater()
            return
        tree, panel = record["tree"], record["panel"]
        if not alive(tree):
            return
        for signal in (tree.itemExpanded, tree.itemCollapsed):
            try:
                signal.disconnect(self._tree_changed)
            except Exception as _fw_err:
                _fw_log("flyouttree.py:295", _fw_err)
        self.slot.removeWidget(tree)
        tree.setRootIndex(QtCore.QModelIndex())
        for index in record.get("opened", []):
            if index.isValid():
                tree.collapse(QtCore.QModelIndex(index))
        tree.setStyleSheet(record["qss"])
        tree.viewport().setAutoFillBackground(record["fill"])
        if alive(panel) and panel.layout() is not None:
            tree.setParent(panel)
            panel.layout().insertWidget(record["index"], tree)
            tree.setHidden(record["hidden"])
        else:
            # its panel is gone: keep the tree alive under the main window rather than lose it
            tree.setParent(self.shell.window)
            tree.hide()
            App.Console.PrintWarning("FreeCAD: the feature tree's panel is gone\n")

    def _tree_changed(self, *args):
        self.place()

    def _document_index(self, tree):
        """The active document's row in FreeCAD's tree (it shows the document's label)."""
        doc = App.ActiveDocument
        model = tree.model()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if doc is not None and index.data(Qt.DisplayRole) == doc.Label:
                return index
        return None

    def _open_bodies(self, tree, root):
        ""

        doc = App.ActiveDocument
        if root is None or doc is None:
            return []
        bodies = {o.Label for o in doc.Objects if o.TypeId == "PartDesign::Body"}
        model = tree.model()
        opened = []
        for row in range(model.rowCount(root)):
            child = model.index(row, 0, root)
            if child.data(Qt.DisplayRole) in bodies and not tree.isExpanded(child):
                tree.expand(child)
                opened.append(QtCore.QPersistentModelIndex(child))
        return opened

    # ---------------------------------------------------------------- the drawing's tree
    def _expand_sheet_tree(self, doc):
        tree = QtWidgets.QTreeWidget(self)
        tree.setObjectName("SWFlyoutSheetTree")
        tree.setHeaderHidden(True)
        tree.setColumnCount(1)
        tree.setIconSize(QtCore.QSize(16, 16))
        tree.setStyleSheet(tree_qss(sheet=True))      # flyoutink-1121
        tree.viewport().setAutoFillBackground(False)
        tree.setFrameShape(QtWidgets.QFrame.NoFrame)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        tree.itemClicked.connect(self._sheet_item_clicked)
        tree.itemExpanded.connect(self._tree_changed)
        tree.itemCollapsed.connect(self._tree_changed)
        self.slot.addWidget(tree, 1)
        self.borrowed = {"tree": tree, "own": True, "doc": doc.Name, "rows": None, "root": False}
        self._fill_sheet_tree(tree, doc)
        tree.show()
        self.expanded = True
        self.arrow.setArrowType(Qt.DownArrow)
        self.header.setToolTip("Hide the feature tree")
        self.place()

    def _fill_sheet_tree(self, tree, doc):
        ""
        record = self.borrowed
        closed = set()                      # what the user folded keeps folded on a refill
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            if not top.isExpanded():
                closed.add(top.data(0, Qt.UserRole))
            for j in range(top.childCount()):
                if not top.child(j).isExpanded():
                    closed.add(top.child(j).data(0, Qt.UserRole))
        tree.clear()
        for page in _pages(doc):
            sheet = self._item(tree, page)
            for view in _views(page):
                item = self._item(sheet, view)
                for model in _models(view):
                    self._item(item, model)
                item.setExpanded(_key(view) not in closed)
            sheet.setExpanded(_key(page) not in closed)
        if record is not None:
            record["rows"] = drawing_rows(doc)
        self.place()

    def _item(self, parent, obj):
        item = QtWidgets.QTreeWidgetItem(parent, [obj.Label])
        item.setData(0, Qt.UserRole, _key(obj))
        icon = _object_icon([obj])
        if not icon.isNull():
            item.setIcon(0, icon)
        return item

    def _sheet_item_clicked(self, item, column=0):
        """A pick in the flyout selects that sheet, view or model, as a pick in the tree does."""
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        docname, name = key.split("#", 1)
        try:
            doc = App.getDocument(docname)
            obj = doc.getObject(name) if doc is not None else None
        except Exception:
            obj = None
        if obj is None:
            return
        try:
            mods = QtWidgets.QApplication.keyboardModifiers()
            if not mods & (Qt.ControlModifier | Qt.ShiftModifier):
                Gui.Selection.clearSelection()
            if Gui.Selection.isSelected(obj) and mods & Qt.ControlModifier:
                Gui.Selection.removeSelection(obj)
            else:
                Gui.Selection.addSelection(docname, name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: flyout pick: %s\n" % error)

    # ---------------------------------------------------------------- placing
    def _rows(self, tree):
        view = self._overlay()
        if view is not None and view.isVisible():
            tree = view         # pkg428: the rows shown are the overlay's
        rows, index = 0, tree.model().index(0, 0, tree.rootIndex())
        while index.isValid() and rows < 500:
            rows += 1
            index = tree.indexBelow(index)
        return rows

    def place(self):
        host = self.host()
        if host is None:
            return
        mw = self.shell.window
        top_left = host.mapTo(mw, QtCore.QPoint(MARGIN, MARGIN + _strip()))
        header_h = max(self.header.sizeHint().height(), self.arrow.height())
        width = self.arrow.width() + self.header.sizeHint().width() + 4
        height = header_h
        tree = self.borrowed["tree"] if self.borrowed else None
        if tree is not None and alive(tree):
            view = self._overlay()
            shown = view if view is not None and view.isVisible() else tree
            row_h = max(shown.sizeHintForRow(0), shown.fontMetrics().height() + 4)
            rows = self._rows(tree)
            # tree width: the widest item, its indentation included, and room for the scroll bar
            width = max(width, MIN_WIDTH, tree.sizeHintForColumn(0) + 14 + 24)
            height = header_h + 2 + rows * row_h + 6
        width = min(width, max(MIN_WIDTH, int(host.width() * 0.5)))
        height = min(height, max(header_h, host.height() - 2 * MARGIN - 40))
        geometry = QtCore.QRect(top_left, QtCore.QSize(width, height))
        if self.geometry() != geometry:
            self.setGeometry(geometry)

    def remove(self):
        self.timer.stop()
        self.collapse()
        if self.page is not None and alive(self.page):
            self.page.removeEventFilter(self)
        self.page = None
        self.hide()
        self.setParent(None)
        self.deleteLater()


# ---------------------------------------------------------------- drawing documents
def is_drawing(doc):
    ""
    return bool(doc is not None and _pages(doc))


def _pages(doc):
    if doc is None:
        return []
    try:
        return [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")]
    except Exception:
        return []


def _views(page):
    ""

    out = []
    for view in getattr(page, "Views", []) or []:
        try:
            if view.isDerivedFrom("TechDraw::DrawProjGroup"):
                out.extend(v for v in (view.Views or []) if v.isDerivedFrom("TechDraw::DrawViewPart"))
            elif view.isDerivedFrom("TechDraw::DrawViewPart"):
                out.append(view)
        except Exception:
            continue
    return out


def _models(view):
    """The part or assembly a view shows (its sources, from this document or another)."""
    out = []
    for prop in ("Source", "XSource"):
        try:
            for obj in _fw_unsplit(getattr(view, prop, []) or []):
                if obj is not None and obj not in out:
                    out.append(obj)
        except Exception:
            continue
    return out


def _key(obj):
    return "%s#%s" % (obj.Document.Name, obj.Name)


def drawing_rows(doc):
    """What the flyout lists for a drawing, to see when it must be filled again."""
    rows = []
    for page in _pages(doc):
        rows.append((_key(page), page.Label))
        for view in _views(page):
            rows.append((_key(view), view.Label, tuple((_key(m), m.Label) for m in _models(view))))
    return tuple(rows)


def _object_icon(objs):
    for obj in objs:
        try:
            icon = obj.ViewObject.Icon if obj.ViewObject is not None else None
            if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                return icon
        except Exception:
            continue
    return QtGui.QIcon()
