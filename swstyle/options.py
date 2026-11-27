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

import copy

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import chrome, migrate, optionspages, paths, sketchoptions, style
from .sketchoptions import Bool, Number, Setting, _param
from .widgets import ui_font

Qt = QtCore.Qt

GENERAL = "General"
UNITS = "Units"
TECHDRAW_GENERAL = "Mod/TechDraw/General"
TECHDRAW_DIMS = "Mod/TechDraw/Dimensions"


class Choice(Setting):
    """A drop-down list; values are what is written (int or str)."""

    def __init__(self, path, key, default, text, choices, tip="", write=None, read=None):
        super().__init__(path, key, default, text, tip)
        self.choices = choices          # [(label, value)]
        self.write, self.read = write, read

    def widget(self):
        self.box = QtWidgets.QComboBox()
        for label, _value in self.choices:
            self.box.addItem(label)
        self.tag(self.box)
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QtWidgets.QLabel(self.text)
        label.setBuddy(self.box)
        lay.addWidget(label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def value(self):
        return self.choices[max(0, self.box.currentIndex())][1]

    def load(self):
        if self.read is not None:
            current = self.read()
        elif isinstance(self.default, str):
            current = _param(self.path).GetString(self.key, self.default)
        else:
            current = _param(self.path).GetInt(self.key, self.default)
        values = [v for _l, v in self.choices]
        self.box.setCurrentIndex(values.index(current) if current in values else 0)
        self.loaded = self.value()

    def save(self):
        if not self.changed():
            return
        if self.write is not None:
            self.write(self.value())
        elif isinstance(self.value(), str):
            _param(self.path).SetString(self.key, self.value())
        else:
            _param(self.path).SetInt(self.key, self.value())
        self.loaded = self.value()


# ---------------------------------------------------------------- the look and the units
def _read_theme():
    return style.theme_name()


def _write_theme(name):
    style.set_theme(name)


def _unit_choices():
    ""
    out, seen = [], set()
    for index, (name, description) in enumerate(chrome.schemas()):
        label = chrome.schema_label(name, description)
        if label in seen or label == "Custom":
            continue
        seen.add(label)
        out.append(("%s (%s)" % (label, _UNIT_WORDS.get(label, description)), index))
    order = ["MKS", "CGS", "MMGS", "IPS"]
    out.sort(key=lambda c: order.index(c[0].split(" ")[0]) if c[0].split(" ")[0] in order else 9)
    return out


_UNIT_WORDS = {"MKS": "meter, kilogram, second", "CGS": "centimeter, gram, second",
               "MMGS": "millimeter, gram, second", "IPS": "inch, pound, second"}


def _read_units():
    current = chrome.current_schema()
    label = None
    names = chrome.schemas()
    if 0 <= current < len(names):
        label = chrome.schema_label(*names[current])
    for text, index in _unit_choices():
        if text.startswith((label or "?") + " "):
            return index
    return current


DECIMALS = [("None", 0), (".1", 1), (".12", 2), (".123", 3), (".1234", 4), (".12345", 5),
            (".123456", 6), (".1234567", 7), (".12345678", 8)]


def _write_decimals(n):
    # FreeCAD 1.1 has no Python call for the decimals: unitspage.apply_decimals has FreeCAD's own
    # Preferences page set them, so they apply at once
    from . import unitspage
    unitspage.apply_decimals(n)



STANDARDS = ["ANSI", "ISO", "DIN", "JIS", "BSI", "GOST", "GB"]
DRAFTING = "DraftingStandard"


def _read_standard():
    doc = App.ActiveDocument
    if doc is not None:
        try:
            if any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
                # fh255: a drawing keeps its standard in its own Document Properties (a drawing template's
                # ANSI or ISO): that one, not the system default
                from . import drawdocprops
                value = dict(drawdocprops.stored(doc)).get("standard")
                if value in STANDARDS:
                    return value
            value = migrate.doc_meta(doc)
            if value in STANDARDS:
                return value
        except Exception as _fw_err:
            _fw_log("options.py:156", _fw_err)
    return paths.params().GetString(DRAFTING, "ISO")


def _keep_others(doc):
    ""


    if doc is None:
        return
    try:
        from . import migrate
        key = migrate.DOC_META_NEW
    except Exception:
        key = "SolidWorksDraftingStandard"
    old = paths.params().GetString(DRAFTING, "ISO")
    for d in App.listDocuments().values():
        try:
            meta = dict(d.Meta or {})
            if d is doc or meta.get("FreeWorksDraftingStandard") or meta.get("SolidWorksDraftingStandard"):
                continue
            gd = Gui.getDocument(d.Name) if App.GuiUp else None
            was = gd.Modified if gd is not None else None
            meta[key] = old
            d.Meta = meta
            if gd is not None and was is False:
                gd.Modified = False
        except Exception as _fw_err:
            _fw_log("options.py:keep_others", _fw_err)


def _write_standard(name):
    doc = App.ActiveDocument
    if doc is not None:
        try:
            meta = dict(doc.Meta)
            meta[migrate.DOC_META_NEW] = name
            doc.Meta = meta
        except Exception as _fw_err:
            _fw_log("options.py:168", _fw_err)
    _keep_others(doc)
    paths.params().SetString(DRAFTING, name)
    # ANSI and JIS draw third-angle views, the others first-angle; ANSI dimensions the ASME way.
    _param(TECHDRAW_GENERAL).SetInt("ProjectionAngle", 1 if name in ("ANSI", "JIS") else 0)
    _param(TECHDRAW_DIMS).SetInt("StandardAndStyle", 2 if name == "ANSI" else 0)


class StandardChoice(Choice):
    ""


    def widget(self):
        row = super().widget()
        self.box.activated.connect(lambda i: self.picked(self.choices[max(0, i)][1]))
        return row

    def picked(self, name):
        try:
            from . import draftstd, drawdocprops
            font = drawdocprops.standard_preset(name).get("ann_font")
            dialog = self.box.window()
            if not font or not hasattr(dialog, "build_all"):
                return
            dialog.build_all()
            for s in getattr(dialog, "settings", []):
                box = getattr(s, "box", None)
                if getattr(s, "page", None) in draftstd.PAGES and s.text == "Font" and \
                        isinstance(box, QtWidgets.QLineEdit):
                    box.setText(font)
        except Exception as _fw_err:
            _fw_log("options.py:standard_picked", _fw_err)


# ---------------------------------------------------------------- pages
# A page: (title, sections, FreeCAD page or None, children). sections as sketchoptions':
# [(heading or None, [settings])]. FreeCAD page: (group, index, its name) for the button.
def _own_system_pages():
    general = [
        (None, [
            Choice("Mod/FreeWorks", style.THEME_SETTING, "Dark", "Look",      # freshdark-1121
                   [(t, t) for t in style.THEMES], read=_read_theme, write=_write_theme),
            Number("RecentFiles", "RecentFiles", 4, "Recent documents to list", "", 0, 30),
        ]),
    ]

    # while it is the look in use, so opening and OK never changes it
    looks = [x for _h, xs in general for x in xs if isinstance(x, Choice) and x.write is _write_theme]
    for x in looks:
        x.text = "Background"
        x.choices = [(t, v) for t, v in x.choices if v != "AMOLED" or _read_theme() == "AMOLED"]
    general = [(h, [x for x in xs if x not in looks]) for h, xs in general]
    colors = [(None, looks)] if looks else []
    try:
        colors = [(None, [optionspages._later("Colors")("Icon color", "Default")] + looks)]
    except Exception as _fw_err:
        _fw_log("options.py:icon-color", _fw_err)
    return [
        ("General", general, ("General", 0, "General"), []),
        ("Drawings", [], ("TechDraw", 0, "TechDraw"), []),
        ("Colors", colors, ("Display", 4, "Display > Colors"), []),
        (sketchoptions.SKETCH[0], sketchoptions.SKETCH[1], ("Sketcher", 2, "Sketcher > General"),
         [(sketchoptions.RELATIONS_SNAPS[0], sketchoptions.RELATIONS_SNAPS[1], None, [])]),
        ("Display", [], ("Display", 0, "Display > 3D View"), []),
        ("Selection", [], ("General", 2, "General > Selection"), []),
        ("Performance", [], ("Display", 5, "Display > Advanced"), []),
        ("Assemblies", [], ("Assembly", 0, "Assembly"), []),
        ("View", [], ("Display", 3, "Display > Navigation"), []),
        ("Backup/Recover", [], ("General", 1, "General > Document"), []),
        ("Import", [], ("Import-Export", 0, "Import-Export"), []),
        ("Export", [], ("Import-Export", 0, "Import-Export"), []),
    ]


def _own_document_pages():
    from . import unitspage
    return [
        ("Drafting Standard", [
            (None, [StandardChoice("", DRAFTING, "ISO", "Overall drafting standard", [(s, s) for s in STANDARDS],
                           read=_read_standard, write=_write_standard)]),
        ], ("TechDraw", 0, "TechDraw"), []),
        ("Units", [

            (None, [unitspage.UnitsTable()]),
        ], None, []),
        ("Image Quality", [], ("Part/Part Design", 1, "Part/Part Design > Shape View"), []),
    ]




SW_NAMES = {"TechDraw": "drawing settings", "Sketcher > General": "sketch settings"}


def _system_pages():
    ""
    return optionspages.system_pages(_own_system_pages())


def _document_pages():
    return optionspages.document_pages(_own_document_pages())


def _html(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_SIZE_GROUP = "Mod/FreeWorks"     # optl24: where the Options box size is kept


_FIELDS = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit)


def _row_colons(page):
    ""

    for label in page.findChildren(QtWidgets.QLabel):
        text = label.text()
        if not text or "<" in text or "\n" in text or len(text) > 70 or text.rstrip()[-1:] in ":.?!)":
            continue
        if label.pixmap() is not None and not label.pixmap().isNull():
            continue
        parent = label.parentWidget()
        lay = parent.layout() if parent is not None else None
        row = _row_of(lay, label) if lay is not None else None
        if row is None:
            continue
        i = row.indexOf(label)
        nxt = [row.itemAt(j).widget() for j in range(i + 1, row.count()) if row.itemAt(j).widget() is not None]
        if nxt and isinstance(nxt[0], _FIELDS):
            label.setText(text.rstrip() + ":")


def _row_of(lay, w):
    """The horizontal layout (or form row) that holds w, if any."""
    if isinstance(lay, QtWidgets.QHBoxLayout) and lay.indexOf(w) >= 0:
        return lay
    if isinstance(lay, QtWidgets.QFormLayout):
        for r in range(lay.rowCount()):
            a = lay.itemAt(r, QtWidgets.QFormLayout.LabelRole)
            if a is not None and a.widget() is w:
                f = lay.itemAt(r, QtWidgets.QFormLayout.FieldRole)
                return _Pair(w, f.widget() if f is not None else None)
    for j in range(lay.count()):
        sub = lay.itemAt(j).layout()
        if sub is not None:
            found = _row_of(sub, w)
            if found is not None:
                return found
    return None


class _Pair:
    """A form row seen as a two-item row (label, field) for _row_colons."""
    def __init__(self, label, field):
        self.items = [label, field]

    def indexOf(self, w):
        return self.items.index(w) if w in self.items else -1

    def count(self):
        return len(self.items)

    def itemAt(self, j):
        w = self.items[j]
        return type("_I", (), {"widget": lambda _s, w=w: w})()


class OptionsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, tab=0):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWOptions")
        self.setFont(ui_font())
        self._size_restore()
        self.settings = []
        self.page_settings = {}         # page index -> its settings (Reset... This Page)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.tabs = QtWidgets.QTabBar(self)
        self.tabs.setObjectName("SWOptionsTabs")
        self.tabs.setExpanding(False)
        self.tabs.addTab("System Options")
        self.tabs.addTab("Document Properties")
        self.tabs.setTabEnabled(1, App.ActiveDocument is not None)

        if hasattr(self.tabs, "setTabVisible"):
            self.tabs.setTabVisible(1, App.ActiveDocument is not None)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(self.tabs, 1)
        self.search = QtWidgets.QLineEdit(self)
        self.search.setObjectName("SWOptionsSearch")
        self.search.setPlaceholderText("Search Options")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(190)
        self.search.textEdited.connect(self._search_edited)
        head.addWidget(self.search)
        lay.addLayout(head)
        body = QtWidgets.QHBoxLayout()
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWOptionsPages")
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(190)
        self.tree.setRootIsDecorated(False)
        self.stack = QtWidgets.QStackedWidget(self)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(self.tree, 1)

        self.reset_button = QtWidgets.QPushButton("Reset...", self)
        self.reset_button.setObjectName("SWOptionsReset")
        self.reset_button.setToolTip("Puts the system options back to their defaults")
        self.reset_button.clicked.connect(self.ask_reset)
        left.addWidget(self.reset_button)
        body.addLayout(left)
        body.addWidget(self.stack, 1)
        lay.addLayout(body, 1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
                                             | QtWidgets.QDialogButtonBox.Help, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.helpRequested.connect(self.show_help)
        if not self._help_available():
            buttons.button(QtWidgets.QDialogButtonBox.Help).hide()
        lay.addWidget(buttons)
        self.trees = [self._pages(_system_pages()), self._pages(_document_pages())]
        self.tabs.currentChanged.connect(self._show_tab)
        self.tree.currentItemChanged.connect(self._show_page)
        self.tabs.setCurrentIndex(tab if self.tabs.isTabEnabled(tab) else 0)
        self._show_tab(self.tabs.currentIndex())

    # search and help (look audit) ----------------------------------------
    def _search_entries(self):
        """[(text shown, tab, page index, setting or None)]: every page and every setting of the open tabs."""
        self.build_all()
        titles = {}                                     # page index -> (tab, title path)

        def walk(entries, tab, path):
            for title, index, children in entries:
                titles[index] = (tab, path + [title])
                walk(children, tab, path + [title])
        walk(self.trees[0], 0, [])
        if self.tabs.isTabEnabled(1) and not drawing_properties_available():
            walk(self.trees[1], 1, [])
        out = []
        for index, (tab, path) in sorted(titles.items()):
            out.append((" > ".join(path), tab, index, None))
            for s in self.page_settings.get(index, []):
                text = str(getattr(s, "text", "") or "").strip()
                if text:
                    out.append(("%s > %s" % (path[-1], text), tab, index, s))
        return out

    def _search_edited(self, text):
        if not text.strip():
            return
        if getattr(self, "_search_model", None) is None:
            QtWidgets.QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._search_hits = {}
                for label, tab, index, setting in self._search_entries():
                    self._search_hits.setdefault(label, (tab, index, setting))
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self._search_model = QtCore.QStringListModel(sorted(self._search_hits), self)
            completer = QtWidgets.QCompleter(self._search_model, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setFilterMode(Qt.MatchContains)
            completer.setMaxVisibleItems(12)
            completer.activated[str].connect(self._search_pick)
            self.search.setCompleter(completer)
            self._search_completer = completer
            completer.setCompletionPrefix(text)
            completer.complete()

    def _search_pick(self, label):
        hit = getattr(self, "_search_hits", {}).get(label)
        if hit is None:
            return
        tab, index, setting = hit
        if self.tabs.currentIndex() != tab and self.tabs.isTabEnabled(tab):
            self.tabs.setCurrentIndex(tab)
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.UserRole) == index:
                parent = item.parent()
                while parent is not None:
                    parent.setExpanded(True)
                    parent = parent.parent()
                self.tree.setCurrentItem(item)
                break
            stack.extend(item.child(i) for i in range(item.childCount()))
        box = getattr(setting, "box", None) if setting is not None else None
        if box is not None:
            page = self.stack.currentWidget()
            try:
                if hasattr(page, "ensureWidgetVisible"):
                    page.ensureWidgetVisible(box)
                box.setFocus()
            except RuntimeError:
                pass
        self.search.clear()

    def _help_available(self):
        try:
            from . import helpmenu
            return hasattr(helpmenu, "HelpWindow")
        except Exception:
            return False

    def show_help(self):
        """The add-on's help window on a page for the open Options page (its group boxes and settings)."""
        from . import helpmenu
        page = self.stack.currentWidget()
        title = self.windowTitle()
        parts = ["<h2>%s</h2>" % _html(title),
                 "<p>Options has two tabs: System Options, settings for the program, and Document Properties, settings kept "
                 "in the document. Pick a page in the list on the left. OK keeps the changes, Cancel drops them; Reset... "
                 "puts the system options back to their defaults. Search Options finds a page or a setting by name.</p>"]
        groups = []
        for box in (page.findChildren(QtWidgets.QGroupBox) if page is not None else []):
            words = []
            for w in box.findChildren(QtWidgets.QWidget):
                text = ""
                if isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)):
                    text = w.text()
                elif isinstance(w, QtWidgets.QLabel):
                    text = w.text()
                text = text.strip().rstrip(":")
                if text and "<" not in text and len(text) < 90 and text not in words:
                    words.append(text)
            groups.append((box.title(), words))
        if groups:
            parts.append("<h3>On this page</h3><dl>")
            for name, words in groups:
                parts.append("<dt><b>%s</b></dt><dd>%s</dd>" % (_html(name), _html(", ".join(words)) or "&nbsp;"))
            parts.append("</dl>")
        win = helpmenu.HelpWindow("home")
        win.view.setHtml("".join(parts))
        win.setWindowTitle("FreeCAD Help - %s" % title)
        win.show()
        win.raise_()
        self._help_window = win

    # pages ---------------------------------------------------------------
    def _pages(self, specs):
        """A place for each page; returns [(title, page index, children)]. A page is built the
        first time it is shown (building all of them made the box take seconds to open)."""
        out = []
        if not hasattr(self, "_unbuilt"):
            self._unbuilt = {}
        for title, sections, freecad, children in specs:
            if sections and freecad is None and not children and \
                    not any(not optionspages.hidden(s) for _heading, rows in sections for s in rows):
                continue                    # every row of this page is one nothing reads: no empty page in the list
            holder = QtWidgets.QWidget()
            holder.setProperty("swTitle", title)
            index = self.stack.addWidget(holder)
            self._unbuilt[index] = (title, sections, freecad)
            out.append((title, index, self._pages(children)))
        return out

    def build(self, index):
        """The page at index, built now if it was not yet."""
        spec = self._unbuilt.pop(index, None)
        if spec is not None:
            holder = self.stack.widget(index)
            first = len(self.settings)
            page = self._page(*spec)
            _row_colons(page)
            self.page_settings[index] = self.settings[first:]
            self.stack.insertWidget(index, page)
            self.stack.removeWidget(holder)
            holder.deleteLater()
        return self.stack.widget(index)

    def build_all(self):
        """Every page built (for checks that look for a control without opening its page)."""
        for index in sorted(self._unbuilt):
            self.build(index)

    def _page(self, title, sections, freecad):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(inner)
        lay.setContentsMargins(12, 6, 12, 6)
        by_key = {}
        for heading, settings in sections:
            settings = [s for s in settings if sketchoptions.available(s) and not optionspages.hidden(s)]
            if not settings:
                continue
            target = lay
            if heading:
                box = QtWidgets.QGroupBox(heading)
                target = QtWidgets.QVBoxLayout(box)
                lay.addWidget(box)
            for s in settings:
                s = _copy(s)
                s._fw_row = s.widget()      # extapps83: the whole row, hidden while its parent box is off
                target.addWidget(s._fw_row)
                s.load()
                by_key[s.key] = s
                self.settings.append(s)
        # extapps83: a row whose parent box (or the parent's parent) is off is hidden, not greyed (Ati: greyed
        # counts as dead); it shows again, as left, when the box is ticked
        def _shown(s):
            need, seen = getattr(s, "needs", None), set()
            while need in by_key and _parent_box(by_key[need]) and need not in seen:
                seen.add(need)
                if not by_key[need].box.isChecked():
                    return False
                need = getattr(by_key[need], "needs", None)
            return True
        children = [s for s in by_key.values() if getattr(s, "needs", None) in by_key
                    and _parent_box(by_key[s.needs])]

        def _follow(_on=None, children=children):
            for s in children:
                (getattr(s, "_fw_row", None) or s.box).setVisible(_shown(s))
        for s in children:
            by_key[s.needs].box.toggled.connect(_follow)
        _follow()
        if freecad is not None:
            group, index, name = freecad
            name = SW_NAMES.get(name, name)
            text = ("More settings for this are on FreeCAD's own %s page." % name) if sections else \
                   ("FreeCAD keeps these settings on its own %s page." % name)
            note = QtWidgets.QLabel(text)
            note.setWordWrap(True)
            lay.addWidget(note)
            button = QtWidgets.QPushButton("Open %s" % name)
            button.setObjectName("SWOptionsMore")
            button.clicked.connect(lambda _c=False, g=group, i=index: self._freecad_page(g, i))
            row = QtWidgets.QHBoxLayout()
            row.addWidget(button)
            row.addStretch(1)
            lay.addLayout(row)
        lay.addStretch(1)
        scroll.setWidget(inner)
        scroll.setProperty("swTitle", title)
        return scroll

    def _freecad_page(self, group, index):
        QtCore.QTimer.singleShot(0, lambda: _show_preferences(group, index))

    def _fill_tree(self, entries, parent=None):
        for title, index, children in entries:
            item = QtWidgets.QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, index)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self._fill_tree(children, item)

            item.setExpanded(parent is None)

    def _drawing_tree(self):
        ""


        if getattr(self, "_dd", None) is not None:
            return self._dd_entries
        from . import drawdocprops
        self._dd = drawdocprops.DocumentPropertiesDialog(App.ActiveDocument, self)
        self._dd.hide()
        moved = {}          # the drawing box's page index -> this box's
        pages = [self._dd.stack.widget(i) for i in range(self._dd.stack.count())]
        for index, page in enumerate(pages):
            self._dd.stack.removeWidget(page)
            moved[index] = self.stack.addWidget(page)

        def walk(item):
            out = []
            for i in range(item.childCount()):
                child = item.child(i)
                out.append((child.text(0), moved.get(child.data(0, Qt.UserRole)), walk(child)))
            return out
        self._dd_entries = walk(self._dd.tree.invisibleRootItem())
        return self._dd_entries

    def _show_tab(self, tab):
        if tab == 1 and drawing_properties_available():
            self.reset_button.setVisible(False)
            self.tree.blockSignals(True)
            self.tree.clear()
            self._fill_tree(self._drawing_tree())
            self.tree.blockSignals(False)
            self._fit_tree()
            start = getattr(self, "_start_page", None)
            item = self._find_item(start) if start else None
            self.tree.setCurrentItem(item or self.tree.topLevelItem(0))
            self._show_page(self.tree.currentItem())
            return
        self.reset_button.setVisible(tab == 0)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._fill_tree(self.trees[tab])
        self.tree.blockSignals(False)
        self._fit_tree()
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._show_page(self.tree.currentItem())

    def _fit_tree(self):
        ""


        try:
            fm = self.tree.fontMetrics()
            step = self.tree.indentation()

            def need(entries, depth):
                w = 0
                for title, _index, children in entries or ():
                    w = max(w, (depth + 1) * step + fm.horizontalAdvance(title), need(children, depth + 1))
                return w
            widest = max([need(entries, 0) for entries in list(self.trees) + [getattr(self, "_dd_entries", None)]])
            bar = self.tree.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent, None, self.tree)
            want = max(190, min(280, widest + bar + 2 * self.tree.frameWidth() + 16))
            if self.tree.width() != want:
                self.tree.setFixedWidth(want)
        except Exception as _fw_err:
            _fw_log("options.py:fit_tree", _fw_err)

    def _find_item(self, title):
        found = self.tree.findItems(title, Qt.MatchExactly | Qt.MatchRecursive)
        return found[0] if found else None

    def show_page(self, title):
        """Opens the page with this title on the current tab (Document Properties > Drawing Sheets)."""
        item = self._find_item(title)
        if item is not None:
            parent = item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.setCurrentItem(item)
        return item is not None

    def _show_page(self, item, _previous=None):
        if item is None:
            return
        self.build(item.data(0, Qt.UserRole))
        self.stack.setCurrentIndex(item.data(0, Qt.UserRole))
        self.setWindowTitle("%s - %s" % (self.tabs.tabText(self.tabs.currentIndex()), item.text(0)))

    # Reset... -------------------------------------------------------------
    def _indices(self, entries):
        out = []
        for _title, index, children in entries:
            out.append(index)
            out.extend(self._indices(children))
        return out

    def ask_reset(self):
        ""

        item = self.tree.currentItem()
        title = item.text(0) if item is not None else ""
        if reset_hook is not None:
            choice = reset_hook(title)
        else:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Reset")
            box.setIcon(QtWidgets.QMessageBox.Question)
            box.setText("Reset system options to their default values?")
            box.setInformativeText("Reset All: every system option.\nReset This Page: only the options on %s." % title)
            every = box.addButton("Reset All", QtWidgets.QMessageBox.AcceptRole)
            page = box.addButton("Reset This Page", QtWidgets.QMessageBox.AcceptRole)
            box.addButton(QtWidgets.QMessageBox.Cancel)
            box.exec()
            choice = "all" if box.clickedButton() is every else "page" if box.clickedButton() is page else None
        if choice is None:
            return 0
        if choice == "page" and item is not None:
            indices = [item.data(0, Qt.UserRole)]
        else:
            indices = self._indices(self.trees[0])
        count = 0
        for index in indices:
            self.build(index)
            for s in self.page_settings.get(index, []):
                try:
                    count += 1 if reset_setting(s) else 0
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: reset %s: %s\n" % (getattr(s, "key", "?"), error))
        return count

    def select(self, title):
        """For checks: shows the page called title on the current tab."""
        found = self.tree.findItems(title, Qt.MatchExactly | Qt.MatchRecursive)
        if found:
            self.tree.setCurrentItem(found[0])

    def _size_group(self):
        return App.ParamGet("User parameter:BaseApp/Preferences/%s" % _SIZE_GROUP)

    def _size_restore(self):
        ""

        w = h = 0
        try:
            g = self._size_group()
            w, h = g.GetInt("OptionsWidth", 0), g.GetInt("OptionsHeight", 0)
        except Exception:
            pass
        try:
            screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
            sw, sh = screen.width(), screen.height()
        except Exception:
            sw, sh = 1920, 1040
        if w < 400 or h < 300:
            w, h = int(sw * 0.73), int(sh * 0.91)
        # BB44 DS-2: the floor never past the screen (1080p at 200% leaves 540 logical px: OK/Cancel stay on it)
        bar = self.frameGeometry().height() - self.height()
        bar = bar if bar > 0 else 32        # the title bar (not drawn yet): Windows' at 100 %
        self.resize(min(max(760, w), sw), min(max(560, h), sh - bar))
        try:
            top = screen.topLeft() if "screen" in locals() else None
            if top is not None:
                self.move(max(top.x(), screen.x() + (sw - self.width()) // 2),
                          max(top.y(), screen.y() + (sh - self.height() - bar) // 2))
        except Exception as _fw_err:
            _fw_log("options.py:size place", _fw_err)

    def done(self, result):
        try:
            g = self._size_group()
            g.SetInt("OptionsWidth", self.width())
            g.SetInt("OptionsHeight", self.height())
        except Exception:
            pass
        super().done(result)

    def accept(self):
        from . import smengine

        old_sheet_metal = smengine.enabled()
        theme = None
        for s in self.settings:
            if isinstance(s, Choice) and s.write is _write_theme:
                theme = s          # the look last: it restyles the window
                continue
            try:
                s.save()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: option %s not saved: %s\n" % (s.key, error))
        dd = getattr(self, "_dd", None)
        if dd is not None:
            try:
                dd.ok()             # the drawing's Document Properties (drawdocprops), kept in the drawing
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: drawing document properties not saved: %s\n" % error)
        super().accept()
        if smengine.enabled() != old_sheet_metal:
            from . import cmtabs

            cmtabs.apply()
        if theme is not None and theme.changed():
            QtCore.QTimer.singleShot(0, theme.save)


reset_hook = None       # checks: callable(page title) -> "all" / "page" / None instead of the box


def reset_setting(s):
    ""

    if isinstance(s, optionspages.ColorList):
        s.reset_all()
        return True
    if isinstance(s, optionspages.Radio):
        return s.reset()        # fh236: round buttons with a default (Import > Unit, Solid and Surface)
    if callable(getattr(s, "read", None)):
        return _factory_reset(s)
    if not getattr(s, "path", "") or getattr(s, "default", None) is None:
        return False
    box, d = getattr(s, "box", None), s.default
    if isinstance(box, QtWidgets.QCheckBox):
        if not box.isEnabled():
            return False
        box.setChecked(bool(d))
    elif isinstance(box, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
        if isinstance(d, str):          # fh252: a value kept as text with its unit ("0.00deg", Area Hatch/Fill)
            import re
            m = re.match(r"\s*([-+]?\d*\.?\d+)", d)
            if m is None:
                return False
            d = float(m.group(1))
        box.setValue(type(box.value())(d))
    elif isinstance(box, QtWidgets.QComboBox):
        if isinstance(s, Choice):
            values = [v for _l, v in s.choices]
            if d not in values:
                return False
            box.setCurrentIndex(values.index(d))
        else:
            i = box.findText(str(d))
            if i < 0:
                return False
            box.setCurrentIndex(i)
    elif isinstance(box, QtWidgets.QLineEdit):
        box.setText(str(d))
    elif isinstance(box, QtWidgets.QSlider) and str(d) in getattr(s, "stops", ()):     # extapps82
        box.setValue(s.stops.index(str(d)))
    else:
        return False
    return True


def _factory_reset(s):
    ""



    try:
        from . import optionsfactory
        got = optionsfactory.FACTORY.get(getattr(s, "key", None))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: option defaults: %s\n" % error)
        got = None
    if got is None:
        return False
    kind, d = got
    box = getattr(s, "box", None)
    if kind == "bool" and isinstance(box, QtWidgets.QCheckBox):
        if box.isChecked() == bool(d):
            return False
        box.setChecked(bool(d))
    elif kind == "number" and isinstance(box, (QtWidgets.QDoubleSpinBox, QtWidgets.QSpinBox)):
        if abs(box.value() - d) < 1e-9:
            return False
        box.setValue(type(box.value())(d))
    elif kind == "combo" and isinstance(box, QtWidgets.QComboBox):
        i = box.findText(str(d))
        if i < 0 or i == box.currentIndex():
            return False
        box.setCurrentIndex(i)
    elif kind == "slider" and isinstance(box, QtWidgets.QSlider):
        if box.value() == int(d):
            return False
        box.setValue(int(d))
    elif kind == "checknumber" and isinstance(box, QtWidgets.QCheckBox) and hasattr(s, "number"):
        on, n = d
        if box.isChecked() == bool(on) and s.number.value() == int(n):
            return False
        box.setChecked(bool(on))
        s.number.setValue(int(n))
    elif kind == "checkcombo" and isinstance(getattr(s, "check", None), QtWidgets.QCheckBox) \
            and isinstance(box, QtWidgets.QComboBox):
        on, choice = d
        i = box.findText(str(choice))
        if s.check.isChecked() == bool(on) and (i < 0 or i == box.currentIndex()):
            return False
        s.check.setChecked(bool(on))
        if i >= 0:
            box.setCurrentIndex(i)
    else:
        return False
    return True


def _is_drawing(doc):
    return doc is not None and any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)


def drawing_properties_available(doc=None):
    """A drawing is active and drawdocprops.document_properties() is installed."""
    doc = doc or App.ActiveDocument
    if not _is_drawing(doc):
        return False
    try:
        from . import drawdocprops
        return callable(getattr(drawdocprops, "document_properties", None))
    except ImportError:
        return False


def open_drawing_properties(doc=None, start_page=None):
    ""
    return show(1, start_page)


def show_document_properties(doc=None, start_page=None):
    """Document Properties (right-click > Document Properties..., a page's own button): the Options box on
    its Document Properties tab, at start_page when given."""
    return show(1, start_page)


def _parent_box(setting):
    """extapps84: a row other rows can hang off: a Bool, or any row whose box is a check box."""
    return isinstance(setting, Bool) or isinstance(getattr(setting, "box", None), QtWidgets.QCheckBox)


def _copy(setting):
    """Each box gets its own copy: the specs are shared with sketchoptions' pages."""
    return copy.copy(setting)


def _show_preferences(group, index):
    try:
        Gui.showPreferences(group, index)
    except Exception:
        Gui.runCommand("Std_DlgPreferences", 0)


_open = []


def show(tab=0, start_page=None):
    box = OptionsDialog(tab=tab)
    if start_page:
        box.show_page(start_page)
    _open.append(box)
    try:
        box.exec()
    finally:
        _open.remove(box)
        box.deleteLater()


class OptionsCommand:
    def GetResources(self):
        return {"MenuText": "Options...", "ToolTip": "Program settings and this file's settings",
                "Pixmap": "preferences-system", "CmdType": "ForEdit"}

    def Activated(self):
        QtCore.QTimer.singleShot(0, show)

    def IsActive(self):
        return True


class _GridWatch:
    """fh267: the active document's own Grid/Snap goes into FreeCAD's sketcher settings when it becomes active."""

    def slotActivateDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda name=doc.Name: _apply_grid(name))


def _apply_grid(name):
    try:
        if name in App.listDocuments():
            optionspages.apply_doc_grid(App.getDocument(name))
    except Exception as _fw_err:
        _fw_log("options.py:apply_grid", _fw_err)


_GRID_WATCH = []


def register():
    Gui.addCommand("SWStyle_Options", OptionsCommand())
    if not _GRID_WATCH:
        _GRID_WATCH.append(_GridWatch())
        App.addDocumentObserver(_GRID_WATCH[0])
