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
from PySide import QtCore, QtWidgets
from PySide.QtCore import Qt

from . import relationspm as R
from . import unitbox


def _move_before(page, group, before):
    """Put group just above before in the page's column."""
    page.column.removeWidget(group)
    page.column.insertWidget(page.column.indexOf(before), group)


class CurrentEntity(QtCore.QObject):
    """Existing Relations + Add Relations (inserted above before), and Parameters/Additional
    Parameters (added where the page is building) for the entity last drawn."""

    def __init__(self, page, before, parameters=True):
        super().__init__(page)
        self.page = page
        self.geo = None
        self._filling = False
        self.rel_group = page.group("Existing Relations")
        self.list = QtWidgets.QListWidget(self.rel_group.body)
        self.list.setObjectName("SWCurrentRelations")
        self.list.setFixedHeight(80)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.state = QtWidgets.QLabel("", self.rel_group.body)
        self.state.setObjectName("SWCurrentState")
        self.rel_group.content.addWidget(self.list)
        self.rel_group.content.addWidget(self.state)
        self.add_group = page.group("Add Relations")
        self.add_box = QtWidgets.QVBoxLayout()
        self.add_box.setSpacing(0)
        self.add_group.content.addLayout(self.add_box)
        self.buttons = []
        _move_before(page, self.rel_group, before)
        _move_before(page, self.add_group, before)
        self.params = self.more = None
        self.fields = {}
        if parameters:
            self.params = page.group("Parameters")
            self.params.setObjectName("SWGroup_CurrentParameters")
            self.more = page.group("Additional Parameters")
            self.more.setObjectName("SWGroup_CurrentAdditional")
            self.more.toggle()
        self.groups = [g for g in (self.rel_group, self.add_group, self.params, self.more) if g is not None]
        for g in self.groups:
            g.hide()

    # ------------------------------------------------------------------ state
    def sketch(self):
        return self.page.sketch

    def item(self):
        if self.geo is None:
            return None
        try:
            items = R.items_of(self.sketch(), ["Edge%d" % (self.geo + 1)])
        except Exception as _fw_err:
            _fw_log("currententity.py:item", _fw_err)
            return None
        return items[0] if items else None

    def show_for(self, geo):
        self.geo = geo
        if self.item() is None:
            self.hide()
            return False
        for g in self.groups:
            g.show()
        self.fill()
        return True

    def follow(self, geo):
        """Show (or keep up to date) the groups for geo; None hides them. Cheap when nothing changed."""
        if geo is None:
            if self.active():
                self.hide()
            return
        try:
            sk = self.sketch()
            sig = (geo, len(sk.Constraints), len(sk.Geometry), bool(sk.getConstruction(geo)))
        except Exception:
            return
        if geo != self.geo:
            self.show_for(geo)
        elif sig != getattr(self, "_sig", None):
            self.fill()
        self._sig = sig

    def hide(self):
        self.geo = None
        for g in self.groups:
            g.hide()

    def active(self):
        return self.geo is not None

    def fill(self):
        item = self.item()
        if item is None:
            self.hide()
            return
        sk = self.sketch()
        self._filling = True
        try:
            self.list.clear()
            try:
                for _, name in R.existing_relations(sk, [item], dimensions=True):
                    self.list.addItem(name)
            except Exception as _fw_err:
                _fw_log("currententity.py:list", _fw_err)
            try:
                self.state.setText(R.defined_state(sk, [item]))
            except Exception as _fw_err:
                _fw_log("currententity.py:state", _fw_err)
            keys = [k for k in R.relations_for([item])] + ["Fix"]
            keys = list(dict.fromkeys(keys))
            if [b.key for b in self.buttons] != keys:
                for b in self.buttons:
                    b.setParent(None)
                    b.deleteLater()
                self.buttons = []
                for k in keys:
                    b = R.RelationButton(k, self.add_group.body)
                    b.clicked.connect(lambda checked=False, k=k: self._add(k))
                    self.add_box.addWidget(b)
                    self.buttons.append(b)
            if self.params is not None:
                self._fill_parameters(item)
        finally:
            self._filling = False

    def _fill_parameters(self, item):
        sk = self.sketch()
        keys = R.parameter_keys(sk, [item]) or ((), ())
        want = list(keys[0]) + list(keys[1])
        if sorted(self.fields) != sorted(want):
            for box in list(self.fields.values()):
                box.parentWidget().setParent(None)
            self.fields = {}
            for group, names in ((self.params, keys[0]), (self.more, keys[1])):
                for key in names:
                    row = QtWidgets.QWidget(group.body)
                    lay = QtWidgets.QHBoxLayout(row)
                    lay.setContentsMargins(0, 0, 0, 0)
                    label = QtWidgets.QLabel(R._NAMES.get(key, key), row)
                    box = unitbox.UnitSpinBox(row)
                    box.setObjectName("SWCurrent_" + key)
                    box.setDecimals(2)
                    if key in R.ANGLES:
                        box.setRange(-360.0, 360.0)
                        box.setSuffix("°")
                    else:
                        box.setRange(-1e7, 1e7)
                        box.setSuffix(" mm")
                    box.setToolTip(R._NAMES.get(key, key))
                    box.setKeyboardTracking(False)
                    box.valueChanged.connect(lambda v, key=key: self._set(key, v))
                    lay.addWidget(label, 1)
                    lay.addWidget(box, 1)
                    group.content.addWidget(row)
                    self.fields[key] = box
        values = R.parameter_values(sk, item)
        for key, box in self.fields.items():
            if key in values and not _typing(box):
                box.blockSignals(True)
                box.setValue(values[key])
                box.blockSignals(False)

    # ------------------------------------------------------------------ edits
    def _note(self, text):
        try:
            if text:
                self.page.show_note(text, warning=True)
        except Exception as _fw_err:
            _fw_log("currententity.py:note", _fw_err)

    def _add(self, key):
        item = self.item()
        if item is None:
            return
        try:
            added, message = R.add_relation(self.sketch(), key, [item])
        except Exception as error:
            added, message = False, str(error)
        if not added:
            self._note(message)
        self.fill()

    def _set(self, key, value):
        if self._filling:
            return
        item = self.item()
        if item is None:
            return
        try:
            changed, message = R.set_parameter(self.sketch(), item, key, value)
        except Exception as error:
            changed, message = False, str(error)
        if not changed:
            self._note(message)
        box = self.fields.get(key)
        try:
            if box is not None and box.lineEdit() is not None:
                box.lineEdit().setModified(False)       # the typed value is in: refreshes show the sketch again
        except RuntimeError as _fw_err:
            _fw_log("currententity.py:typed", _fw_err)
        self.fill()

    def set_construction(self, on):
        item = self.item()
        if item is not None:
            R.set_construction(self.sketch(), [item], bool(on))

    def construction(self):
        try:
            return bool(self.sketch().getConstruction(self.geo))
        except Exception:
            return False

    def set_infinite(self, on):
        if self.geo is None:
            return
        try:
            R.set_infinite(self.sketch(), self.geo, bool(on))
        except Exception as error:
            self._note(str(error))
        self.fill()

    def infinite(self):
        try:
            return bool(R.is_infinite(self.sketch(), self.geo))
        except Exception:
            return False


def _typing(box):
    """True while the user is typing in box: the page's refresh leaves its text alone (the Line
    Properties page refreshes on every tick while the tool runs, which wiped a typed Length)."""
    try:
        edit = box.lineEdit()
        return box.hasFocus() and edit is not None and edit.isModified()
    except RuntimeError:
        return False


def last_placed(page, types):
    """The last entity the page's tool placed whose geometry type is one of types, else None."""
    try:
        from . import paramedit
        tool = paramedit._tool(page)
        sketch = page.sketch
        ids = paramedit.last_group(tool, sketch) if tool is not None else []
        for g in ids:
            if type(sketch.Geometry[g]).__name__ in types:
                return g
    except Exception as _fw_err:
        _fw_log("currententity.py:last_placed", _fw_err)
    return None
