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

SETTING = "ScaleEdgeWidth"
_observer = None
_gui_observer = None


def enabled():
    try:
        from . import paths
        return paths.params().GetBool(SETTING, True)
    except Exception:
        return True


def factor():
    """The 3D views' scale factor (the main window's screen; 1.0 at 100 %)."""
    if not enabled():
        return 1.0
    try:
        mw = Gui.getMainWindow()
        handle = mw.windowHandle() if mw is not None else None
        screen = handle.screen() if handle is not None else QtWidgets.QApplication.primaryScreen()
        return max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        return 1.0


def _styles(vo):
    """The SoDrawStyle nodes of vo's own scene that draw its edges (lineWidth fed by LineWidth)."""
    try:
        from pivy import coin
        root = vo.RootNode
    except Exception:
        return []
    want = float(vo.LineWidth)
    sa = coin.SoSearchAction()
    sa.setType(coin.SoDrawStyle.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.setSearchingAll(True)
    sa.apply(root)
    out = []
    for i in range(sa.getPaths().getLength()):
        node = sa.getPaths().get(i).getTail()
        try:
            width = float(node.lineWidth.getValue())
        except Exception:
            continue
        # FreeCAD's own value, or one this module already scaled (any factor)
        if want > 0 and (abs(width - want) < 1e-6 or
                         any(abs(width - want * f) < 1e-6 for f in (1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0))):
            out.append(node)
    return out


_found = {}         # (document, object) -> (scene root, its edge style nodes): searched once, not on every sweep


def _styles_kept(vo, obj):
    """_styles(vo), searched once per object and scene root (a search walks the object's whole scene: on a big
    file each sweep searched every object again, 1.25 s on file open). A node kept here is FreeCAD's own edge
    style, which FreeCAD keeps for the object's life and writes LineWidth into again."""
    try:
        root = vo.RootNode
        key = (obj.Document.Name, obj.Name)
    except Exception:
        return _styles(vo)
    got = _found.get(key)
    if got is not None and got[0] == root and got[1]:
        return got[1]
    nodes = _styles(vo)
    _drop(key)
    for node in nodes:
        try:
            node.ref()          # 0.4.1 (GitHub #6): held while kept, so a node FreeCAD frees cannot be read after
        except Exception as _fw_err:
            _fw_log("edgescale.py:ref", _fw_err)
    _found[key] = (root, nodes)
    return nodes


def _drop(key):
    """Forgets one kept entry and lets go of its nodes."""
    got = _found.pop(key, None)
    for node in (got[1] if got else ()):
        try:
            node.unref()
        except Exception as _fw_err:
            _fw_log("edgescale.py:unref", _fw_err)


def _is_link(obj):
    """A link draws another object's scene (often in another file): that object's own view sets its edges.
    Its nodes are freed when that file is closed or read again (an assembly loading a part fully on open),
    so keeping them under the link crashed FreeCAD (GitHub #6)."""
    try:
        return obj.hasExtension("App::LinkBaseExtension") or "LinkedObject" in obj.PropertiesList
    except Exception:
        return False


def scale(vo, f=None):
    """Draws vo's edges at LineWidth x f (the screen's factor). Returns the number of nodes set."""
    if vo is None or "LineWidth" not in getattr(vo, "PropertiesList", ()):
        return 0
    obj = getattr(vo, "Object", None)
    if obj is None or getattr(obj, "Shape", None) is None or _is_link(obj):
        return 0
    f = factor() if f is None else f
    n = 0
    want = float(vo.LineWidth) * f
    for node in _styles_kept(vo, obj):
        try:
            if abs(node.lineWidth.getValue() - want) > 1e-6:
                node.lineWidth.setValue(want)
            n += 1
        except Exception as _fw_err:
            _fw_log("edgescale.py:scale", _fw_err)
    return n


def scale_document(doc, f=None):
    gdoc = Gui.getDocument(doc.Name) if doc is not None and App.GuiUp else None
    if gdoc is None:
        return 0
    n = 0
    for obj in doc.Objects:
        try:
            n += scale(gdoc.getObject(obj.Name), f)
        except Exception as _fw_err:
            _fw_log("edgescale.py:doc", _fw_err)
    return n


def scale_all(f=None):
    return sum(scale_document(d, f) for d in App.listDocuments().values())


class _AppObserver:
    def slotFinishRestoreDocument(self, doc):
        QtCore.QTimer.singleShot(200, lambda n=doc.Name: _later_doc(n))

    def slotActivateDocument(self, doc):
        # once per document and scale factor (a sweep walks every object's scene: switching windows stays quick)
        if (doc.Name, factor()) not in _swept:
            QtCore.QTimer.singleShot(0, lambda n=doc.Name: _later_doc(n))

    def slotDeletedDocument(self, doc):
        for key in [k for k in _swept if k[0] == doc.Name]:
            _swept.discard(key)
        for key in [k for k in _found if k[0] == doc.Name]:
            _drop(key)

    def slotDeletedObject(self, obj):
        try:
            _drop((obj.Document.Name, obj.Name))
        except Exception as _fw_err:
            _fw_log("edgescale.py:deleted", _fw_err)

    def slotCreatedObject(self, obj):
        # the view object is made after this signal: right after
        QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, o=obj.Name: _later_obj(d, o))


_pending = []
_swept = set()


class _GuiObserver:
    """Only the property's name is read here: FreeCAD also sends this while a view provider is still being built
    (its Object not set yet; reading it there crashed FreeCAD 1.1.4), so the active document is swept a moment later."""

    def slotChangedObject(self, vp, prop):
        # FreeCAD puts LineWidth back into the node when it changes (and on a display mode switch)
        if prop in ("LineWidth", "DisplayMode") and not _pending:
            _pending.append(True)
            QtCore.QTimer.singleShot(0, _sweep_active)


def _sweep_active():
    del _pending[:]
    doc = App.ActiveDocument
    if doc is not None and factor() != 1.0:      # at 100 % FreeCAD's own write is already the width wanted
        scale_document(doc)


def _later_doc(name):
    doc = App.listDocuments().get(name)
    if doc is not None:
        scale_document(doc)
        _swept.add((name, factor()))


def _later_obj(doc_name, obj_name):
    doc = App.listDocuments().get(doc_name)
    obj = doc.getObject(obj_name) if doc is not None else None
    if obj is None:
        return
    try:
        scale(Gui.getDocument(doc_name).getObject(obj_name))
    except Exception as _fw_err:
        _fw_log("edgescale.py:obj", _fw_err)


def _screen_changed(*_args):
    _swept.clear()
    QtCore.QTimer.singleShot(0, scale_all)


def install():
    global _observer, _gui_observer
    if _observer is not None:
        return
    _observer, _gui_observer = _AppObserver(), _GuiObserver()
    App.addDocumentObserver(_observer)
    try:
        Gui.addDocumentObserver(_gui_observer)
    except Exception as _fw_err:
        _fw_log("edgescale.py:gui-observer", _fw_err)
    try:
        from . import restorehook
        restorehook.on_restored(_observer.slotFinishRestoreDocument)
    except Exception as _fw_err:
        _fw_log("edgescale.py:restorehook", _fw_err)
    try:
        # the window dragged to a screen with another scale factor
        Gui.getMainWindow().windowHandle().screenChanged.connect(_screen_changed)
    except Exception as _fw_err:
        _fw_log("edgescale.py:screen", _fw_err)
    scale_all()


def remove():
    """Style off: FreeCAD's own widths back."""
    global _observer, _gui_observer
    if _observer is not None:
        try:
            App.removeDocumentObserver(_observer)
        except Exception as _fw_err:
            _fw_log("edgescale.py:remove", _fw_err)
    if _gui_observer is not None:
        try:
            Gui.removeDocumentObserver(_gui_observer)
        except Exception as _fw_err:
            _fw_log("edgescale.py:remove-gui", _fw_err)
    try:
        Gui.getMainWindow().windowHandle().screenChanged.disconnect(_screen_changed)
    except Exception:
        pass
    _observer = _gui_observer = None
    scale_all(1.0)
