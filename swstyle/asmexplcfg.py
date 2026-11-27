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
from PySide import QtGui, QtWidgets

from . import asmcore as ac

CFG_PROP = "FwConfiguration"


def active_config(doc):
    try:
        from . import configmanager as cm
        t = cm.table(doc)
        return (t.active() if t is not None else None) or "Default"
    except Exception:
        return "Default"


def config_of(view):
    return getattr(view, CFG_PROP, "") or active_config(view.Document)


def stamp(view):
    if not hasattr(view, CFG_PROP):
        view.addProperty("App::PropertyString", CFG_PROP, "FreeCAD", "The configuration this exploded view belongs to")
        view.setEditorMode(CFG_PROP, 2)
    setattr(view, CFG_PROP, active_config(view.Document))


def views_by_config(doc):
    from . import asmexplode as ax
    asm = ac.assembly_of(doc)
    if asm is None:
        return {}
    out = {}
    for v in ax.views(asm):
        out.setdefault(config_of(v), []).append(v)
    return out


def _show_config(view):
    ""
    name = config_of(view)
    if name == active_config(view.Document):
        return True
    try:
        from . import configmanager as cm
        t = cm.table(view.Document)
        if t is not None and name in t.names():
            cm.show(t, name)
            return True
    except Exception as _fw_err:
        _fw_log("asmexplcfg.py:75", _fw_err)
    return False


def toggle(view):
    from . import asmexplode as ax
    asm = ac.assembly_of(view.Document)
    if asm is None:
        return False
    _show_config(view)
    doc = asm.Document
    on = ax.is_exploded(view)
    doc.openTransaction("Collapse" if on else "Explode")
    try:
        (ax.collapse if on else ax.explode)(asm, view)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return True


def delete_view(view):
    """Delete an exploded view with its steps and explode line sketches (undoable)."""
    from . import asmexplode as ax, asmexplines as el
    asm = ac.assembly_of(view.Document)
    doc = view.Document
    doc.openTransaction("Delete Exploded View")
    try:
        if asm is not None and ax.is_exploded(view):
            ax.collapse(asm, view)
        for s in el.sketches(asm, view) if asm is not None else []:
            doc.removeObject(s.Name)
        for st in list(view.Group):
            doc.removeObject(st.Name)
        doc.removeObject(view.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def _remove_views(doc, asm, views):
    ""

    from . import asmexplode as ax, asmexplines as el
    doc.openTransaction("Delete Configuration")
    try:
        for view in views:
            if ax.is_exploded(view):
                ax.collapse(asm, view)
            for s in el.sketches(asm, view):
                doc.removeObject(s.Name)
            for st in list(view.Group):
                doc.removeObject(st.Name)
            doc.removeObject(view.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()


def new_exploded_view(asm):
    """Right-click a configuration > New Exploded View: the Explode PropertyManager on a new view."""
    import FreeCADGui as Gui
    from . import asmpm, asmui, asmexplode as ax
    if not asmpm.close_open():
        return False
    asmui.activate(asm)
    panel = ax.ExplodePanel(asm, None)
    asmpm._track(panel)
    Gui.Control.showDialog(panel)
    return True


def view_entries(view):
    from . import asmexpanim
    _show = [(label, run, enabled) for _k, label, run, enabled in asmexpanim.view_items(view)]
    return _show + [("Delete", lambda: delete_view(view), True)]


def step_entries(view, step):
    from . import asmexplode as ax
    return [("Edit Step", lambda: ax.edit_step(step), True), ("Delete Step", lambda: ax.delete_step(step), True)]


def lines_entries(obj):
    from . import asmexplines as el

    def delete():
        doc = obj.Document
        doc.openTransaction("Delete")
        try:
            doc.removeObject(obj.Name)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()
    return [("Edit Sketch", lambda: el.edit(obj), True), ("Delete", delete, True)]


def _rows(page, item, name, doc):
    from . import asmexplode as ax, asmexplines as el
    from . import configmanager as cm
    asm = ac.assembly_of(doc)
    for v in views_by_config(doc).get(name, []):
        vi = QtWidgets.QTreeWidgetItem(["%s%s" % (v.Label, "  (exploded)" if ax.is_exploded(v) else "")])
        vi.setData(0, cm.ROLE, ("explview", v.Name))
        vi.setToolTip(0, "Double-click to explode or collapse")
        vi.setIcon(0, _icon("ASSEMBLIES_EXPLODED_VIEW"))
        item.addChild(vi)
        for st in ax.steps(v):
            si = QtWidgets.QTreeWidgetItem([st.Label])
            si.setData(0, cm.ROLE, ("explstep", v.Name, st.Name))
            si.setIcon(0, _icon("ASSEMBLIES_EXPLODED_VIEW"))
            vi.addChild(si)

            for comp in (ax.step_components(asm, st) if asm is not None else []):
                ci = QtWidgets.QTreeWidgetItem([ax.display_name(comp)])
                ci.setData(0, cm.ROLE, ("explcomp", v.Name, st.Name, comp.Name))
                try:
                    ci.setIcon(0, comp.ViewObject.Icon)
                except Exception as _fw_err:
                    _fw_log("asmexplcfg.py:172", _fw_err)
                si.addChild(ci)
        for s in el.sketches(asm, v) if asm is not None else []:
            li = QtWidgets.QTreeWidgetItem([s.Label])
            li.setData(0, cm.ROLE, ("expllines", s.Name))
            li.setIcon(0, _icon("ASSEMBLIES_EXPLODE_LINE_SKETCH"))
            vi.addChild(li)


def _icon(family):
    try:
        from . import icons
        return icons.family(family)
    except Exception:
        return QtGui.QIcon()


def _new_in(asm, name):
    """New Exploded View on a configuration that is not shown: that configuration is shown first, so the
    new view belongs to it."""
    doc = asm.Document
    if name != active_config(doc):
        try:
            from . import configmanager as cm
            t = cm.table(doc)
            if t is not None and name in t.names():
                cm.show(t, name)
        except Exception as _fw_err:
            _fw_log("asmexplcfg.py:new_in", _fw_err)
    return new_exploded_view(asm)


def install():
    from . import configmanager as cm, asmexplode as ax
    if getattr(cm.Page, "_fw_explviews", False):
        return
    refresh0, entries0, activate0 = cm.Page.refresh, cm.Page.entries, cm.Page.activate

    def refresh(self):
        refresh0(self)
        try:
            doc = App.ActiveDocument
            if doc is None or ac.assembly_of(doc) is None:
                return
            groups = views_by_config(doc)
            if not groups:
                return
            root = self.tree.topLevelItem(0)
            todo = [root] if root is not None else []
            while todo:
                it = todo.pop(0)
                todo += [it.child(i) for i in range(it.childCount())]
                d = it.data(0, cm.ROLE) or ()
                name = d[1] if d[:1] == ("config",) else "Default" if d[:1] == ("default",) else None
                if name in groups:
                    _rows(self, it, name, doc)
            self.tree.expandAll()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view rows: %s\n" % error)

    def _obj(d, k=1):
        doc = App.ActiveDocument
        return doc.getObject(d[k]) if doc is not None and len(d) > k else None

    def entries(self, item):
        d = (item.data(0, cm.ROLE) if item is not None else None) or ("none",)
        try:
            if d[0] == "explview" and _obj(d):
                return view_entries(_obj(d))
            if d[0] in ("explstep", "explcomp") and _obj(d) and _obj(d, 2):
                return step_entries(_obj(d), _obj(d, 2))
            if d[0] == "expllines" and _obj(d):
                return lines_entries(_obj(d))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view menu: %s\n" % error)
        out = list(entries0(self, item))

        if d[0] in ("config", "default"):
            doc = App.ActiveDocument
            asm = ac.assembly_of(doc) if doc is not None else None
            if asm is not None:
                at = next((i for i, e in enumerate(out) if e[0] == "Edit Table..."), len(out))
                name = d[1] if d[0] == "config" else "Default"
                out[at:at] = [("New Exploded View...", lambda name=name: _new_in(asm, name), True)]
        return out

    def activate(self, item):
        d = (item.data(0, cm.ROLE) if item is not None else None) or ("none",)
        try:
            if d[0] == "explview" and _obj(d):
                return toggle(_obj(d))
            if d[0] in ("explstep", "explcomp") and _obj(d, 2):
                return ax.edit_step(_obj(d, 2))
            if d[0] == "expllines" and _obj(d):
                from . import asmexplines as el
                return el.edit(_obj(d))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view: %s\n" % error)
        return activate0(self, item)

    cm.Page.refresh, cm.Page.entries, cm.Page.activate = refresh, entries, activate
    cm.Page._fw_explviews = True
    # a new exploded view belongs to the configuration shown when it is made
    if not getattr(ax, "_fw_cfgstamp", False):
        nv0 = ax.new_view

        def new_view(asm):
            v = nv0(asm)
            try:
                stamp(v)
                cm.refresh_all()
            except Exception as _fw_err:
                _fw_log("asmexplcfg.py:269", _fw_err)
            return v
        ax.new_view = new_view
        ax._fw_cfgstamp = True
    # a renamed configuration keeps its exploded views
    from . import configs
    if not getattr(configs, "_fw_explrename", False):
        rename0 = configs.rename
        def rename(t, old, new):
            done = rename0(t, old, new)
            if done:
                try:
                    asm = ac.assembly_of(t.sheet.Document)
                    for v in ax.views(asm) if asm is not None else []:
                        if getattr(v, CFG_PROP, "") == old:
                            setattr(v, CFG_PROP, (new or "").strip())
                    cm.refresh_all()
                except Exception as _fw_err:
                    _fw_log("asmexplcfg.py:rename", _fw_err)
            return done
        rename.__wrapped__ = rename0
        configs.rename = rename
        configs._fw_explrename = True
    # a deleted configuration takes its exploded views with it
    if not getattr(cm, "_fw_expldelete", False):
        delete0 = cm.delete

        def delete(t, name, *args, **kwargs):     # ask= and the rest go through to configmanager.delete
            doc = t.sheet.Document
            asm = ac.assembly_of(doc)
            gone = [v for v in ax.views(asm) if getattr(v, CFG_PROP, "") == name] if asm is not None else []
            done = delete0(t, name, *args, **kwargs)
            if done and gone:
                try:
                    _remove_views(doc, asm, gone)
                    cm.refresh_all()
                except Exception as _fw_err:
                    _fw_log("asmexplcfg.py:delete", _fw_err)
            return done
        delete.__wrapped__ = delete0
        cm.delete = delete
        cm._fw_expldelete = True
