""










import FreeCAD as App

PROP = "SWDisplayMode"
TAG = "SWCompMode"
# FreeCAD display mode -> the child of a Part view provider's display-mode switch
CHILD = {"Flat Lines": "NormalRoot", "Shaded": "FlatRoot", "Wireframe": "WireframeRoot",
         "Points": "PointsRoot"}

_live = {}          # (doc, link name) -> (pre node, post node, state); keeps the callbacks alive
_observer = None


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD: %s: %s\n" % (site, err))
    except Exception:
        pass


def is_component(obj):
    try:
        return obj is not None and obj.TypeId == "App::Link" and obj.ViewObject is not None \
            and hasattr(obj.ViewObject, "OverrideMaterial")
    except ReferenceError:
        return False


def get(link):
    """The instance's own mode, or "" when it draws as its part does."""
    try:
        return getattr(link, PROP, "") or ""
    except Exception:
        return ""


def drawn(link):
    """The mode the instance shows."""
    m = get(link)
    if m:
        return m
    try:
        return link.LinkedObject.ViewObject.DisplayMode
    except Exception:
        return ""


def set_mode(link, mode):
    """Give one instance its own mode (None or "" = as its part)."""
    mode = mode or ""
    if mode and mode not in CHILD:
        return False
    if not hasattr(link, PROP):
        if not mode:
            return True
        link.addProperty("App::PropertyString", PROP, "Display", "Display Mode of this instance", 4)
    if getattr(link, PROP) != mode:
        setattr(link, PROP, mode)       # the observer applies it (undo/redo too)
    apply(link)
    return True


def _key(link):
    return (link.Document.Name, link.Name)


def _remove(link):
    item = _live.pop(_key(link), None)
    if item is None:
        return
    try:
        root = link.ViewObject.RootNode
    except Exception:
        return
    for node in item[:2]:
        try:
            i = root.findChild(node)
            if i >= 0:
                root.removeChild(i)
        except Exception as _fw_err:
            _fw_log("compmode.py:remove", _fw_err)


def _shared_switch(mode_switch):
    """The part's display-mode switch under the link's ModeSwitch."""
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoSwitch.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.setSearchingAll(True)
    sa.apply(mode_switch)
    paths = sa.getPaths()
    for i in range(paths.getLength()):
        node = paths[i].getTail()
        if node is mode_switch or node.getNumChildren() < 3:
            continue
        if node.getChild(0).getName().getString() == "NormalRoot":
            return node
    return None


def apply(link):
    """Draw the instance in its own mode (or as its part when it has none)."""
    if not is_component(link):
        return
    _remove(link)
    mode = get(link)
    if not mode:
        return
    import os
    if os.environ.get("FW_NO_COMPMODE") or os.environ.get("NOCOMPMODE"):
        return          # fault hunting: no callbacks that switch the part's display mode while drawing
    from pivy import coin
    root = link.ViewObject.RootNode
    mode_switch = None
    for i in range(root.getNumChildren()):
        if root.getChild(i).getName().getString() == "ModeSwitch":
            mode_switch = root.getChild(i)
            k = i
            break
    if mode_switch is None:
        return
    state = {"content": None, "switch": None, "index": -1, "saved": []}

    def resolve():
        content = mode_switch.getChild(0) if mode_switch.getNumChildren() else None
        ident = int(content.this) if content is not None else 0
        if ident != state["content"]:
            state["content"] = ident
            sw = _shared_switch(mode_switch)
            state["switch"] = sw
            state["index"] = -1
            if sw is not None:
                names = [sw.getChild(j).getName().getString() for j in range(sw.getNumChildren())]
                want = CHILD.get(get(link), "")
                state["index"] = names.index(want) if want in names else -1
        return state["switch"], state["index"]

    def pre(_ud, _action):
        try:
            sw, idx = resolve()
            if sw is None or idx < 0:
                state["saved"].append(None)
                return
            state["saved"].append(sw.whichChild.getValue())
            sw.enableNotify(False)
            sw.whichChild = idx
            sw.enableNotify(True)
        except Exception as _fw_err:
            state["saved"].append(None)
            _fw_log("compmode.py:pre", _fw_err)

    def post(_ud, _action):
        try:
            was = state["saved"].pop() if state["saved"] else None
            sw = state["switch"]
            if was is None or sw is None:
                return
            sw.enableNotify(False)
            sw.whichChild = was
            sw.enableNotify(True)
        except Exception as _fw_err:
            _fw_log("compmode.py:post", _fw_err)

    a = coin.SoCallback()
    a.setName(TAG + "On")
    a.setCallback(pre)
    b = coin.SoCallback()
    b.setName(TAG + "Off")
    b.setCallback(post)
    root.insertChild(a, k)
    root.insertChild(b, k + 2)
    _live[_key(link)] = (a, b, state, pre, post)
    try:
        link.ViewObject.RootNode.touch()
    except Exception:
        pass


def apply_document(doc):
    for obj in doc.Objects:
        if hasattr(obj, PROP) and is_component(obj):
            apply(obj)


class _Observer:
    def slotChangedObject(self, obj, prop):
        if prop == PROP:
            try:
                apply(obj)
            except Exception as _fw_err:
                _fw_log("compmode.py:changed", _fw_err)
        elif prop == "LinkedObject" and hasattr(obj, PROP):
            try:
                apply(obj)
            except Exception as _fw_err:
                _fw_log("compmode.py:linked", _fw_err)

    def slotDeletedObject(self, obj):
        try:
            _live.pop(_key(obj), None)
        except Exception:
            pass

    def slotFinishRestoreDocument(self, doc):
        from PySide import QtCore
        name = doc.Name

        def later():
            d = App.listDocuments().get(name)
            if d is not None:
                apply_document(d)
        QtCore.QTimer.singleShot(0, later)

    def slotDeletedDocument(self, doc):
        for k in [k for k in _live if k[0] == doc.Name]:
            _live.pop(k, None)


def install():
    global _observer
    if _observer is not None:
        return
    _observer = _Observer()
    App.addDocumentObserver(_observer)
    try:
        from . import dynlod            # Level of detail while the view moves (assemblies)
        dynlod.install()
    except Exception as _fw_err:
        _fw_log("compmode.py:dynlod", _fw_err)
    for doc in App.listDocuments().values():
        try:
            apply_document(doc)
        except Exception as _fw_err:
            _fw_log("compmode.py:install", _fw_err)
