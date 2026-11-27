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
from PySide import QtCore

COMMAND = "SWStyle_Cartoon"

VERTEX = """
varying vec3 N;
varying vec4 C;
void main()
{
    N = normalize(gl_NormalMatrix * gl_Normal);
    C = gl_Color;
    gl_Position = ftransform();
}
"""

FRAGMENT = """
varying vec3 N;
varying vec4 C;
void main()
{
    vec3 n = normalize(N);
    if (!gl_FrontFacing)
        n = -n;
    float d = max(dot(n, normalize(vec3(-0.45, 0.6, 0.75))), 0.0);
    float k = d > 0.75 ? 1.0 : (d > 0.35 ? 0.78 : 0.55);
    gl_FragColor = vec4(C.rgb * k, C.a);
}
"""

_on = {}            # id(view) -> _Cartoon


class _Cartoon:
    def __init__(self, view):
        from pivy import coin
        self.view = view
        self.root = view.getSceneGraph()
        self.shader = coin.SoShaderProgram()
        vs = coin.SoVertexShader()
        vs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        vs.sourceProgram = VERTEX
        fs = coin.SoFragmentShader()
        fs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        fs.sourceProgram = FRAGMENT
        self.shader.shaderObject.set1Value(0, vs)
        self.shader.shaderObject.set1Value(1, fs)
        # The outline: the model drawn again as thick black lines, back faces only, so that only
        # its edges and the outline of curved faces show past the faces in front.
        self.outline = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        style = coin.SoDrawStyle()
        style.style = coin.SoDrawStyle.LINES
        style.lineWidth = 3
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        black = coin.SoBaseColor()
        black.rgb.setValue(0.0, 0.0, 0.0)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.CLOCKWISE
        hints.shapeType = coin.SoShapeHints.SOLID
        for node in (pick, style, light, black, hints):
            node.setOverride(True)
            self.outline.addChild(node)
        self.models = coin.SoGroup()
        self.outline.addChild(self.models)
        self.root.insertChild(self.shader, 0)
        self.root.addChild(self.outline)
        self.seen = None
        self.refresh()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    def _children(self):
        return [self.root.getChild(i) for i in range(self.root.getNumChildren())
                if self.root.getChild(i) not in (self.shader, self.outline)]

    def refresh(self):
        """Outlines what the view shows now (objects come and go)."""
        try:
            kids = self._children()
        except Exception:
            self.stop()
            return
        key = [id(k) for k in kids]
        if key == self.seen:
            return
        self.seen = key
        self.models.removeAllChildren()
        for k in kids:
            self.models.addChild(k)

    def stop(self):
        self.timer.stop()
        for node in (self.shader, self.outline):
            try:
                self.root.removeChild(node)
            except Exception as _fw_err:
                _fw_log("cartoon.py:123", _fw_err)
        _on.pop(id(self.view), None)


def active(view=None):
    view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None)
    return view is not None and id(view) in _on


def set_cartoon(on, view=None):
    view = view or Gui.ActiveDocument.ActiveView
    if on and id(view) not in _on:
        _on[id(view)] = _Cartoon(view)
    elif not on and id(view) in _on:
        _on[id(view)].stop()
    _sync()


def _sync():
    """The Cartoon buttons and menu tick follow the state now, not at FreeCAD's next update: a
    toggle from the heads-up strip, then the View > Display entry, turns it back off."""
    state = active()
    try:
        actions = Gui.Command.get(COMMAND).getAction()
    except Exception:
        actions = []
    for action in actions:
        if action.isCheckable() and action.isChecked() != state:
            blocked = action.blockSignals(True)
            action.setChecked(state)
            action.blockSignals(blocked)


class _Toggle:
    def GetResources(self):
        return {"MenuText": "Cartoon", "Pixmap": "DrawStyleFlatLines",
                "ToolTip": "Draws the model in flat bands of color with thick black outlines",
                "Checkable": False, "CmdType": "ForEdit"}      # extapps77: also while a sketch is open

    def Activated(self, checked=None):
        if Gui.ActiveDocument is None or not hasattr(Gui.ActiveDocument.ActiveView, "getSceneGraph"):
            return
        # from a menu or button: checked says which way; run without one (a macro): it toggles
        set_cartoon(not active() if checked is None else bool(checked))

    def IsActive(self):
        if Gui.ActiveDocument is None or not hasattr(Gui.ActiveDocument.ActiveView, "getSceneGraph"):
            return False
        _sync()
        return True


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Toggle())
    try:
        from . import checkstate
        checkstate.register(COMMAND, active)       # ticked/pressed from the state, as the View Settings switches
    except Exception as _fw_err:
        _fw_log("cartoon.py:checkstate", _fw_err)
