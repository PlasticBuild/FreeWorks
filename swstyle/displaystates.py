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

import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

TITLE = "Display States"
KEY = "SWDisplayStates"
STEM = "Display State "


def _data(doc):
    try:
        return json.loads(doc.Meta.get(KEY, "") or "{}")
    except Exception:
        return {}


def _save(doc, data):
    meta = dict(doc.Meta)
    meta[KEY] = json.dumps(data)
    doc.Meta = meta


def names(doc):
    return list(_data(doc).get("order", []))


def active(doc):
    return _data(doc).get("active")


def _in_body(obj):
    return any(p.isDerivedFrom("PartDesign::Body") for p in obj.InList)


def _rgbt(m):
    return list(m.DiffuseColor[:3]) + [float(m.Transparency)]


def capture(doc):
    """The look of doc now: {object name: {v, m, a?, sw?}}."""
    from . import appearance
    out = {}
    for obj in doc.Objects:
        vo = getattr(obj, "ViewObject", None)
        if vo is None:
            continue
        item = {"v": bool(vo.Visibility)}
        try:
            item["m"] = vo.DisplayMode
        except Exception as _fw_err:
            _fw_log("displaystates.py:77", _fw_err)
        if hasattr(vo, "Transparency"):

            try:
                item["t"] = int(vo.Transparency)
            except Exception as _fw_err:
                _fw_log("displaystates.py:83", _fw_err)
        if obj.TypeId == "PartDesign::Body":
            item["sw"] = appearance.stored(obj)
        elif hasattr(vo, "ShapeAppearance") and not _in_body(obj):
            try:
                item["a"] = [_rgbt(m) for m in vo.ShapeAppearance]
            except Exception as _fw_err:
                _fw_log("displaystates.py:90", _fw_err)
        out[obj.Name] = item
    return out


def restore(doc, look):
    from . import appearance
    for name, item in look.items():
        obj = doc.getObject(name)
        vo = getattr(obj, "ViewObject", None) if obj is not None else None
        if vo is None:
            continue
        mode = item.get("m")
        try:
            if mode and mode != vo.DisplayMode and mode in vo.listDisplayModes():
                vo.DisplayMode = mode
        except Exception as _fw_err:
            _fw_log("displaystates.py:107", _fw_err)
        if "sw" in item:
            if item["sw"] != appearance.stored(obj):
                appearance.store(obj, item["sw"])
            appearance.paint(obj)
        elif "a" in item:
            try:
                now = list(vo.ShapeAppearance)
                want = item["a"]
                if len(want) != len(now):
                    want = want[:1] * len(now)
                vo.ShapeAppearance = [appearance._material(now[i], c) for i, c in enumerate(want)]
            except Exception as _fw_err:
                _fw_log("displaystates.py:120", _fw_err)
        if "t" in item:
            try:
                if int(vo.Transparency) != item["t"]:
                    vo.Transparency = item["t"]
            except Exception as _fw_err:
                _fw_log("displaystates.py:126", _fw_err)
        if bool(vo.Visibility) != item["v"]:
            vo.Visibility = item["v"]


def _config(doc):
    try:
        from . import configmanager
        t = configmanager.table(doc)
        if t is not None and t.active():
            return t.active()
    except Exception as _fw_err:
        _fw_log("displaystates.py:config", _fw_err)
    return "Default"


def _is_assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc) is not None
    except Exception:
        return False


def default_name(doc, n=1, config=None):
    ""




    if _is_assembly(doc):
        return "Display State-%d" % n
    return "<%s>_%s%d" % (config or _config(doc), STEM, n)


def _next_name(doc):
    have = set(names(doc))
    n = 1
    while default_name(doc, n) in have or "Display State-%d" % n in have:
        n += 1
    return default_name(doc, n)


def add(doc, name=None):
    """Keeps the look now as a new state, made active; its name."""
    data = _data(doc)
    data.setdefault("order", [])
    data.setdefault("states", {})
    if data.get("active") in data["states"]:
        data["states"][data["active"]] = capture(doc)
    name = (name or "").strip() or _next_name(doc)
    if name in data["states"]:
        raise ValueError("There is already a display state named %s" % name)
    data["states"][name] = capture(doc)
    data["order"].append(name)
    data["active"] = name
    cfg = _config(doc)
    data.setdefault("cfg", {})[name] = cfg
    _save(doc, data)
    _remember(doc, cfg, name)
    return name


def ensure_default(doc):
    ""

    if names(doc):
        return None
    return add(doc)


def activate(doc, name):
    data = _data(doc)
    states = data.get("states", {})
    if name not in states:
        raise ValueError("No display state named %s" % name)
    if data.get("active") == name:
        return
    if data.get("active") in states:
        states[data["active"]] = capture(doc)
    data["active"] = name
    _save(doc, data)
    restore(doc, states[name])
    _remember(doc, _config(doc), name)


def rename(doc, old, new):
    data = _data(doc)
    new = new.strip()
    if not new or new in data.get("states", {}):
        raise ValueError("Give a new name that is not used yet")
    data["states"][new] = data["states"].pop(old)
    data["order"] = [new if n == old else n for n in data["order"]]
    if data.get("active") == old:
        data["active"] = new
    if old in data.get("cfg", {}):
        data["cfg"][new] = data["cfg"].pop(old)
    _save(doc, data)
    try:
        from . import asmdisplay
        for cfg, state in list(_per_config(doc).items()):
            if state == old:
                asmdisplay._set_state_of(doc, cfg, new)
    except Exception as _fw_err:
        _fw_log("displaystates.py:rename-link", _fw_err)


def delete(doc, name):
    ""
    data = _data(doc)
    if name in data.get("order", []) and len(data["order"]) == 1:
        raise ValueError("The last display state can't be deleted")
    if linked(doc) and len(listed(doc)) <= 1 and name in listed(doc):
        raise ValueError("The last display state of a configuration can't be deleted")
    if data.get("active") == name and len(data.get("order", [])) > 1:
        raise ValueError("Activate another display state before deleting this one")
    data["states"].pop(name, None)
    data["order"] = [n for n in data["order"] if n != name]
    data.get("cfg", {}).pop(name, None)
    if data.get("active") == name:
        data["active"] = None
    _save(doc, data)


def _save_per(doc, per):
    try:
        from . import asmdisplay
        meta = dict(doc.Meta)
        meta[asmdisplay.PER_CONFIG] = json.dumps(per)
        doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("displaystates.py:per", _fw_err)


def config_renamed(doc, old, new):
    ""

    data, per = _data(doc), _per_config(doc)
    states = data.get("states", {})
    mine = [n for n in data.get("order", []) if state_config(doc, n, data, per) == old]
    cfg = data.setdefault("cfg", {})
    renamed = {}
    for n in mine:
        cfg[n] = new
        stem = "<%s>_" % old
        if n.startswith(stem):
            nn = "<%s>_" % new + n[len(stem):]
            if nn not in states:
                renamed[n] = nn
    for n, nn in renamed.items():
        states[nn] = states.pop(n)
        cfg[nn] = cfg.pop(n)
        data["order"] = [nn if x == n else x for x in data["order"]]
        if data.get("active") == n:
            data["active"] = nn
    if mine or renamed:
        _save(doc, data)
    if old in per or renamed:
        if old in per:
            per[new] = per.pop(old)
        per = {c: renamed.get(v, v) for c, v in per.items()}
        _save_per(doc, per)
    return renamed


def config_deleted(doc, name):
    """A configuration deleted: with the display states linked, its own states go with it (one stays if
    it was the part's last)."""
    data, per = _data(doc), _per_config(doc)
    if linked(doc) and data.get("order"):
        mine = [n for n in data["order"] if state_config(doc, n, data, per) == name and n != data.get("active")]
        if len(mine) >= len(data["order"]):
            mine = mine[1:]
        for n in mine:
            data["states"].pop(n, None)
            data.get("cfg", {}).pop(n, None)
        data["order"] = [n for n in data["order"] if n not in mine]
        if mine:
            _save(doc, data)
    if name in per:
        per.pop(name)
        _save_per(doc, per)


def linked(doc):
    ""

    try:
        from . import asmdisplay
        return asmdisplay.linked(doc)
    except Exception:
        return True


def set_linked(doc, on):
    from . import asmdisplay
    asmdisplay.set_linked(doc, on)


def _per_config(doc):
    try:
        from . import asmdisplay
        return json.loads(doc.Meta.get(asmdisplay.PER_CONFIG, "") or "{}")
    except Exception:
        return {}


def _remember(doc, cfg, name):
    ""

    if not linked(doc):
        return
    try:
        from . import asmdisplay
        if _per_config(doc).get(cfg) != name:
            asmdisplay._set_state_of(doc, cfg, name)
    except Exception as _fw_err:
        _fw_log("displaystates.py:remember", _fw_err)


def state_config(doc, name, data=None, per=None):
    """The configuration a display state belongs to (None: listed in every configuration)."""
    data = data if data is not None else _data(doc)
    cfg = data.get("cfg", {}).get(name)
    if cfg is None:
        per = per if per is not None else _per_config(doc)
        cfg = next((c for c, n in per.items() if n == name), None)
    if cfg is None and name.startswith("<") and ">_" in name:
        cfg = name[1:name.index(">_")]
    if cfg is None and " Display State-" in name:
        cfg = name[:name.index(" Display State-")]
    return cfg


def listed(doc):
    """The display states the ConfigurationManager lists now: the active configuration's when
    linked, all of them when not."""
    data = _data(doc)
    order = list(data.get("order", []))
    if not linked(doc):
        return order
    cfg, per = _config(doc), _per_config(doc)
    return [n for n in order if state_config(doc, n, data, per) in (None, cfg)]


class PropertiesPanel:
    ""

    def __init__(self, doc, name):
        self.doc, self.name = doc, name
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDisplayStateProperties")
        self.form.setWindowTitle("Display State Properties")
        lay = QtWidgets.QVBoxLayout(self.form)
        box = QtWidgets.QWidget()          # the page's own heading names it: no second title
        inner = QtWidgets.QVBoxLayout(box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.addWidget(QtWidgets.QLabel("Display State name:"))
        self.edit = QtWidgets.QLineEdit(name)
        self.edit.setObjectName("SWDisplayStatePropName")
        inner.addWidget(self.edit)
        self.link = QtWidgets.QCheckBox("Link Display States to configurations")
        self.link.setObjectName("SWDisplayStatePropLink")
        self.link.setChecked(linked(doc))
        inner.addWidget(self.link)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        inner.addWidget(self.note)
        lay.addWidget(box)
        lay.addStretch(1)

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

    def accept(self):
        try:
            ensure_default(self.doc)
            new = self.edit.text().strip()
            if new and new != self.name and self.name in names(self.doc):
                rename(self.doc, self.name, new)
            if self.link.isChecked() != linked(self.doc):
                set_linked(self.doc, self.link.isChecked())
        except Exception as error:
            self.note.setText(str(error))
            return False
        Gui.Control.closeDialog()
        refresh_panes()
        _tree_again()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def properties(doc, name):
    if Gui.Control.activeDialog():
        return None
    panel = PropertiesPanel(doc, name)
    Gui.Control.showDialog(panel)
    return panel


_PANES = []


def _state_icon():
    try:
        from . import icons
        return icons.drawn("ChangeDisplayStates")
    except Exception as _fw_err:
        _fw_log("displaystates.py:icon", _fw_err)
        from PySide import QtGui
        return QtGui.QIcon()


def _tree_again():
    """The FeatureManager tree's top row names the active display state: rebuilt after a change."""
    try:
        for view in Gui.getMainWindow().findChildren(QtWidgets.QTreeView):
            fm = getattr(view, "fm", None)
            if fm is not None and hasattr(fm, "rebuild"):
                fm.rebuild()
    except Exception as _fw_err:
        _fw_log("displaystates.py:tree", _fw_err)


def refresh_panes():
    for pane in list(_PANES):
        try:
            pane.refresh()
        except RuntimeError:
            _PANES.remove(pane)


class ConfigPane(QtWidgets.QWidget):
    """The ConfigurationManager's lower pane: Display States (linked)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWConfigDisplayStates")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QtWidgets.QLabel(self)
        self.title.setObjectName("SWConfigDisplayStatesTitle")
        self.title.setContentsMargins(6, 3, 6, 3)
        lay.addWidget(self.title)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWConfigDisplayStateList")
        self.list.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu_at)
        self.list.itemDoubleClicked.connect(lambda item: self.activate(item))
        self.list.itemChanged.connect(self._renamed)
        lay.addWidget(self.list, 1)
        self._key = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(700)        # follows Show Configuration, Undo and other windows
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        _PANES.append(self)
        self.refresh()

    def poll(self):
        if not self.isVisible():
            return
        doc = App.ActiveDocument
        key = None
        if doc is not None:
            key = (doc.Name, doc.Meta.get(KEY, ""), _config(doc))
        if key != self._key:
            self.refresh()

    def refresh(self):
        from PySide import QtGui
        doc = App.ActiveDocument
        self._key = (doc.Name, doc.Meta.get(KEY, ""), _config(doc)) if doc is not None else None
        blocked = self.list.blockSignals(True)
        self.list.clear()
        self.title.setText("Display States (linked)" if doc is None or linked(doc) else "Display States")
        if doc is not None:
            on = active(doc)
            shown = listed(doc) if names(doc) else [default_name(doc)]
            for n in shown:
                item = QtWidgets.QListWidgetItem(n)
                item.setData(QtCore.Qt.UserRole, n)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
                item.setIcon(_state_icon())
                if n == on or not names(doc):
                    font = QtGui.QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(QtCore.Qt.gray)))
                self.list.addItem(item)
        self.list.blockSignals(blocked)

    def _note(self, error):
        try:
            Gui.getMainWindow().statusBar().showMessage(str(error), 5000)
        except Exception as _fw_err:
            _fw_log("displaystates.py:note", _fw_err)

    def _run(self, f, *args):
        doc = App.ActiveDocument
        if doc is None:
            return None
        try:
            ensure_default(doc)
            out = f(doc, *args)
        except Exception as error:
            self._note(error)
            out = None
        self.refresh()
        _tree_again()
        return out

    def activate(self, item):
        name = item.data(QtCore.Qt.UserRole) if item is not None else None
        if name:
            self._run(activate, name)

    def _renamed(self, item):
        old, new = item.data(QtCore.Qt.UserRole), item.text().strip()
        if old and new and new != old:
            QtCore.QTimer.singleShot(0, lambda: self._run(rename, old, new))

    def entries(self, item):
        """The right-click menu: [(text, run)] (only what can act now: no greyed rows)."""
        doc = App.ActiveDocument
        if doc is None:
            return []
        out = [("Add Display State", lambda: self._run(add))]
        name = item.data(QtCore.Qt.UserRole) if item is not None else None
        if name:
            if name != active(doc) and names(doc):
                out.insert(0, ("Activate Display State", lambda: self.activate(item)))
            out.append(("Rename", lambda: self.list.editItem(item)))
            if len(listed(doc)) > 1 and name != active(doc):
                out.append(("Delete", lambda: self._run(delete, name)))
            out.append(("Properties...", lambda: properties(doc, name)))
        return out

    def _menu_at(self, pos):
        entries = self.entries(self.list.itemAt(pos))
        if not entries:
            return
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWConfigDisplayStateMenu")
        for text, run in entries:
            act = menu.addAction(text)
            act.triggered.connect(lambda checked=False, run=run: run())
        menu.popup(self.list.viewport().mapToGlobal(pos))


def attach(page, layout, tree):
    """The ConfigurationManager page: configurations above, Display States below (a splitter)."""
    split = QtWidgets.QSplitter(QtCore.Qt.Vertical, page)
    split.setObjectName("SWConfigSplit")
    split.setChildrenCollapsible(False)
    split.addWidget(tree)
    pane = ConfigPane(split)
    split.addWidget(pane)
    split.setStretchFactor(0, 3)
    split.setStretchFactor(1, 1)
    layout.addWidget(split)
    return pane


class DisplayStatesWindow(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        self.setWindowTitle(TITLE)
        self.setObjectName("SWDisplayStates")
        self.resize(320, 360)
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWDisplayStateList")
        self.list.itemDoubleClicked.connect(lambda item: self.activate())
        lay.addWidget(self.list, 1)
        row = QtWidgets.QGridLayout()
        for i, (label, name, slot) in enumerate((("Activate", "SWDisplayStateActivate", self.activate),
                                                  ("Add Display State", "SWDisplayStateAdd", self.add),
                                                  ("Rename", "SWDisplayStateRename", self.rename),
                                                  ("Delete", "SWDisplayStateDelete", self.delete))):
            b = QtWidgets.QPushButton(label)
            b.setObjectName(name)
            b.clicked.connect(slot)
            row.addWidget(b, i // 2, i % 2)
        lay.addLayout(row)
        self.name = QtWidgets.QLineEdit()
        self.name.setObjectName("SWDisplayStateName")
        self.name.setPlaceholderText("Name for Add or Rename (empty: the next Display State)")
        lay.addWidget(self.name)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("SWDisplayStateNote")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        lay.addWidget(close, 0, QtCore.Qt.AlignRight)
        self.fill()

    def fill(self):
        from PySide import QtGui
        doc = App.ActiveDocument
        self.list.clear()
        if doc is None:
            return
        on = active(doc)
        for n in names(doc):
            item = QtWidgets.QListWidgetItem(n)
            if n == on:
                font = QtGui.QFont(item.font())
                font.setBold(True)
                item.setFont(font)
                item.setText(n + "  (active)")
            item.setData(QtCore.Qt.UserRole, n)
            self.list.addItem(item)
        if not names(doc):

            item = QtWidgets.QListWidgetItem(default_name(doc) + "  (active)")
            font = QtGui.QFont(item.font())
            font.setBold(True)
            item.setFont(font)
            item.setData(QtCore.Qt.UserRole, default_name(doc))
            self.list.addItem(item)

    def _picked(self):
        item = self.list.currentItem()
        return item.data(QtCore.Qt.UserRole) if item is not None else None

    def _do(self, f, *args):
        doc = App.ActiveDocument
        if doc is None:
            return
        try:
            out = f(doc, *args)
        except Exception as error:
            self.note.setText(str(error))
            return
        self.note.setText("")
        self.fill()
        return out

    def activate(self):
        name = self._picked()
        if name:
            if names(App.ActiveDocument):
                self._do(activate, name)
            self.note.setText("%s is active." % name)

    def add(self):
        self._do(ensure_default)
        name = self._do(add, self.name.text())
        if name:
            self.name.clear()
            self.note.setText("%s added and active." % name)

    def rename(self):
        name = self._picked()
        if name:
            self._do(ensure_default)
            self._do(rename, name, self.name.text())
            self.name.clear()

    def delete(self):
        name = self._picked()
        if name:
            if not names(App.ActiveDocument):
                self.note.setText("The last display state can't be deleted")
                return
            self._do(delete, name)

    def closeEvent(self, event):
        _OPEN.pop("win", None)
        super().closeEvent(event)


_OPEN = {}


def open_window():
    win = _OPEN.get("win")
    if win is None or not win.isVisible():
        win = DisplayStatesWindow()
        _OPEN["win"] = win
    else:
        win.fill()
    win.show()
    win.raise_()
    return win


class _Window:
    def GetResources(self):
        return {"Pixmap": "DrawStyleShaded", "MenuText": "Change Display States",
                "ToolTip": "Lists the part's display states: activate, add, rename or delete one"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        QtCore.QTimer.singleShot(0, open_window)


class _Add:
    def GetResources(self):
        return {"Pixmap": "DrawStyleShaded", "MenuText": "Add Display State",
                "ToolTip": "Keeps the look as it is now as a new display state and makes it active"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument

        def run():
            ensure_default(doc)
            name = add(doc)
            try:
                Gui.getMainWindow().statusBar().showMessage("%s added and active" % name, 4000)
            except Exception as _fw_err:
                _fw_log("displaystates.py:335", _fw_err)
            win = _OPEN.get("win")
            if win is not None and win.isVisible():
                win.fill()
        QtCore.QTimer.singleShot(0, run)


# ---------------------------------------------------------------------- Undo / Redo
# The display states and what configurations keep by name (parent, marks, display data) live in doc.Meta, which
# FreeCAD's Undo does not touch, while the configuration names live in the table sheet, which it does. So Undo of a
# rename gave Long its name back with Tall's states, and Undo of a delete brought the configuration back with none.
# Each step of the document's Undo list keeps what these keys were when it started; Undo puts that back, Redo the after.
_UNDO_PREFIXES = (KEY, "CfgProp:", "CustomPropertyUnit:", "SWDisplayStateOf", "FreeWorks:Cfg", "SWMassOverride")


def _undo_keys(doc):
    return {k: v for k, v in dict(doc.Meta or {}).items() if k.startswith(_UNDO_PREFIXES)}


def _put_keys(doc, keys):
    meta = dict(doc.Meta or {})
    if {k: v for k, v in meta.items() if k.startswith(_UNDO_PREFIXES)} == keys:
        return False
    meta = {k: v for k, v in meta.items() if not k.startswith(_UNDO_PREFIXES)}
    meta.update(keys)
    doc.Meta = meta
    return True


class _MetaUndo:
    """Keeps doc.Meta's configuration and display-state keys in step with the document's Undo list."""
    LIMIT = 200

    def __init__(self):
        self.docs = {}              # doc name -> {"open": keys or None, "undo": [keys before], "redo": [keys after]}

    def _of(self, doc):
        return self.docs.setdefault(doc.Name, {"open": None, "undo": [], "redo": []})

    def slotOpenTransaction(self, doc, _name):
        try:
            self._of(doc)["open"] = _undo_keys(doc)
        except Exception as _fw_err:
            _fw_log("displaystates.py:undo-open", _fw_err)

    def slotCommitTransaction(self, doc):
        try:
            st = self._of(doc)
            if st["open"] is None:
                return
            st["undo"].append(st["open"])
            del st["undo"][:-self.LIMIT]
            st["redo"], st["open"] = [], None
        except Exception as _fw_err:
            _fw_log("displaystates.py:undo-commit", _fw_err)

    def slotAbortTransaction(self, doc):
        self._of(doc)["open"] = None

    def _step(self, doc, back):
        st = self._of(doc)
        take, give = (st["undo"], st["redo"]) if back else (st["redo"], st["undo"])
        if not take:
            return
        give.append(_undo_keys(doc))
        if _put_keys(doc, take.pop()):
            QtCore.QTimer.singleShot(0, refresh_panes)

    def slotUndoDocument(self, doc):
        try:
            self._step(doc, True)
        except Exception as _fw_err:
            _fw_log("displaystates.py:undo", _fw_err)

    def slotRedoDocument(self, doc):
        try:
            self._step(doc, False)
        except Exception as _fw_err:
            _fw_log("displaystates.py:redo", _fw_err)

    def slotDeletedDocument(self, doc):
        self.docs.pop(doc.Name, None)


_META_UNDO = []


def register():
    if not _META_UNDO:
        _META_UNDO.append(_MetaUndo())
        App.addDocumentObserver(_META_UNDO[0])
    if "SWStyle_ChangeDisplayStates" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ChangeDisplayStates", _Window())
    if "SWStyle_AddDisplayState" not in Gui.listCommands():
        Gui.addCommand("SWStyle_AddDisplayState", _Add())
