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

GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
PARAM = "RapidSketch"
COMMAND = "SWStyle_RapidSketch"
SKETCH = "Sketcher::SketchObject"
FILL = (1.0, 0.62, 0.20)               # the lit face (sketchstart's orange plane colour)


_GROUP = []     # the parameter group, kept: ParamGet on every mouse move was most of this filter's cost


def on():
    if not _GROUP:
        _GROUP.append(App.ParamGet(GENERAL))
    return _GROUP[0].GetBool(PARAM, False)


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 4000)
    except Exception as _fw_err:
        _fw_log("rapidsketch.py:51", _fw_err)


def _command_of(running):
    ""
    from .fwsketch import commands
    title = running.title()
    if title == "Line" and getattr(running, "construction", False) and "FreeWorks_Centerline" in commands.COMMANDS:
        return "FreeWorks_Centerline"
    for name, entry in commands.COMMANDS.items():
        if entry[0] == title:
            return name
    return None


def _plane(face):
    """(point, unit normal) of a flat face, or None."""
    try:
        surface = face.Surface
        if type(surface).__name__ == "Plane":
            return surface.Position, surface.Axis.normalize()
        found = face.findPlane()
        if found is not None:
            return found.Position, found.Axis.normalize()
    except Exception as _fw_err:
        _fw_log("rapidsketch.py:76", _fw_err)
    return None


def on_sketch_plane(sketch, face):
    plane = _plane(face)
    if plane is None:
        return True
    gpl = sketch.getGlobalPlacement()
    normal = gpl.Rotation.multVec(App.Vector(0, 0, 1))
    if normal.cross(plane[1]).Length > 1e-6:
        return False
    return abs((plane[0] - gpl.Base).dot(normal)) < 1e-6


def face_under(view, sketch, pos=None):
    """(support object, "FaceN", face) of a flat part face under the pointer that a new sketch could
    go on, or None. The nearest thing hit decides: the sketch, an edge or a corner come first."""
    try:
        from .fwsketch import modelpick
        if modelpick.sketch_preselected(sketch):
            return None
    except Exception as _fw_err:
        _fw_log("rapidsketch.py:99", _fw_err)
    try:
        hits = view.getObjectsInfo(pos or view.getCursorPos()) or []
    except Exception:
        return None
    if not hits:
        return None
    hit = hits[0]
    name, comp = hit.get("Object"), hit.get("Component") or ""
    if not name or name == sketch.Name:
        return None
    sub = comp.split(".")[-1]
    if not sub.startswith("Face"):
        return None
    obj = sketch.Document.getObject(name)
    if obj is None or not hasattr(obj, "Shape"):
        return None
    if obj.TypeId == "PartDesign::Body" and obj.Tip is not None:
        obj = obj.Tip              # the body shows its tip: the face is the tip feature's
    try:
        face = obj.Shape.getElement(sub)
    except Exception:
        return None
    if _plane(face) is None or on_sketch_plane(sketch, face):
        return None
    return obj, sub, face


class _Lit:
    """The face under the pointer, filled see-through over everything, never picked."""

    def __init__(self, view, face):
        from pivy import coin
        self.view = view
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*FILL)
        mat.transparency.setValue(0.6)
        coords = coin.SoCoordinate3()
        faces = coin.SoIndexedFaceSet()
        points, triangles = face.tessellate(0.2)
        coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
        index = []
        for tri in triangles:
            index.extend((tri[0], tri[1], tri[2], -1))
        faces.coordIndex.setValues(0, len(index), index)
        for node in (pick, light, mat, coords, faces):
            self.root.addChild(node)
        view.getSceneGraph().addChild(self.root)

    def remove(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("rapidsketch.py:157", _fw_err)


class RapidSketch(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.app = QtWidgets.QApplication.instance()
        self.seen = None             # the tool the filter was last put in front of
        self.lit = None              # _Lit
        self.target = None           # (document name, object name, sub) lit now
        self.eat_release = False
        self.switches = []           # (from sketch, object name, sub, command), for checks
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self.installed = False
        QE = QtCore.QEvent
        self.wanted = frozenset(int(x) for x in (QE.MouseMove, QE.MouseButtonPress, QE.MouseButtonRelease,
                                                 QE.MouseButtonDblClick, QE.Leave))

    def _poll(self):
        # The app-wide filter sees every event of the application, so it is only in place while it
        # can act: Rapid Sketch on and a sketch tool running (or a release still to eat). The PC
        # profile counted it among the filters called on every event.
        from .fwsketch import tool
        running = tool.active()
        need = (running is not None and on()) or self.eat_release
        if not need:
            if self.installed:
                self.app.removeEventFilter(self)
                self.installed = False
                self._unlight()
            self.seen = running
            return
        if running is not self.seen or not self.installed:
            self.seen = running
            self.app.removeEventFilter(self)
            self.app.installEventFilter(self)    # in front of the new tool's filter
            self.installed = True

    def _unlight(self):
        if self.lit is not None:
            self.lit.remove()
        self.lit = self.target = None

    def _context(self, obj):
        """(tool, view, sketch) when a click here could switch the sketch."""
        if not on():
            return None
        from .fwsketch import tool
        running = tool.active()
        if running is None or not running.is_first_state():
            return None
        try:
            if obj is not running.viewport and obj is not running.quarter:
                return None
        except RuntimeError:
            return None
        return running, running.view, running.sketch

    def eventFilter(self, obj, event):
        try:
            if int(event.type()) not in self.wanted:
                return False         # the cheap way out for every other event
        except Exception:
            return False             # Qt can hand filters a QWidgetItem; not an event
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            return self._filter(obj, event)
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD Rapid Sketch: %s" % traceback.format_exc())
            return False

    def _filter(self, obj, event):
        t = event.type()
        QE = QtCore.QEvent
        if t not in (QE.MouseMove, QE.MouseButtonPress, QE.MouseButtonRelease, QE.MouseButtonDblClick, QE.Leave):
            return False
        if t == QE.MouseButtonRelease and self.eat_release and event.button() == QtCore.Qt.LeftButton:
            self.eat_release = False
            return True
        ctx = self._context(obj)
        if ctx is None:
            if self.lit is not None and t in (QE.MouseMove, QE.Leave):
                self._unlight()
            return False
        running, view, sketch = ctx
        if t == QE.Leave:
            self._unlight()
            return False
        from .fwsketch.toolbase import other_buttons
        if other_buttons(event):
            return False         # panning or turning the view
        ctrl = bool(event.modifiers() & QtCore.Qt.ControlModifier)
        found = None if ctrl else face_under(view, sketch)
        if found is not None and t == QE.MouseMove:
            self._light(view, sketch, found)
        elif found is None:
            self._unlight()
        if t in (QE.MouseButtonPress, QE.MouseButtonDblClick) and event.button() == QtCore.Qt.LeftButton \
                and found is not None and not self._snapped(running):
            command = _command_of(running)
            if command is None:
                return False
            self.eat_release = True
            target = (found[0].Document.Name, found[0].Name, found[1])
            self._unlight()
            QtCore.QTimer.singleShot(0, lambda: self.switch(sketch, target, command))
            return True
        return False

    @staticmethod
    def _snapped(running):
        """The tool has found a snap under the pointer (a point, a curve, an axis): the click is
        for it."""
        try:
            from .fwsketch import snap
            d = running.decision
            return d is not None and d.winner not in (snap.FREE, snap.DISABLED, snap.SUPPRESSED)
        except Exception:
            return False

    def _light(self, view, sketch, found):
        key = (found[0].Document.Name, found[0].Name, found[1])
        if key == self.target:
            return
        self._unlight()
        try:
            self.lit = _Lit(view, found[2])
        except Exception:
            self.lit = None
        self.target = key
        _status("Rapid Sketch: click to sketch on %s of %s." % (found[1], found[0].Label))

    def switch(self, sketch, target, command):
        """Close sketch, open a new one on target's face, the same tool running in it."""
        from .fwsketch import tool, sketchfirst
        doc = App.getDocument(target[0])
        obj = doc.getObject(target[1]) if doc is not None else None
        if obj is None:
            return
        self.switches.append((sketch.Name, obj.Name, target[2], command))
        running = tool.active()
        if running is not None:
            running.end()
        gdoc = Gui.getDocument(doc.Name)
        try:
            if gdoc.getInEdit() is not None:
                gdoc.resetEdit()
        except Exception as _fw_err:
            _fw_log("rapidsketch.py:310", _fw_err)

        def open_next():
            sketchfirst.sketch_on(obj, target[2])
            sketchfirst.then_command(command)
            _status("Rapid Sketch: new sketch on %s of %s." % (target[2], obj.Label))
        QtCore.QTimer.singleShot(150, open_next)


class RapidSketchCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_NewSketch", "MenuText": "Rapid Sketch", "Checkable": on(),
                "ToolTip": "Sketch on any flat face: with a sketch tool running, click another face to "
                           "start a new sketch there with the same tool"}

    def IsActive(self):
        state = on()
        try:
            actions = Gui.Command.get(COMMAND).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != state:
                blocked = action.blockSignals(True)
                action.setChecked(state)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None

    def Activated(self, checked=0):
        try:
            has_action = bool(Gui.Command.get(COMMAND).getAction())
        except Exception:
            has_action = False
        state = bool(checked) if has_action else not on()
        App.ParamGet(GENERAL).SetBool(PARAM, state)
        _status("Rapid Sketch is %s." % ("on: with a sketch tool running, click a flat face to sketch there"
                                         if state else "off"))


_rapid = None


def watcher():
    return _rapid


def install():
    global _rapid
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, RapidSketchCommand())
    from . import checkstate
    checkstate.register(COMMAND, on)
    if _rapid is None:
        _rapid = RapidSketch()
