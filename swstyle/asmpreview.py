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

_open = None        # {"view", "comp", "asm", "callback", ...} while a preview shows


def is_open():
    return _open is not None and _alive()


def _alive():
    try:
        _open["view"].getSize()
        return True
    except Exception as _fw_err:
        _fw_log("asmpreview.py:42", _fw_err)
        return False


def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


def open_preview(asm, comp):
    """Opens the preview of comp; returns the viewer."""
    global _open
    close_preview()
    from pivy import coin
    assembly_view = Gui.ActiveDocument.ActiveView
    view = Gui.createViewer()
    view.setName("Component Preview - %s" % comp.Label)
    root = coin.SoSeparator()
    root.addChild(comp.ViewObject.RootNode)
    view.getViewer().setSceneGraph(root)
    view.viewIsometric()
    view.fitAll()
    viewport = view.graphicsView().viewport()
    callback = _Clicks(viewport)
    viewport.installEventFilter(callback)
    _open = {"view": view, "comp": comp, "asm": asm, "callback": callback, "root": root,
             "assembly_view": assembly_view, "fill": _fill_light(assembly_view, view, root)}
    _beside()
    return view


def _fill_light(assembly_view, view, root):
    """The assembly view's fill light in the preview (its viewer has the headlight only): same intensity and colour, the
    same direction as seen from the camera, turned with the camera. Returns the sensor to detach, or None."""
    try:
        from pivy import coin
        found = None
        search = coin.SoSearchAction()
        search.setType(coin.SoDirectionalLight.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(assembly_view.getViewer().getSoRenderManager().getSceneGraph())
        paths = search.getPaths()
        for i in range(paths.getLength()):
            tail = paths[i].getTail()
            if tail.getName().getString() == "filllight":
                found = tail
                break
        camera = view.getCameraNode()
        if found is None or camera is None or not found.on.getValue():
            return None
        light = coin.SoDirectionalLight()
        light.intensity.setValue(found.intensity.getValue())
        light.color.setValue(found.color.getValue())
        local = found.direction.getValue()

        def turn(*_args):
            world = camera.orientation.getValue().multVec(local)
            light.direction.setValue(world)

        turn()
        root.insertChild(light, 0)
        sensor = coin.SoFieldSensor(turn, None)
        sensor.setPriority(0)
        sensor.attach(camera.orientation)
        return (sensor, light)
    except Exception as _fw_err:
        _fw_log("asmpreview.py:fill light", _fw_err)
        return None


def _beside():
    ""
    mdi = _mdi()
    if mdi is None:
        return
    subs = [w for w in mdi.subWindowList() if w.isVisible() or w.widget() is not None]
    preview = next((w for w in subs if w.windowTitle().startswith("Component Preview")), None)
    if preview is None:
        return
    if mdi.viewMode() == QtWidgets.QMdiArea.TabbedView:
        # tabbed windows show one at a time: the preview floats beside the graphics area instead
        area = mdi.geometry()
        top_left = mdi.mapToGlobal(QtCore.QPoint(area.width() // 2, 0))
        preview.setParent(None)
        preview.setWindowFlags(QtCore.Qt.Tool)
        preview.setGeometry(top_left.x(), top_left.y(), area.width() // 2, area.height())
        preview.show()
        _open["floating"] = preview
    else:
        mdi.tileSubWindows()


def _pick_at(view, x, y):
    """(component, element) under viewport pixel (x, y), counted from the bottom left."""
    from pivy import coin
    comp = _open["comp"]
    rm = view.getViewer().getSoRenderManager()
    action = coin.SoRayPickAction(rm.getViewportRegion())
    action.setPoint(coin.SbVec2s(int(x), int(y)))
    action.setRadius(4)
    action.apply(rm.getSceneGraph())     # the whole viewer scene: the ray needs its camera
    picked = action.getPickedPoint()
    if picked is None:
        return None
    p = App.Vector(*picked.getPoint().getValue())
    return element_at(comp, p)


def element_at(comp, p, tol=1e-3):
    """The edge (else the face) of comp through the point p."""
    import Part
    vertex = Part.Vertex(p)
    best = None
    for prefix, count in (("Edge", None), ("Face", None)):
        for i in range(1, 100000):
            name = "%s%d" % (prefix, i)
            try:
                shape = comp.getSubObject(name)
            except Exception:
                shape = None
            if shape is None or shape.isNull():
                break
            d = shape.distToShape(vertex)[0]
            if d < tol * (20 if prefix == "Edge" else 1) and (best is None or d < best[0]):
                best = (d, name)
        if best is not None:
            return comp, best[1]
    return None


class _Clicks(QtCore.QObject):
    """A left click (no drag) in the preview picks the face or edge under it in the assembly."""
    def __init__(self, parent):
        super().__init__(parent)
        self.down = None

    def eventFilter(self, widget, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self.down = event.position().toPoint() if hasattr(event, "position") else event.pos()
        elif kind == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton \
                and self.down is not None:
            at = event.position().toPoint() if hasattr(event, "position") else event.pos()
            add = bool(event.modifiers() & QtCore.Qt.ControlModifier)
            if (at - self.down).manhattanLength() <= 4:
                # after FreeCAD's own click handling in that viewer, which finds nothing there
                QtCore.QTimer.singleShot(0, lambda: _clicked(at.x(), widget.height() - at.y(), add))
            self.down = None
        return False


def _clicked(x, y, add=False):
    if not is_open():
        return
    found = _pick_at(_open["view"], x, y)
    if found is not None:
        pick(found[0], found[1], add=add or _mate_open())


def _mate_open():
    try:
        from . import asmpm
        return isinstance(asmpm.OPEN, asmpm.MatePanel)
    except Exception:
        return False


def pick(comp, element, add=False):
    """Selects comp's element in the assembly (Mate takes it as the next pick)."""
    asm = _open["asm"] if _open else ac.assembly_of(comp.Document)
    if not add:
        Gui.Selection.clearSelection()
    Gui.Selection.addSelection(comp.Document.Name, asm.Name, "%s.%s" % (comp.Name, element))


def close_preview():
    global _open
    if _open is None:
        return
    state, _open = _open, None
    try:
        if state.get("fill"):
            state["fill"][0].detach()
    except Exception as _fw_err:
        _fw_log("asmpreview.py:fill off", _fw_err)
    try:
        state["callback"].parent().removeEventFilter(state["callback"])
    except (RuntimeError, AttributeError) as _fw_err:
        _fw_log("asmpreview.py:185", _fw_err)
    floating = state.get("floating")
    try:
        if floating is not None:
            floating.close()
        else:
            mdi = _mdi()
            for w in mdi.subWindowList() if mdi else []:
                if w.windowTitle().startswith("Component Preview"):
                    w.close()
    except RuntimeError as _fw_err:
        _fw_log("asmpreview.py:196", _fw_err)
    try:
        gdoc = Gui.getDocument(state["asm"].Document.Name)
        views = gdoc.mdiViewsOfType("Gui::View3DInventor")
        if views:
            Gui.getMainWindow().setActiveWindow(views[0])
    except Exception as _fw_err:
        _fw_log("asmpreview.py:203", _fw_err)


class ComponentPreviewCommand:
    def GetResources(self):
        return {"MenuText": "Component Preview Window", "Pixmap": "view-isometric",
                "ToolTip": "Shows the selected component alone in a window beside the assembly; "
                           "pick its faces there. Click again to close it."}

    def Activated(self):
        if is_open():
            close_preview()
            return
        from . import asmtools
        asm = asmtools._assembly()
        comps = asmtools._picked_components(asm) if asm is not None else []
        if not comps:
            asmtools._tell("Component Preview", "Select a component in the graphics area or the "
                           "FeatureManager design tree, then click Component Preview.")
            return
        open_preview(asm, comps[0])

    def IsActive(self):
        return is_open() or (App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None)


COMMANDS = (("SWStyle_ComponentPreview", ComponentPreviewCommand),)
