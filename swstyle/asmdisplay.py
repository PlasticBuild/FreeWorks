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
from PySide import QtCore, QtWidgets

from . import asmcore as ac

LINK_KEY = "SWDisplayStatesLinked"
PER_CONFIG = "SWDisplayStateOf"


def _is_comp(obj):
    try:
        return obj is not None and obj.TypeId in ("App::Link", "Assembly::AssemblyLink")
    except ReferenceError:
        return False


def _source_vo(comp):
    try:
        return comp.LinkedObject.ViewObject
    except Exception:
        return None


def _asm_comps(obj):
    try:
        if obj.TypeId == "Assembly::AssemblyObject":
            return ac.components(obj)
    except Exception as _fw_err:
        _fw_log("asmdisplay.py:56", _fw_err)
    return None


# ---------------------------------------------------------------- Display Pane
def install_pane():
    from . import displaypane as dp
    if getattr(dp, "_fw_asm", False):
        return
    dp._fw_asm = True
    cells0, shown0, mode0, transparent0, colour0 = dp.cells, dp.shown, dp.mode, dp.transparent, dp.colour
    hide0, setmode0, trans0, edit0 = dp.toggle_hide, dp.set_mode, dp.toggle_transparency, dp.edit_appearance

    def cells(view, node):
        fm = view.fm
        if node is not None and not node.link:
            obj = node.obj
            if node is fm.part and _asm_comps(obj) is not None:
                return {"mode": (obj, None), "appearance": (obj, "part"), "transparency": (obj, None)}
            if _is_comp(obj):
                if obj.TypeId == "Assembly::AssemblyLink":
                    return {"hide": (obj, None)}        # a subassembly: its parts have the rest
                return {"hide": (obj, None), "mode": (obj, None), "appearance": (obj, "component"),
                        "transparency": (obj, None)}
        return cells0(view, node)

    def mode(obj):
        comps = _asm_comps(obj)
        if comps is not None:
            return mode(comps[0]) if comps else ""
        if _is_comp(obj):
            from . import compmode
            if compmode.is_component(obj):
                return compmode.drawn(obj)
            vo = _source_vo(obj)
            return vo.DisplayMode if vo is not None and hasattr(vo, "DisplayMode") else ""
        return mode0(obj)

    def set_mode(obj, freecad_mode):
        comps = _asm_comps(obj)
        if comps is not None:
            for c in comps:
                set_mode(c, freecad_mode)
            return
        if _is_comp(obj):
            from . import compmode
            if compmode.is_component(obj):
                # this instance only, kept in the assembly (the part's file stays as it is)
                compmode.set_mode(obj, freecad_mode)
                return
            vo = _source_vo(obj)
            if vo is None:
                return
            m = freecad_mode or "Flat Lines"
            if m in vo.listDisplayModes():
                vo.DisplayMode = m
            return
        setmode0(obj, freecad_mode)

    def transparent(obj):
        from . import asmmenu
        comps = _asm_comps(obj)
        if comps is not None:
            return bool(comps) and all(asmmenu.transparent(c) for c in comps)
        if _is_comp(obj):
            return asmmenu.transparent(obj)
        return transparent0(obj)

    def toggle_transparency(obj):
        from . import asmmenu
        comps = _asm_comps(obj)
        if comps is not None:
            want = not transparent(obj)
            for c in comps:
                if asmmenu.transparent(c) != want:
                    asmmenu.change_transparency(c)
            return
        if _is_comp(obj):
            asmmenu.change_transparency(obj)
            return
        trans0(obj)

    def colour(obj, level):
        comps = _asm_comps(obj)
        if comps is not None:
            return colour(comps[0], level) if comps else None
        if _is_comp(obj):
            vo = obj.ViewObject
            try:
                if vo.OverrideMaterial:
                    m = vo.ShapeMaterial
                    return tuple(m.DiffuseColor[:3]) + (m.Transparency,)
            except Exception as _fw_err:
                _fw_log("asmdisplay.py:141", _fw_err)
            src = getattr(obj, "LinkedObject", None)
            return colour0(src, "part") if src is not None else None
        return colour0(obj, level)

    def edit_appearance(obj, level):
        if _is_comp(obj) or _asm_comps(obj) is not None:
            from . import asmappearance
            comps = _asm_comps(obj)
            asm = obj if comps is not None else ac.assembly_of(obj.Document)
            if asm is None:
                return False
            asmappearance.open_component_page(asm, comps if comps is not None else [obj])
            return True
        return edit0(obj, level)

    dp.cells, dp.mode, dp.set_mode, dp.transparent = cells, mode, set_mode, transparent
    dp.toggle_transparency, dp.colour, dp.edit_appearance = toggle_transparency, colour, edit_appearance


# ---------------------------------------------------------------- display states
def _rgbt(m):
    return list(m.DiffuseColor[:3]) + [float(m.Transparency)]


def install_states():
    from . import displaystates as ds
    if getattr(ds, "_fw_asm", False):
        return
    ds._fw_asm = True
    capture0, restore0, init0 = ds.capture, ds.restore, ds.DisplayStatesWindow.__init__

    def capture(doc):
        from . import asmmenu, compmode
        out = capture0(doc)
        for obj in doc.Objects:
            if not _is_comp(obj) or obj.ViewObject is None:
                continue
            vo = obj.ViewObject
            item = out.setdefault(obj.Name, {"v": bool(vo.Visibility)})
            item.pop("m", None)
            src = _source_vo(obj)
            if not hasattr(vo, "OverrideMaterial"):
                continue                # a subassembly: its parts carry their own looks
            item["c"] = {"o": bool(vo.OverrideMaterial), "mat": _rgbt(vo.ShapeMaterial),
                         "t": bool(asmmenu.transparent(obj)),
                         "m": compmode.get(obj), "i": 1,
                         # the component's own appearance as kept (asmappearance): without it a state
                         # with no colour kept the last one's, which came back on reopening the file
                         "a": getattr(obj, "FwAppearance", "") or ""}
        return out

    def restore(doc, look):
        from . import asmmenu, compmode
        restore0(doc, {k: v for k, v in look.items() if "c" not in v})
        for name, item in look.items():
            c = item.get("c")
            obj = doc.getObject(name)
            if c is None or obj is None or obj.ViewObject is None:
                continue
            vo = obj.ViewObject
            if "a" in c and (getattr(obj, "FwAppearance", "") or "") != c["a"]:
                try:
                    if "FwAppearance" not in obj.PropertiesList:
                        obj.addProperty("App::PropertyString", "FwAppearance", "FreeCAD",
                                        "Component appearance (this assembly only)")
                        obj.setPropertyStatus("FwAppearance", "Hidden")
                    obj.FwAppearance = c["a"]        # the material itself is put back just below
                except Exception as _fw_err:
                    _fw_log("asmdisplay.py:state-appearance", _fw_err)
            if bool(asmmenu.transparent(obj)) != c["t"]:
                asmmenu.change_transparency(obj)
            if c["o"]:
                m = App.Material()
                m.DiffuseColor = tuple(c["mat"][:3])
                m.Transparency = c["mat"][3]
                vo.ShapeMaterial = m
            if bool(vo.OverrideMaterial) != c["o"]:
                vo.OverrideMaterial = c["o"]
            if c.get("i") or c.get("m"):
                # per instance (states saved before kept the part's mode: brought back per instance)
                if compmode.get(obj) != (c.get("m") or ""):
                    compmode.set_mode(obj, c.get("m") or "")
            if bool(vo.Visibility) != item["v"]:
                vo.Visibility = item["v"]

    def init(self):
        init0(self)
        doc = App.ActiveDocument
        box = QtWidgets.QCheckBox("Link Display States to configurations", self)
        box.setObjectName("SWDisplayStatesLinked")
        box.setChecked(linked(doc) if doc is not None else True)
        box.toggled.connect(lambda on: App.ActiveDocument and set_linked(App.ActiveDocument, on))
        self.layout().insertWidget(1, box)
        self.linked_box = box
        if doc is not None and ac.assembly_of(doc) is not None:
            table = QtWidgets.QPushButton("Display State Table...", self)
            table.setObjectName("SWDisplayStateTableButton")
            table.setToolTip("Every component's hide/show in every display state, in one table")
            table.clicked.connect(lambda: open_table(App.ActiveDocument))
            self.layout().insertWidget(2, table)

    ds.capture, ds.restore = capture, restore
    ds.DisplayStatesWindow.__init__ = init


def linked(doc):
    ""
    try:
        return doc.Meta.get(LINK_KEY, "1") != "0"
    except Exception:
        return True


def set_linked(doc, on):
    meta = dict(doc.Meta)
    meta[LINK_KEY] = "1" if on else "0"
    doc.Meta = meta


def state_of(doc, config):
    import json
    try:
        return json.loads(doc.Meta.get(PER_CONFIG, "") or "{}").get(config)
    except Exception:
        return None


def _set_state_of(doc, config, state):
    import json
    try:
        d = json.loads(doc.Meta.get(PER_CONFIG, "") or "{}")
    except Exception:
        d = {}
    d[config] = state
    meta = dict(doc.Meta)
    meta[PER_CONFIG] = json.dumps(d)
    doc.Meta = meta


def _new_name(doc, config):
    ""

    from . import displaystates as ds
    try:
        is_asm = any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)
        make = getattr(ds, "default_name", None)
        if not is_asm and make is not None:
            return make(doc, 1, config)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: display state name: %s\n" % error)
    return "%s Display State-1" % config


def leave_configuration(doc, old):
    """Before Show Configuration: the look now is kept as the old configuration's display state."""
    from . import displaystates as ds
    if not linked(doc) or not old:
        return
    name = state_of(doc, old) or _new_name(doc, old)
    data = ds._data(doc)
    data.setdefault("order", [])
    data.setdefault("states", {})
    if name not in data["states"]:
        data["order"].append(name)
    data["states"][name] = ds.capture(doc)
    data["active"] = None               # so activating the next one keeps this capture
    ds._save(doc, data)
    _set_state_of(doc, old, name)


def enter_configuration(doc, new):
    """After Show Configuration: its display state put back, or made from the look now."""
    from . import displaystates as ds
    if not linked(doc):
        return None
    name = state_of(doc, new) or _new_name(doc, new)
    if name in ds.names(doc):
        ds.activate(doc, name)
    else:
        ds.add(doc, name)
    _set_state_of(doc, new, name)
    try:
        from . import asmconfigure
        if asmconfigure.apply_hide(doc):        # Configure Component's Hide column wins
            data = ds._data(doc)
            data["states"][name] = ds.capture(doc)
            ds._save(doc, data)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: display state hide: %s\n" % error)
    return name


def install_configs():
    from . import configmanager as cm
    if getattr(cm, "_fw_asmdisplay", False):
        return
    cm._fw_asmdisplay = True
    show0 = cm.show

    def show(t, name, *more, **named):
        doc = t.sheet.Document
        old = t.active()

        asm = old != name
        if asm:
            try:
                leave_configuration(doc, old)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: display states: %s\n" % error)
        ok = show0(t, name, *more, **named)
        if ok and asm:
            try:
                enter_configuration(doc, name)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: display states: %s\n" % error)
        return ok
    cm.show = show
    add0 = cm.add

    def add(t, name, *more, **named):
        """Add Configuration switches to the new one: the display states follow as for Show."""
        doc = t.sheet.Document
        old = t.active()
        asm = True                  # parts and assemblies alike
        if asm:
            try:
                leave_configuration(doc, old)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: display states: %s\n" % error)
        ok = add0(t, name, *more, **named)
        if asm:
            try:
                now = t.active()
                if now != old:
                    enter_configuration(doc, now)
                elif linked(doc):
                    st = state_of(doc, old)
                    from . import displaystates as ds
                    if st in ds.names(doc):
                        ds.activate(doc, st)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: display states: %s\n" % error)
        return ok
    cm.add = add


# ----------------------------------------------------------------------------- Display State table
class DisplayStateTable(QtWidgets.QDialog):
    ""




    def __init__(self, doc):
        super().__init__(Gui.getMainWindow())
        from . import displaystates as ds
        self.doc = doc
        self.asm = ac.assembly_of(doc)
        self.setObjectName("SWDisplayStateTable")
        self.setWindowTitle("Display State Table - %s" % doc.Label)
        lay = QtWidgets.QVBoxLayout(self)
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("SWDisplayStateTableNote")
        self.note.setWordWrap(True)
        if not ds.names(doc):
            ds.add(doc)
        self.before_data = ds._data(doc)
        self.before_vis = {c.Name: bool(c.ViewObject.Visibility) for c in self.comps() if c.ViewObject is not None}
        self.states = ds.names(doc)
        self.comps_ = self.comps()
        self.table = QtWidgets.QTableWidget(len(self.comps_), len(self.states))
        self.table.setObjectName("SWDisplayStateTableGrid")
        self.table.setHorizontalHeaderLabels(self.states)
        self.table.setVerticalHeaderLabels([c.Label for c in self.comps_])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)     # 2026: columns resize
        hh.setDefaultSectionSize(140)
        self.table.setWordWrap(True)
        on = ds.active(doc)
        data = ds._data(doc)
        self._filling = True
        for r, comp in enumerate(self.comps_):
            for k, name in enumerate(self.states):
                if name == on:
                    shown = bool(comp.ViewObject.Visibility)
                else:
                    shown = bool(data.get("states", {}).get(name, {}).get(comp.Name, {}).get("v", True))
                item = QtWidgets.QTableWidgetItem("Show" if shown else "Hide")
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if shown else QtCore.Qt.Unchecked)
                self.table.setItem(r, k, item)
        for k, name in enumerate(self.states):
            if name == on:
                h = self.table.horizontalHeaderItem(k)
                f = h.font()
                f.setBold(True)
                h.setFont(f)
                h.setToolTip("The active display state")
        self._filling = False
        self.table.itemChanged.connect(self._changed)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.note)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(min(900, 220 + 140 * len(self.states)), min(700, 140 + 26 * len(self.comps_)))

    def comps(self):
        return [c for c in ac.components(self.asm)] if self.asm is not None else []

    def _changed(self, item):
        if self._filling:
            return
        shown = item.checkState() == QtCore.Qt.Checked
        self._filling = True
        item.setText("Show" if shown else "Hide")
        self._filling = False
        self.set_cell(item.row(), item.column(), shown)

    def set_cell(self, row, col, shown):
        """A component's Hide/Show in one display state (the active one shows at once)."""
        from . import displaystates as ds
        comp, name = self.comps_[row], self.states[col]
        if name == ds.active(self.doc):
            if comp.ViewObject is not None and bool(comp.ViewObject.Visibility) != shown:
                comp.ViewObject.Visibility = shown
        else:
            data = ds._data(self.doc)
            look = data.setdefault("states", {}).setdefault(name, {})
            look.setdefault(comp.Name, {})["v"] = bool(shown)
            ds._save(self.doc, data)
        item = self.table.item(row, col)
        if item is not None and (item.checkState() == QtCore.Qt.Checked) != shown:
            self._filling = True
            item.setCheckState(QtCore.Qt.Checked if shown else QtCore.Qt.Unchecked)
            item.setText("Show" if shown else "Hide")
            self._filling = False

    def reject(self):
        from . import displaystates as ds
        ds._save(self.doc, self.before_data)
        for c in self.comps_:
            want = self.before_vis.get(c.Name)
            if want is not None and c.ViewObject is not None and bool(c.ViewObject.Visibility) != want:
                c.ViewObject.Visibility = want
        _TABLE.pop("win", None)
        super().reject()

    def accept(self):
        from . import displaystates as ds
        data = ds._data(self.doc)
        on = data.get("active")
        if on in data.get("states", {}):
            data["states"][on] = ds.capture(self.doc)      # the active state keeps what the table set
            ds._save(self.doc, data)
        _TABLE.pop("win", None)
        super().accept()


_TABLE = {}


def open_table(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None or ac.assembly_of(doc) is None:
        return None
    win = DisplayStateTable(doc)
    _TABLE["win"] = win
    win.show()
    win.raise_()
    return win


def _install_compmode():
    from . import compmode
    compmode.install()


def install():
    for f in (install_pane, install_states, install_configs, _install_compmode):
        try:
            f()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly display: %s\n" % error)
