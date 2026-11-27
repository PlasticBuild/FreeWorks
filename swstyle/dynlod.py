# SPDX-License-Identifier: LGPL-2.1-or-later
""

















_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App
import FreeCADGui as Gui

SETTING = "Level of detail"
# screen size (the box's diagonal, in pixels) under which a component is left out while the view moves
SMALL_PX = {"Off": 0.0, "More (slower)": 8.0, "Less (faster)": 40.0}
TAG = "SWDynLod"
BOX_TAG = "SWDynLodBoxes"
STOP_MS = 120           # the view is still this long after the last release or wheel step: everything back

_state = {"moving": False, "pressed": False, "view": None, "skipped": [], "boxes": None, "root": None,
          "timer": None}
_cache = {}             # (doc, name) -> (key, (xmin, ymin, zmin, xmax, ymax, zmax))
stats = {"starts": 0, "skipped": 0}     # for checks


def setting():
    try:
        from . import optionspages
        value = optionspages.stored("Performance", SETTING, "More (slower)")
    except Exception:
        value = "More (slower)"
    return value if value in SMALL_PX else "More (slower)"


def _assembly(doc):
    try:
        from . import asmcore
        return asmcore.assembly_of(doc)
    except Exception:
        return None


def _box(comp):
    """The component's box in the assembly's (world) axes, kept while its placement and part stay the same."""
    try:
        linked = comp.getLinkedObject(True)
        shape = getattr(linked, "Shape", None)
        place = comp.getGlobalPlacement() if hasattr(comp, "getGlobalPlacement") else comp.Placement
        key = (tuple(place.toMatrix().A), shape.hashCode() if shape is not None else 0, id(linked))
    except Exception:
        return None
    ck = (comp.Document.Name, comp.Name)
    hit = _cache.get(ck)
    if hit is not None and hit[0] == key:
        return hit[1]
    try:
        import Part
        s = Part.getShape(comp, "", needSubElement=False, transform=True)
        if s.isNull():
            return None
        b = s.BoundBox
        if not b.isValid():
            return None
        box = (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax)
    except Exception as _fw_err:
        _fw_log("dynlod.py:box", _fw_err)
        return None
    _cache[ck] = (key, box)
    return box


def _corners(box):
    x0, y0, z0, x1, y1, z1 = box
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def screen_size(view, box):
    """The box's size on screen: the diagonal of its corners' screen rectangle, in pixels."""
    pts = [view.getPointOnViewport(App.Vector(*c)) for c in _corners(box)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5


def small_components(view, doc, limit):
    """[(component, box)] of the shown components smaller on screen than limit pixels."""
    asm = _assembly(doc)
    if asm is None or limit <= 0:
        return []
    from . import asmcore
    out = []
    gdoc = Gui.getDocument(doc.Name)
    for comp in asmcore.components(asm):
        try:
            vobj = gdoc.getObject(comp.Name)
            if vobj is None or not vobj.Visibility or comp.TypeId != "App::Link":
                continue
            box = _box(comp)
            if box is not None and screen_size(view, box) < limit:
                out.append((comp, box))
        except Exception as _fw_err:
            _fw_log("dynlod.py:small", _fw_err)
    return out


def _mode_switch(root):
    for i in range(root.getNumChildren()):
        if root.getChild(i).getName().getString() == "ModeSwitch":
            return i, root.getChild(i)
    return -1, None


def _skip(comp):
    """The two callbacks around the component's ModeSwitch: off while traversed, back after."""
    from pivy import coin
    root = comp.ViewObject.RootNode
    k, switch = _mode_switch(root)
    if switch is None:
        return None
    saved = []

    def pre(_ud, _action):
        try:
            saved.append(switch.whichChild.getValue())
            switch.enableNotify(False)
            switch.whichChild = -1
            switch.enableNotify(True)
        except Exception as _fw_err:
            _fw_log("dynlod.py:pre", _fw_err)

    def post(_ud, _action):
        try:
            if saved:
                was = saved.pop()
                switch.enableNotify(False)
                switch.whichChild = was
                switch.enableNotify(True)
        except Exception as _fw_err:
            _fw_log("dynlod.py:post", _fw_err)

    a = coin.SoCallback()
    a.setName(TAG + "Off")
    a.setCallback(pre)
    b = coin.SoCallback()
    b.setName(TAG + "On")
    b.setCallback(post)
    root.insertChild(a, k)
    root.insertChild(b, k + 2)
    return (root, a, b, pre, post)


def _unskip(item):
    root, a, b = item[:3]
    for node in (a, b):
        try:
            i = root.findChild(node)
            if i >= 0:
                root.removeChild(i)
        except Exception as _fw_err:
            _fw_log("dynlod.py:unskip", _fw_err)


def _box_node(boxes):
    """Thin grey outlines of the left-out components' boxes."""
    from pivy import coin
    sep = coin.SoSeparator()
    sep.setName(BOX_TAG)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(pick)
    lm = coin.SoLightModel()
    lm.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(lm)
    m = coin.SoMaterial()
    m.diffuseColor.setValue(0.45, 0.45, 0.48)
    sep.addChild(m)
    ds = coin.SoDrawStyle()
    ds.lineWidth = 1.0
    sep.addChild(ds)
    pts, counts = [], []
    for box in boxes:
        c = _corners(box)       # index: x*4 + y*2 + z
        for path in ((0, 1, 3, 2, 0, 4, 5, 7, 6, 4), (1, 5), (3, 7), (2, 6)):
            pts.extend(c[i] for i in path)
            counts.append(len(path))
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    sep.addChild(coords)
    ls = coin.SoLineSet()
    ls.numVertices.setValues(0, len(counts), counts)
    sep.addChild(ls)
    return sep


def start(view=None):
    """The view starts to move: leave out the small components (and draw their boxes)."""
    if _state["moving"]:
        return len(_state["skipped"])
    limit = SMALL_PX.get(setting(), 0.0)
    doc = App.ActiveDocument
    if limit <= 0 or doc is None:
        return 0
    try:
        view = view or Gui.ActiveDocument.ActiveView
    except Exception:
        return 0
    small = small_components(view, doc, limit)
    _state["moving"], _state["view"] = True, view
    stats["starts"] += 1
    if not small:
        return 0
    for comp, _box_ in small:
        try:
            item = _skip(comp)
            if item is not None:
                _state["skipped"].append(item)
        except Exception as _fw_err:
            _fw_log("dynlod.py:start", _fw_err)
    stats["skipped"] = len(_state["skipped"])
    try:
        root = view.getSceneGraph()
        node = _box_node([b for _c, b in small])
        root.addChild(node)
        _state["boxes"], _state["root"] = node, root
    except Exception as _fw_err:
        _fw_log("dynlod.py:boxes", _fw_err)
    return len(_state["skipped"])


def stop():
    """The view is still: everything drawn as it is again."""
    if not _state["moving"]:
        return
    _state["moving"] = False
    for item in _state["skipped"]:
        _unskip(item)
    _state["skipped"] = []
    node, root = _state["boxes"], _state["root"]
    if node is not None and root is not None:
        try:
            i = root.findChild(node)
            if i >= 0:
                root.removeChild(i)
        except Exception as _fw_err:
            _fw_log("dynlod.py:stopboxes", _fw_err)
    _state["boxes"] = _state["root"] = _state["view"] = None
    try:
        Gui.ActiveDocument.ActiveView.redraw()
    except Exception:
        pass


def moving():
    return _state["moving"]


def _later_stop(ms):
    from PySide import QtCore
    if _state["timer"] is None:
        _state["timer"] = QtCore.QTimer()
        _state["timer"].setSingleShot(True)
        _state["timer"].timeout.connect(stop)
    _state["timer"].start(ms)


def _event(obj, event):
    """A middle-button drag in the 3D view (turn, pan), or a wheel step (zoom), starts the move; letting go (or
    a still wheel) ends it. A click without a drag, a box pick or a component drag changes nothing."""
    from PySide import QtCore
    try:
        if not obj.inherits("QOpenGLWidget"):
            return False
        QE = QtCore.QEvent
        t = event.type()
        if t == QE.MouseButtonPress:
            _state["pressed"] = True
        elif t == QE.MouseMove:
            # the middle button turns and pans the view (a left drag picks with a box or drags a component)
            if _state["pressed"] and not _state["moving"] and event.buttons() & QtCore.Qt.MiddleButton:
                start()
        elif t == QE.MouseButtonRelease:
            _state["pressed"] = False
            if _state["moving"]:
                _later_stop(STOP_MS)
        elif t == QE.Wheel:
            start()
            _later_stop(400)
    except Exception as _fw_err:
        _fw_log("dynlod.py:event", _fw_err)
    return False


OPTIMIZE_COMMAND = "SWStyle_OptimizeZoomPanRotate"
_KEPT = "Level of detail before Optimize off"      # the slider's stop while the menu switch is off


def optimized():
    """View > Display > Optimize Zoom/Pan/Rotate is checked: the view leaves out small components while it moves."""
    return SMALL_PX.get(setting(), 0.0) > 0


def set_optimized(on):
    from . import optionspages
    now = setting()
    if on and now == "Off":
        back = optionspages.stored("Performance", _KEPT, "More (slower)")
        optionspages.set_stored("Performance", SETTING, back if SMALL_PX.get(back, 0.0) > 0 else "More (slower)")
    elif not on and now != "Off":
        optionspages.set_stored("Performance", _KEPT, now)
        optionspages.set_stored("Performance", SETTING, "Off")
        stop()
    _sync()


def _sync():
    state = optimized()
    try:
        actions = Gui.Command.get(OPTIMIZE_COMMAND).getAction()
    except Exception:
        actions = []
    for action in actions:
        if action.isChecked() != state:
            blocked = action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(blocked)


class _Optimize:
    def GetResources(self):
        return {"MenuText": "Optimize Zoom/Pan/Rotate", "Pixmap": "zoom-all",
                "ToolTip": "While you zoom, pan or rotate an assembly, leaves out the components that are small "
                           "on screen and draws them again when the view stops",
                "Checkable": optimized(), "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        set_optimized(not optimized())

    def IsActive(self):
        _sync()     # follows the Options slider too
        return Gui.ActiveDocument is not None


def install():
    from PySide import QtCore
    if OPTIMIZE_COMMAND not in Gui.listCommands():
        Gui.addCommand(OPTIMIZE_COMMAND, _Optimize())
    from . import events
    events.register("dynamic-level-of-detail", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                                QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Wheel), _event)
