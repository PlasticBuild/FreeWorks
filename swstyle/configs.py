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

import re

import FreeCAD as App

from . import configmanager as cm

SUPPRESS = "Suppress_"
COMP = "Comp_"
DESCRIPTION = "Description"
PART_NUMBER = "PartNumber"
BOM_MODE = "BomName"            # "Document Name", "Configuration Name" or "User Specified"
SUPPRESS_NEW = "SuppressNew"
BOM_MODES = ("Document Name", "Configuration Name", "Link to Parent Configuration", "User Specified")
PARENT_MODE = "Link to Parent Configuration"     # derived configurations only
TEXT_COLUMNS = (DESCRIPTION, PART_NUMBER, BOM_MODE)


def _safe(text):
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def table(doc, create=True):
    t = cm.table(doc)
    if t is None and create:
        t = cm.insert_table(doc, "Default")
    return t


# ----------------------------------------------------------------------------- columns
def column_of(t, alias):
    for c in t.columns():
        try:
            if t.sheet.getAlias("%s1" % c) == alias:
                return c
        except Exception as _fw_err:
            _fw_log("configs.py:67", _fw_err)
    return None


def _free_column(t):
    cols = t.columns()
    return cm._col(cm._colnum(cols[-1]) + 1) if cols else cm._col(cm._colnum(t.col) + 1)


def ensure_column(t, alias, value):
    """The column for alias, made with value in every configuration's row when missing."""
    c = column_of(t, alias)
    if c is not None:
        return c
    sheet = t.sheet
    c = _free_column(t)
    sheet.set("%s%d" % (c, t.first - 1), str(value))
    sheet.setAlias("%s%d" % (c, t.first - 1), alias)
    for r in range(t.first, t.last + 1):
        sheet.set("%s%d" % (c, r), str(value))
    sheet.Document.recompute()
    cm._bind(t)
    sheet.Document.recompute()
    return c


def cell_value(t, alias, name=None):
    c = column_of(t, alias)
    row = t.row_of(name or t.active())
    if c is None or row is None:
        return None
    return t._text("%s%d" % (c, row))


def set_cell(t, alias, value, names):
    """value in each named configuration's row of alias's column."""
    c = column_of(t, alias)
    changed = []
    for name in names:
        row = t.row_of(name)
        if row is not None:
            old = str(t.sheet.getContents("%s%d" % (c, row)))
            t.sheet.set("%s%d" % (c, row), str(value))
            changed.append((name, old))
    t.sheet.Document.recompute()
    for name, old in changed:          # derived configurations follow their parent (configmanager)
        try:
            cm.follow_parent(t, name, c, old, str(value))
        except Exception as _fw_err:
            _fw_log("configs.py:116", _fw_err)
    cm._bind(t)


def _scope(t, scope):
    """"this" -> the active configuration, "all" -> every one, a list -> those."""
    if scope == "all":
        return t.names()
    if scope == "this" or scope is None:
        return [t.active()]
    return list(scope)


# ----------------------------------------------------------------------------- one undo step
def _in_step(doc):
    ""



    try:
        if getattr(doc, "HasPendingTransaction", False):
            return True
    except Exception:
        pass
    try:
        return bool(App.getActiveTransaction())
    except Exception:
        return False


def _open(doc, name):
    """Open a step unless one is open already; True when this call opened it (and commits it)."""
    if _in_step(doc):
        return False
    doc.openTransaction(name)
    return True


def _close(doc, opened):
    if opened:
        doc.commitTransaction()


# ----------------------------------------------------------------------------- suppress per configuration
def is_suppressed(obj):
    return bool(getattr(obj, "Suppressed", False))


def set_suppressed(obj, on, scope="this"):
    ""

    doc = obj.Document
    t = table(doc)
    alias = SUPPRESS + _safe(obj.Name)
    names = _scope(t, scope)
    opened = _open(doc, "Suppress" if on else "Unsuppress")
    try:
        ensure_column(t, alias, "1" if is_suppressed(obj) else "0")
        set_cell(t, alias, "1" if on else "0", names)
        obj.setExpression("Suppressed", "%s.%s == 1" % (t.sheet.Name, alias))
        doc.recompute()
    finally:
        _close(doc, opened)
    cm.refresh_all()
    return t


def suppressed_in(obj, name):
    t = cm.table(obj.Document)
    if t is None:
        return is_suppressed(obj)
    v = cell_value(t, SUPPRESS + _safe(obj.Name), name)
    return is_suppressed(obj) if v is None else v.strip() in ("1", "1.0", "True")


# ----------------------------------------------------------------------------- values per configuration
def _alias_for(obj, prop):
    return _safe("%s_%s" % (obj.Name, prop.replace("Constraints.", "")))


def _number(value):
    """A plain number (mm, deg) from a float, a Quantity ("35 mm", "30 deg") or a text."""
    if isinstance(value, str):
        try:
            value = App.Units.Quantity(value)
        except Exception:
            return value
    try:
        return float(getattr(value, "Value", value))
    except (TypeError, ValueError):
        return value


def configured(obj, prop):
    """The property follows the table (it was set This configuration once)."""
    t = cm.table(obj.Document)
    return t is not None and column_of(t, _alias_for(obj, prop)) is not None


def set_value(obj, prop, value, scope="all", old=None):
    ""



    doc = obj.Document
    t = cm.table(doc)
    alias = _alias_for(obj, prop)
    if scope == "all" and (t is None or column_of(t, alias) is None):
        _plain_set(obj, prop, value)
        doc.recompute()
        return None
    t = t or table(doc)
    try:
        from . import dtoptions
        allowed = dtoptions.allow_edit(doc, column_of(t, alias) is None)
    except ImportError:
        allowed = "table"
    if allowed != "table":
        # Edit Control blocks it (the value goes back), or Options > New parameters is off (the
        # model changes, the table does not)
        if allowed == "model":
            _plain_set(obj, prop, value)
        elif old is not None:
            _plain_set(obj, prop, old)
        doc.recompute()
        return None
    names = _scope(t, scope)
    opened = _open(doc, "Modify")
    try:
        # the value before the edit: the Modify box may have set the datum already (old says what
        # it was); the configurations not chosen keep it
        before = _number(old) if old is not None else _number(_current(obj, prop))
        ensure_column(t, alias, before)
        set_cell(t, alias, _number(value), names)
        obj.setExpression(prop if prop.startswith("Constraints.") else prop, "%s.%s" % (t.sheet.Name, alias))
        doc.recompute()
    finally:
        _close(doc, opened)
    cm.refresh_all()
    return t


def _current(obj, prop):
    if prop.startswith("Constraints."):
        name = prop.split(".", 1)[1]
        for c in obj.Constraints:
            if c.Name == name:
                return c.Value
        return 0.0
    return getattr(obj, prop)


def _plain_set(obj, prop, value):
    if prop.startswith("Constraints."):
        obj.setDatum(prop.split(".", 1)[1], App.Units.Quantity(value) if isinstance(value, str) else value)
    else:
        setattr(obj, prop, value)


def value_in(obj, prop, name):
    t = cm.table(obj.Document)
    v = cell_value(t, _alias_for(obj, prop), name) if t is not None else None
    return _number(_current(obj, prop)) if v is None else _number(v)


# ----------------------------------------------------------------------------- Configuration Properties
def properties(doc, name):
    t = cm.table(doc)
    out = {"name": name, "description": "", "part_number": "", "bom": "Document Name", "suppress_new": False}
    if t is None:
        return out
    out["description"] = cell_value(t, DESCRIPTION, name) or ""
    out["part_number"] = cell_value(t, PART_NUMBER, name) or ""
    out["bom"] = cell_value(t, BOM_MODE, name) or "Document Name"
    out["suppress_new"] = (cell_value(t, SUPPRESS_NEW, name) or "0").strip() in ("1", "1.0")
    return out


def bom_name(doc, name=None):
    """The part number the bill of materials shows for the configuration."""
    t = cm.table(doc)
    name = name or (t.active() if t else "Default")
    p = properties(doc, name)
    if p["bom"] == "Configuration Name":
        return name
    if p["bom"] == "User Specified" and p["part_number"]:
        return p["part_number"]
    if p["bom"] == PARENT_MODE:
        parent = cm.parent_of(doc, name)
        if parent and parent != name:
            return bom_name(doc, parent)
    return doc.Label


def rename(t, old, new):
    new = (new or "").strip()
    if not new or new == old or new in t.names():
        return False
    row = t.row_of(old)
    if row is None:
        return False
    active = t.active()
    sheet, doc = t.sheet, t.sheet.Document
    sheet.set("%s%d" % (t.col, row), new)
    cm._settle(sheet)
    cm._bind(t)
    setattr(sheet, t.prop, new if active == old else active)
    doc.recompute()
    if old in cm.outside_table(doc):
        cm.set_outside_table(doc, old, False)
        cm.set_outside_table(doc, new, True)
    _rename_meta(doc, old, new)
    try:
        from . import displaystates        # its display states go with it, <Long>_Display State 1 renamed too
        displaystates.config_renamed(doc, old, new)
    except Exception as _fw_err:
        _fw_log("configs.py:rename-states", _fw_err)
    return True


def _rename_meta(doc, old, new):
    ""

    meta = dict(doc.Meta or {})
    keys = (cm.PARENT, cm.MARK, cm.DISPLAY_MARK, "FreeWorks:CfgDisplayData:", "FreeWorks:CfgMass:",
            "SWMassOverride@") + tuple(cm.EXTRAS.values())
    for key in keys:            # fp96: its comment, Use in BOM and colour too
        if key + old in meta:
            meta[key + new] = meta.pop(key + old)
    for k in [k for k, v in meta.items() if k.startswith(cm.PARENT) and v == old]:
        meta[k] = new
    doc.Meta = meta
    try:
        from . import fileprops         # fp96: File > Properties > Configuration Properties go with it
        fileprops.config_renamed(doc, old, new)
    except Exception as _fw_err:
        _fw_log("configs.py:rename-props", _fw_err)


def set_properties(doc, name, description=None, part_number=None, bom=None, suppress_new=None, new_name=None):
    """Configuration Properties: name, description, bill of materials part number, Suppress new
    features and mates."""
    t = table(doc)
    if bom == "User Specified Name":        # the label the Properties page shows for "User Specified"
        bom = "User Specified"
    doc.openTransaction("Configuration Properties")
    try:
        for alias, value, blank in ((DESCRIPTION, description, ""), (PART_NUMBER, part_number, ""),
                                    (BOM_MODE, bom, "Document Name"),
                                    (SUPPRESS_NEW, None if suppress_new is None else ("1" if suppress_new else "0"), "0")):
            if value is None:
                continue
            ensure_column(t, alias, blank)
            set_cell(t, alias, value, [name])
        if new_name:
            rename(t, name, new_name)
    finally:
        doc.commitTransaction()
    cm.refresh_all()
    return t


def suppress_new_in(doc):
    """The configurations that have "Suppress new features and mates" on (not the active one)."""
    t = cm.table(doc)
    if t is None or column_of(t, SUPPRESS_NEW) is None:
        return []
    return [n for n in t.names() if n != t.active() and (cell_value(t, SUPPRESS_NEW, n) or "").strip() in ("1", "1.0")]


def new_feature(obj, names=None):
    """A feature was added: suppressed in the configurations that suppress new features (names: those
    configurations as they were when the feature was made)."""
    names = suppress_new_in(obj.Document) if names is None else names
    if not names or not hasattr(obj, "Suppressed"):
        return False
    t = cm.table(obj.Document)
    alias = SUPPRESS + _safe(obj.Name)
    ensure_column(t, alias, "0")
    set_cell(t, alias, "1", names)
    obj.setExpression("Suppressed", "%s.%s == 1" % (t.sheet.Name, alias))
    return True


# ----------------------------------------------------------------------------- assemblies
def _assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc)
    except Exception as _fw_err:
        _fw_log("configs.py:349", _fw_err)
        return None


def suppress_component(comp, on, scope="this"):
    """An assembly component suppressed in This / All / the named configurations."""
    from . import asmcomp
    doc = comp.Document
    t = table(doc)
    alias = COMP + _safe(comp.Name)
    names = _scope(t, scope)
    ensure_column(t, alias, "1" if asmcomp.is_suppressed(comp) else "0")
    set_cell(t, alias, "1" if on else "0", names)
    apply_assembly(doc)
    cm.refresh_all()
    return t


def apply_assembly(doc):
    """After Show Configuration: each component suppressed or resolved as its configuration says."""
    asm = _assembly(doc)
    t = cm.table(doc)
    if asm is None or t is None:
        return 0
    from . import asmcomp, asmcore
    n = 0
    for comp in asmcore.components(asm):
        v = cell_value(t, COMP + _safe(comp.Name))
        if v is None:
            continue
        want = v.strip() in ("1", "1.0")
        if asmcomp.is_suppressed(comp) != want:
            asmcomp.suppress(comp, want)
            n += 1
    return n


def add_configuration_to_part(comp, name):
    """Component right-click > Add Configuration...: the component's part gets the configuration."""
    from . import asmmenu
    doc = asmmenu.part_document(comp)
    if doc is None:
        return None
    t = cm.table(doc)
    if t is None:
        t = cm.insert_table(doc, "Default")
    if not cm.add(t, name):
        return None
    return t


# ----------------------------------------------------------------------------- hooks
def install():
    """Show Configuration also applies the assembly's component states; new features follow
    Suppress new features."""
    if getattr(cm, "_fw_configs", False):
        return
    old_show = cm.show

    def show(t, name, *more, **named):
        ok = old_show(t, name, *more, **named)
        if ok:
            try:
                apply_assembly(t.sheet.Document)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: configuration: %s\n" % error)
        return ok

    cm.show = show
    App.addDocumentObserver(_NewFeatures())
    try:
        _patch_fmmenu()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: configurations menu: %s\n" % error)
    try:
        from . import configtable      # Modify Configurations one for one (Configure Feature/Dimension/Equation/Material)
        configtable.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Modify Configurations: %s\n" % error)
    cm._fw_configs = True


def several(doc):
    t = cm.table(doc) if doc is not None else None
    return t is not None and len(t.names()) > 1


def _patch_fmmenu():
    """Suppress / Unsuppress of a feature: the active configuration when the part has a table
    (FreeCAD's plain Suppressed would be overwritten by the next configuration change), and the
    This Configuration / All Configurations / Specify Configurations choice when it has several."""
    from . import fmmenu
    old_set = fmmenu.set_suppressed

    def set_suppressed(obj, on, *more, **named):
        if "Suppressed" in obj.PropertiesList and cm.table(obj.Document) is not None:
            set_suppressed_cfg(obj, on, "this")
            return True
        return old_set(obj, on, *more, **named)

    fmmenu.set_suppressed = set_suppressed
    old_entries = fmmenu.entries

    def entries(shell, target, view=None, *more, **named):
        items = old_entries(shell, target, view, *more, **named)
        doc = getattr(target, "Document", None)
        if not several(doc) or "Suppressed" not in getattr(target, "PropertiesList", []):
            return items
        out = []
        for item in items:
            if item[0] == "Suppress":
                on = not is_suppressed(target)
                out.append((item[0], item[1], fmmenu.Sub(lambda m, t=target, on=on: scope_menu(m, t, on)), True))
            else:
                out.append(item)
        return out

    fmmenu.entries = entries



    old_row = getattr(fmmenu, "_tree_row", None)
    if old_row is not None:
        def _tree_row(shell, target, kind, row_entries, *more, **named):
            out = old_row(shell, target, kind, row_entries, *more, **named)
            doc = getattr(target, "Document", None)
            if not several(doc) or "Suppressed" not in getattr(target, "PropertiesList", []):
                return out
            on = not is_suppressed(target)
            for e in out:
                if e.key == "Suppress":
                    e.run = lambda t=target, on=on: scope_popup(t, on)
            return out
        fmmenu._tree_row = _tree_row


def scope_popup(obj, on, pos=None):
    """The row's Suppress with several configurations: the scope menu under the pointer."""
    from PySide import QtGui, QtWidgets
    import FreeCADGui as Gui
    menu = QtWidgets.QMenu(Gui.getMainWindow() if App.GuiUp else None)
    menu.setObjectName("SWConfigScopeMenu")
    scope_menu(menu, obj, on)
    menu.popup(pos or QtGui.QCursor.pos())
    return menu


set_suppressed_cfg = set_suppressed


def scope_menu(menu, obj, on):
    """This Configuration / All Configurations / Specify Configurations..."""
    for text, scope in (("This Configuration", "this"), ("All Configurations", "all")):
        a = menu.addAction(text)
        a.setObjectName("SWConfigScope_%s" % scope)
        a.triggered.connect(lambda _c=False, s=scope: set_suppressed_cfg(obj, on, s))
    a = menu.addAction("Specify Configurations...")
    a.setObjectName("SWConfigScope_specify")
    a.triggered.connect(lambda _c=False: specify(obj.Document, lambda names: set_suppressed_cfg(obj, on, names)))


def specify(doc, run, parent=None):
    """Specify Configurations: tick the configurations; OK runs run(names)."""
    from PySide import QtWidgets
    import FreeCADGui as Gui
    t = cm.table(doc)
    box = QtWidgets.QDialog(parent or Gui.getMainWindow())
    box.setObjectName("SWSpecifyConfigurations")
    box.setWindowTitle("Specify Configurations")
    lay = QtWidgets.QVBoxLayout(box)
    lst = QtWidgets.QListWidget()
    lst.setObjectName("SWSpecifyList")
    for n in t.names() if t else []:
        it = QtWidgets.QListWidgetItem(n)
        it.setFlags(it.flags() | QtCore_ItemIsUserCheckable())
        from PySide import QtCore
        it.setCheckState(QtCore.Qt.Checked if n == t.active() else QtCore.Qt.Unchecked)
        lst.addItem(it)
    lay.addWidget(lst)
    bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
    bb.accepted.connect(box.accept)
    bb.rejected.connect(box.reject)
    lay.addWidget(bb)
    box.list = lst

    def done(result):
        if result:
            from PySide import QtCore
            names = [lst.item(i).text() for i in range(lst.count()) if lst.item(i).checkState() == QtCore.Qt.Checked]
            if names:
                run(names)
    box.finished.connect(done)
    SPECIFY[:] = [box]
    box.open()
    return box


SPECIFY = []        # the open Specify Configurations box (checks reach it here)


def QtCore_ItemIsUserCheckable():
    from PySide import QtCore
    return QtCore.Qt.ItemIsUserCheckable


class _NewFeatures:
    def slotCreatedObject(self, obj):
        if obj.TypeId.startswith("PartDesign::") and obj.TypeId not in ("PartDesign::Body",) \
                and hasattr(obj, "Suppressed"):
            from PySide import QtCore
            # the configurations are read now: the timer may run after later changes (a script that
            # turns Suppress new features on before the event loop runs must not reach older features)
            try:
                names = suppress_new_in(obj.Document)
            except Exception:
                names = []
            if names:
                QtCore.QTimer.singleShot(0, lambda o=obj, n=names: _new_later(o, n))


def _new_later(obj, names=None):
    try:
        if obj.Document is not None:
            new_feature(obj, names)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: suppress new features: %s\n" % error)
