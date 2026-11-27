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

import importlib
import json

import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

PREFIX = "swstyle."
APP_PROP, VIEW_PROP = "FreeWorksClass", "FreeWorksView"


def _ours(proxy):
    return proxy is not None and type(proxy).__module__.startswith(PREFIX)


def _state(proxy):
    for name in ("dumps", "__getstate__"):
        method = getattr(proxy, name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                return None
    return None


def _text(proxy):
    cls = type(proxy)
    try:
        state = json.dumps(_state(proxy))
    except Exception:
        state = "null"
    return "%s:%s|%s" % (cls.__module__, cls.__name__, state)


def _instance(text):
    head, _, state = text.partition("|")
    module, _, name = head.partition(":")
    if not module.startswith(PREFIX):
        return None
    cls = getattr(importlib.import_module(module), name)
    proxy = cls.__new__(cls)
    try:
        value = json.loads(state) if state else None
    except Exception:
        value = None
    for method in ("loads", "__setstate__"):
        fn = getattr(proxy, method, None)
        if callable(fn) and value is not None:
            try:
                fn(value)
            except Exception as _fw_err:
                _fw_log("cleanfiles.py:78", _fw_err)
            break
    return proxy


def _mark(obj, prop, text):
    if prop not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", prop, "FreeCAD", "FreeCAD class, put back on open")
        obj.setEditorMode(prop, 2)
    if getattr(obj, prop) != text:
        setattr(obj, prop, text)


_held = {}       # document name -> [(object, app proxy or None, view proxy or None)]


def strip(doc):
    ""
    held = []
    for obj in doc.Objects:
        proxy = getattr(obj, "Proxy", None) if "Proxy" in obj.PropertiesList else None
        vobj = getattr(obj, "ViewObject", None) if App.GuiUp else None
        vproxy = getattr(vobj, "Proxy", None) if vobj is not None and "Proxy" in vobj.PropertiesList else None
        app = _ours(proxy)
        view = _ours(vproxy)
        if not app and not view:
            continue
        touched = "Touched" in obj.State
        try:
            if app:
                _mark(obj, APP_PROP, _text(proxy))
            if view:
                _mark(obj, VIEW_PROP, _text(vproxy))
            if app:
                obj.Proxy = None
            if view:
                vobj.Proxy = None
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s keeps its class in the file (%s)\n" % (obj.Label, error))
        if not touched:
            obj.purgeTouched()
        held.append((obj, proxy if app else None, vproxy if view else None))
    _held[doc.Name] = held
    _note_hidden(doc)


HIDDEN_KEY = "FreeWorksHidden"


def _note_hidden(doc):
    ""

    try:
        hidden = [o.Name for o in doc.Objects
                  if getattr(o, "ViewObject", None) is not None and (APP_PROP in o.PropertiesList or VIEW_PROP in o.PropertiesList)
                  and not o.ViewObject.Visibility]
        meta = dict(doc.Meta or {})
        want = json.dumps(hidden) if hidden else None
        if meta.get(HIDDEN_KEY) != want:
            if want is None:
                meta.pop(HIDDEN_KEY, None)
            else:
                meta[HIDDEN_KEY] = want
            doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("cleanfiles.py:hidden", _fw_err)


def _hidden_of(doc):
    try:
        return json.loads((doc.Meta or {}).get(HIDDEN_KEY, "[]"))
    except Exception:
        return []


def _rehide(doc):
    names = _hidden_of(doc)
    if not names:
        return
    try:
        gdoc = Gui.getDocument(doc.Name)
        was = gdoc.Modified
        for name in names:
            obj = doc.getObject(name)
            vo = getattr(obj, "ViewObject", None) if obj is not None else None
            if vo is not None and vo.Visibility:
                vo.Visibility = False
        if gdoc.Modified != was:
            gdoc.Modified = was
    except Exception as _fw_err:
        _fw_log("cleanfiles.py:rehide", _fw_err)


def put_back(doc):
    """After the save: the same class objects go straight back on."""
    for obj, proxy, vproxy in _held.pop(doc.Name, []):
        touched = "Touched" in obj.State
        try:
            if proxy is not None:
                obj.Proxy = proxy
            if vproxy is not None:
                obj.ViewObject.Proxy = vproxy
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: could not put back %s's class (%s)\n" % (obj.Label, error))
        if not touched:
            obj.purgeTouched()


def restore(doc):
    ""
    views = []
    for obj in doc.Objects:
        props = obj.PropertiesList
        if APP_PROP in props and obj.getPropertyByName(APP_PROP) and \
                "Proxy" in props and not _ours(getattr(obj, "Proxy", None)):
            try:
                proxy = _instance(obj.getPropertyByName(APP_PROP))
                if proxy is not None:
                    obj.Proxy = proxy
                    if hasattr(proxy, "onDocumentRestored"):
                        proxy.onDocumentRestored(obj)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s could not get its class back (%s)\n" % (obj.Label, error))
            obj.purgeTouched()
        if VIEW_PROP in props and obj.getPropertyByName(VIEW_PROP):
            views.append(obj)
    if (views or _hidden_of(doc)) and App.GuiUp:
        from PySide import QtCore
        names = (doc.Name, [o.Name for o in views])     # now: the document can be gone when the timer fires
        QtCore.QTimer.singleShot(0, lambda: _restore_views(*names))


def restore_named(name):
    doc = App.listDocuments().get(name)
    if doc is not None:
        restore(doc)


def _restore_views(doc_name, names):
    doc = App.listDocuments().get(doc_name)
    if doc is None:
        return
    for name in names:
        obj = doc.getObject(name)
        vobj = getattr(obj, "ViewObject", None)
        if vobj is None or _ours(getattr(vobj, "Proxy", None)):
            continue
        try:
            proxy = _instance(obj.getPropertyByName(VIEW_PROP))
            if proxy is not None:
                try:
                    proxy.Object = obj      # claimChildren / getIcon read it before attach() runs (restorefix-1126)
                except Exception:
                    pass
                vobj.Proxy = proxy
                _attach(vobj, proxy)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s's view could not get its class back (%s)\n" % (obj.Label, error))
    _reclaim(doc_name, names)
    _rehide(doc)


def _attach(vobj, proxy):
    """A view whose class goes back on after the file opened: FreeCAD does not call attach() for it, so
    its display mode (made in attach) was missing and the saved one could not be set. The row then
    showed greyed as if hidden, and a folder knew no object to list rows for (look audit AD1:
    Solid Bodies gone, the body row loose at the bottom, Material grey)."""
    try:
        if vobj.DisplayMode:
            return              # attached already (a document FreeCAD itself restored with the class)
        attach = getattr(proxy, "attach", None)
        if callable(attach):
            attach(vobj)
        mode = None
        default = getattr(proxy, "getDefaultDisplayMode", None)
        if callable(default):
            mode = default()
        modes = vobj.listDisplayModes()
        if mode not in modes:
            mode = modes[0] if modes else None
        if mode:
            try:
                vobj.DisplayMode = mode
            except Exception:
                # the mode list was made while the view had no class: give it the class's modes
                vobj.DisplayMode = list(modes)
                vobj.DisplayMode = mode
    except Exception as _fw_err:
        _fw_log("cleanfiles.py:attach", _fw_err)


def _reclaim(doc_name, names):
    """The tree asked the folders for their rows before the classes were back: it is asked again (each
    such row shown afresh). The document stays as it was (unmodified after an open)."""
    try:
        gdoc = Gui.getDocument(doc_name)
        doc = App.getDocument(doc_name)
    except Exception:
        return
    was = gdoc.Modified
    for name in names:
        obj = doc.getObject(name)
        vobj = getattr(obj, "ViewObject", None)
        if vobj is None or not callable(getattr(getattr(vobj, "Proxy", None), "claimChildren", None)):
            continue
        try:
            shown = vobj.ShowInTree
            vobj.ShowInTree = not shown
            vobj.ShowInTree = shown
        except Exception as _fw_err:
            _fw_log("cleanfiles.py:reclaim", _fw_err)
    if gdoc.Modified != was:
        gdoc.Modified = was


class _Observer:
    def slotStartSaveDocument(self, doc, filename):
        strip(doc)

    def slotFinishSaveDocument(self, doc, filename):
        put_back(doc)

    def slotFinishRestoreDocument(self, doc):
        # FreeCAD sets the saved (empty) Proxy values after this signal: put the classes on after it
        if App.GuiUp:
            from PySide import QtCore
            name = doc.Name
            QtCore.QTimer.singleShot(0, lambda: restore_named(name))
        else:
            restore(doc)


_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
        # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
        from . import restorehook
        restorehook.on_restored(_observer.slotFinishRestoreDocument)
