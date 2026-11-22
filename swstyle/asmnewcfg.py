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

from . import asmcore as ac

HIDE_NEW = "HideNewComp"
SUPPRESS_NEW_COMP = "SuppressNewComp"
_WATCH = []


def _on(t, alias, name):
    from . import configs
    v = configs.cell_value(t, alias, name) if configs.column_of(t, alias) is not None else None
    return (v or "").strip() in ("1", "1.0")


def options(doc, name):
    from . import configmanager as cm
    t = cm.table(doc)
    if t is None:
        return {"hide": False, "suppress": False}
    return {"hide": _on(t, HIDE_NEW, name), "suppress": _on(t, SUPPRESS_NEW_COMP, name)}


def set_options(doc, name, hide, suppress):
    from . import configs, configmanager as cm
    t = cm.table(doc)
    if t is None:
        return False
    for alias, on in ((HIDE_NEW, hide), (SUPPRESS_NEW_COMP, suppress)):
        if on or configs.column_of(t, alias) is not None:
            configs.ensure_column(t, alias, "0")
            configs.set_cell(t, alias, "1" if on else "0", [name])
    return True


def _others(t, alias):
    return [n for n in t.names() if n != t.active() and _on(t, alias, n)]


def new_component(comp):
    """A component was added: hidden / suppressed in the configurations that ask for it."""
    from . import configs, configmanager as cm, asmconfigure as acf
    doc = comp.Document
    t = cm.table(doc)
    if t is None:
        return False
    done = False
    hide = _others(t, HIDE_NEW)
    if hide:
        alias = acf._alias(acf.HIDE, comp)
        configs.ensure_column(t, alias, "0")
        configs.set_cell(t, alias, "1", hide)
        done = True
    sup = _others(t, SUPPRESS_NEW_COMP)
    if sup:
        alias = configs.COMP + configs._safe(comp.Name)
        configs.ensure_column(t, alias, "0")
        configs.set_cell(t, alias, "1", sup)
        done = True
    return done


def new_mate(joint):
    from . import configs, configmanager as cm, asmconfigure as acf
    t = cm.table(joint.Document)
    if t is None:
        return False
    names = configs.suppress_new_in(joint.Document)
    if not names:
        return False
    alias = acf._alias(acf.MATE_SUP, joint)
    configs.ensure_column(t, alias, "0")
    configs.set_cell(t, alias, "1", names)
    return True


def _later(doc_name, name):
    try:
        doc = App.listDocuments().get(doc_name)
        obj = doc.getObject(name) if doc is not None else None
        if obj is None:
            return
        asm = ac.assembly_of(doc)
        if asm is None:
            return
        from . import asmmenu
        if obj in ac.components(asm):
            new_component(obj)
        elif asmmenu.is_mate(obj):
            new_mate(obj)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: new component/mate in configurations: %s\n" % error)


class _Watch:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in ("App::Link", "Assembly::AssemblyLink") or obj.TypeId.startswith("Assembly::Joint") \
                    or obj.TypeId == "App::FeaturePython":
                _PENDING.append((obj.Document.Name, obj.Name))
                if len(_PENDING) == 1:      # one timer for a batch (a script inserting 300 components)
                    QtCore.QTimer.singleShot(300, _run_pending)   # after the insert / mate is set up
        except Exception as _fw_err:
            _fw_log("asmnewcfg.py:128", _fw_err)


_PENDING = []


def _run_pending():
    todo = list(_PENDING)
    del _PENDING[:]
    for d, n in todo:
        _later(d, n)


def _patch_panel():
    from . import configmanager as cm
    cls = cm.AddPanel
    if getattr(cls, "_fw_asmnew", False):
        return
    init0, accept0 = cls.__init__, cls.accept

    def __init__(self, doc, name=None, parent=None):
        init0(self, doc, name, parent)
        self.hide_new = self.suppress_new_comp = None
        try:
            if ac.assembly_of(doc) is None:
                return
            self.suppress_new.setText("Suppress new features and mates")
            box = self.suppress_new.parentWidget()
            lay = box.layout()
            o = options(doc, name) if name else {"hide": False, "suppress": False}
            self.hide_new = QtWidgets.QCheckBox("Hide new components")
            self.hide_new.setObjectName("SWConfigHideNewComponents")
            self.hide_new.setChecked(o["hide"])
            self.suppress_new_comp = QtWidgets.QCheckBox("Suppress new components")
            self.suppress_new_comp.setObjectName("SWConfigSuppressNewComponents")
            self.suppress_new_comp.setChecked(o["suppress"])
            at = lay.indexOf(self.suppress_new) + 1
            lay.insertWidget(at, self.hide_new)
            lay.insertWidget(at + 1, self.suppress_new_comp)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: assembly configuration options: %s\n" % error)

    def accept(self):
        name = self.name.text().strip() or "Default"
        ok = accept0(self)
        if ok and getattr(self, "hide_new", None) is not None:
            try:
                set_options(self.doc, name, self.hide_new.isChecked(), self.suppress_new_comp.isChecked())
            except Exception as error:
                App.Console.PrintLog("FreeCAD: assembly configuration options: %s\n" % error)
        return ok

    cls.__init__, cls.accept = __init__, accept
    cls._fw_asmnew = True


def install():
    _patch_panel()
    if not _WATCH:
        _WATCH.append(_Watch())
        App.addDocumentObserver(_WATCH[0])
