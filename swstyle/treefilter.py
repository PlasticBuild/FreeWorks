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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

from . import paths

PARAMS = paths.PARAM_PATH + "/TreeFilter"
PROPERTY = "FwTags"
COMMAND = "SWStyle_Tags"
# (key, menu text, on by default)
MODES = (("Features", "Filter Features", True), ("Tags", "Filter Tags", True),
         ("Descriptions", "Filter Descriptions", False), ("Comments", "Filter Comments", False))
HIERARCHY = ("Hierarchy", "Show Hierarchy Only", True)


def params():
    return App.ParamGet(PARAMS)


def mode(key):
    default = next((d for k, _t, d in MODES + (HIERARCHY,) if k == key), False)
    return params().GetBool(key, default)


def set_mode(key, on):
    params().SetBool(key, bool(on))


# ------------------------------------------------------------------ tags
def tags(obj):
    try:
        return [t for t in (getattr(obj, PROPERTY, None) or []) if t]
    except Exception:
        return []


def set_tags(obj, words):
    words = sorted(set(w.strip() for w in words if w and w.strip()), key=str.lower)
    if PROPERTY not in obj.PropertiesList:
        if not words:
            return
        obj.addProperty("App::PropertyStringList", PROPERTY, "Tags", "Tags of this item (FeatureManager filter)")
        try:
            obj.setEditorMode(PROPERTY, 2)
        except Exception as _fw_err:
            _fw_log("treefilter.py:75", _fw_err)
    if list(getattr(obj, PROPERTY)) != words:
        setattr(obj, PROPERTY, words)


def all_tags(doc):
    out = set()
    for obj in (doc.Objects if doc is not None else []):
        out.update(tags(obj))
    return sorted(out, key=str.lower)


def tagged(doc, word):
    word = word.lower()
    return [o for o in doc.Objects if any(t.lower() == word for t in tags(o))]


# ------------------------------------------------------------------ the filter
def matches(obj, label, needle):
    """Does a tree row (its object, the text it shows) match the typed text, in the modes on?"""
    if not needle:
        return True
    needle = needle.lower()
    if mode("Features") and needle in (label or "").lower():
        return True
    if obj is None:
        return False
    if mode("Tags") and any(needle in t.lower() for t in tags(obj)):
        return True
    if mode("Descriptions") and needle in (getattr(obj, "Label2", "") or "").lower():
        return True
    if mode("Comments"):
        text = getattr(obj, "Comment", "") or ""
        if needle in text.lower():
            return True
        try:
            from . import comments
            if needle in (comments.text_of(obj) or "").lower():
                return True
        except Exception as _fw_err:
            _fw_log("treefilter.py:115", _fw_err)
    return False


def hierarchy_only():
    return mode("Hierarchy")


# ------------------------------------------------------------------ the GUI
def _tag_icon(size=16):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    k = size / 16.0
    shape = QtGui.QPolygonF([QtCore.QPointF(2 * k, 2 * k), QtCore.QPointF(8 * k, 2 * k), QtCore.QPointF(14 * k, 8 * k),
                             QtCore.QPointF(8 * k, 14 * k), QtCore.QPointF(2 * k, 8 * k)])
    p.setPen(QtGui.QPen(QtGui.QColor(150, 110, 20), 1.2 * k))
    p.setBrush(QtGui.QColor(250, 205, 80))
    p.drawPolygon(shape)
    p.setBrush(QtGui.QColor(255, 255, 255))
    p.drawEllipse(QtCore.QPointF(5 * k, 5 * k), 1.3 * k, 1.3 * k)
    p.end()
    return QtGui.QIcon(pm)


def _picked():
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        obj = s.Object
        for sub in s.SubElementNames or [""]:
            target = obj
            if "." in sub:
                for name in sub.split(".")[:-1]:
                    child = obj.Document.getObject(name)
                    if child is not None:
                        target = child
            if target not in out:
                out.append(target)
    return out


if Gui is not None:
    class TagsBox(QtWidgets.QFrame):
        """The tag box: the part's tags with ticks for the picked items, and a line for a new one."""

        def __init__(self, objects, parent=None):
            super().__init__(parent, QtCore.Qt.Popup)
            self.setObjectName("SWTagsBox")
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            self.objects = list(objects)
            self.doc = self.objects[0].Document if self.objects else App.ActiveDocument
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(6, 6, 6, 6)
            title = QtWidgets.QLabel("Tags" if self.objects else "Tags (pick items to tag them)")
            title.setStyleSheet("font-weight: bold;")
            lay.addWidget(title)
            self.edit = QtWidgets.QLineEdit()
            self.edit.setObjectName("SWTagsNew")
            self.edit.setPlaceholderText("New tag, then Enter")
            self.edit.returnPressed.connect(self.add_typed)
            self.edit.setVisible(bool(self.objects))    # nothing picked: nothing to tag (hidden, not greyed)
            lay.addWidget(self.edit)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWTagsList")
            self.list.setMinimumWidth(200)
            self.list.setMaximumHeight(180)
            self.list.itemChanged.connect(self._ticked)
            self.list.itemDoubleClicked.connect(self._find)
            lay.addWidget(self.list)
            hint = QtWidgets.QLabel("Double-click a tag to find its items in the tree")
            hint.setStyleSheet("color: gray;")
            lay.addWidget(hint)
            self._fill()

        def _fill(self):
            self.list.blockSignals(True)
            self.list.clear()
            for word in all_tags(self.doc):
                item = QtWidgets.QListWidgetItem(word)
                if self.objects:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    have = [word in tags(o) for o in self.objects]
                    state = QtCore.Qt.Checked if all(have) else \
                        QtCore.Qt.PartiallyChecked if any(have) else QtCore.Qt.Unchecked
                    item.setCheckState(state)
                self.list.addItem(item)
            self.list.blockSignals(False)

        def _apply(self, word, on):
            doc = self.doc
            doc.openTransaction("Tags")
            try:
                for obj in self.objects:
                    have = tags(obj)
                    set_tags(obj, have + [word] if on else [t for t in have if t != word])
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            _refilter()

        def add_typed(self):
            word = self.edit.text().strip()
            if not word or not self.objects:
                return
            self._apply(word, True)
            self.edit.clear()
            self._fill()

        def _ticked(self, item):
            if item.checkState() == QtCore.Qt.PartiallyChecked:
                return
            self._apply(item.text(), item.checkState() == QtCore.Qt.Checked)

        def _find(self, item):
            set_mode("Tags", True)
            box = _filter_box()
            if box is not None:
                box.setText(item.text())
            self.close()

    LAST_BOX = [None]

    def open_tags(anchor=None):
        box = TagsBox(_picked(), Gui.getMainWindow())
        LAST_BOX[0] = box
        box.adjustSize()
        if anchor is not None:
            g = anchor.mapToGlobal(QtCore.QPoint(0, 0))
            box.move(g.x() + anchor.width() - box.width(), g.y() - box.height() - 2)
        else:
            mw = Gui.getMainWindow()
            g = mw.mapToGlobal(QtCore.QPoint(mw.width() - box.width() - 20, mw.height() - box.height() - 40))
            box.move(g)
        box.show()
        box.edit.setFocus()
        return box

    def _header():
        try:
            from . import shell
            pane = shell.shell().left_pane
            return pane.header if pane is not None else None
        except Exception:
            return None

    def _filter_box():
        header = _header()
        return getattr(header, "filter", None)

    def _refilter():
        box = _filter_box()
        if box is not None and box.text():
            box.textChanged.emit(box.text())

    def filter_menu(parent):
        menu = QtWidgets.QMenu(parent)
        menu.setObjectName("SWTreeFilterMenu")
        for key, text, _d in MODES + (HIERARCHY,):
            if key == HIERARCHY[0]:
                menu.addSeparator()
            act = menu.addAction(text)
            act.setObjectName("SWTreeFilter" + key)
            act.setCheckable(True)
            act.setChecked(mode(key))
            act.toggled.connect(lambda on, k=key: (set_mode(k, on), _refilter()))
        return menu

    class _FunnelClick(QtCore.QObject):
        """A click on the funnel at the left of the filter box opens the filter menu."""

        def __init__(self, header):
            super().__init__(header)
            self.header = header
            self.menu = None
            header.installEventFilter(self)

        def funnel_rect(self):
            box = self.header.filter.geometry()
            return QtCore.QRect(0, box.top() - 2, max(box.left(), 4), box.height() + 4)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False
            if obj is self.header and event.type() == QtCore.QEvent.MouseButtonPress \
                    and event.button() == QtCore.Qt.LeftButton:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if self.funnel_rect().contains(pos):
                    self.open(pos)
                    return True
            return False

        def open(self, pos=None):
            self.menu = filter_menu(self.header)
            r = self.funnel_rect()
            self.menu.popup(self.header.mapToGlobal(QtCore.QPoint(r.left(), r.bottom())))
            return self.menu

    FUNNEL = [None]
    BUTTON = [None]

    class _Command:
        def GetResources(self):
            return {"MenuText": "Tags...", "ToolTip": "Adds keywords to the picked items, to find them with the tree's filter",
                    "CmdType": "ForEdit"}

        def IsActive(self):
            return App.ActiveDocument is not None

        def Activated(self):
            open_tags(BUTTON[0])

    def install(tries=20):
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, _Command())
        header = _header()
        if header is None and tries > 0:
            QtCore.QTimer.singleShot(1500, lambda: install(tries - 1))     # the left pane comes later
            return
        if header is not None and FUNNEL[0] is None:
            FUNNEL[0] = _FunnelClick(header)
            header.filter.setToolTip("Filter the FeatureManager design tree (click the funnel for what to filter)")
        bar = Gui.getMainWindow().statusBar()
        if bar is not None and BUTTON[0] is None:
            button = QtWidgets.QToolButton(bar)
            button.setObjectName("SWStatusTags")
            button.setAutoRaise(True)
            button.setIcon(_tag_icon(16))
            button.setToolTip("Tags: add keywords to the picked items")
            button.clicked.connect(lambda: open_tags(button))

            # QStatusBar only appends, so the units box and what is right of it go back on after Tags.
            # (the units box is "SWUnits"; the rebuild icon is hidden while nothing needs a
            # rebuild, so it goes by name too and keeps its visibility)
            after = []
            for name in ("SWUnits", "SWRebuildIndicator", "SWQuickTipsButton"):
                w = bar.findChild(QtWidgets.QWidget, name)
                if w is not None and w.parent() is bar:
                    after.append((w, w.isVisible()))
            for w, _shown in after:
                bar.removeWidget(w)
            bar.addPermanentWidget(button)
            for w, shown in after:
                bar.addPermanentWidget(w)
                w.setVisible(shown)
            BUTTON[0] = button
else:
    def install():
        pass
