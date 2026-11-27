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
from . import events
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
TITLE = "Markup"
INK = (0.85, 0.1, 0.1)
ACTIVE = []             # the open Markup page (the Markup tab's Color / Draw / Erase / Select / Touch / Note drive it)


class MarkupObject:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "Camera", "Markup", "The view the markup was drawn in")
        obj.addProperty("App::PropertyLinkList", "Notes", "Markup", "Its notes")
        obj.addProperty("App::PropertyPythonObject", "Strokes", "Markup", "Its strokes, as lists of points")
        obj.Strokes = []

    def execute(self, obj):
        import Part
        edges = []
        for stroke in obj.Strokes or []:
            pts = [V(*p) for p in stroke]
            if len(pts) >= 2:
                edges.append(Part.makePolygon(pts))
        obj.Shape = Part.Compound(edges)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class MarkupView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def claimChildren(self):
        return list(getattr(self.Object, "Notes", []) or [])

    def getIcon(self):
        return "Tree_Annotation"

    def setupContextMenu(self, vobj, menu):
        action = menu.addAction("Go to Markup View")
        action.setObjectName("SWMarkupGoTo")

        def go():
            Gui.ActiveDocument.ActiveView.setCamera(vobj.Object.Camera)
        action.triggered.connect(go)

    def dumps(self):
        return None

    def loads(self, state):
        return None


# --------------------------------------------------------------------------- the Markups folder
class _Folder:
    Type = "FreeWorksMarkups"

    def __init__(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _FolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return "Tree_Annotation"

    def setupContextMenu(self, vobj, menu):
        doc = vobj.Object.Document
        a = menu.addAction("Show Markups")
        a.setObjectName("SWMarkupsShow")
        a.setCheckable(True)
        a.setChecked(shown())
        a.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: set_shown(doc, not shown())))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_folder(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == _Folder.Type


def markups_folder(doc):
    ""
    found = next((o for o in doc.Objects if is_folder(o)), None)
    if found is None:
        found = doc.addObject("App::DocumentObjectGroupPython", "Markups")
        _Folder(found)
        found.Label = "Markups"
        if App.GuiUp:
            _FolderView(found.ViewObject)
    return found


def _params():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks")


def shown():
    """View > Hide/Show > Markups (on by default)."""
    return _params().GetBool("ViewMarkups", True)


def set_shown(doc, on):
    """Shows or hides every markup (its strokes and notes) of the document."""
    _params().SetBool("ViewMarkups", bool(on))
    n = 0
    for o in (doc.Objects if doc is not None else []):
        if is_markup(o):
            for x in [o] + list(getattr(o, "Notes", []) or []):
                try:
                    x.ViewObject.Visibility = bool(on)
                except Exception as _fw_err:
                    _fw_log("markup.py:165", _fw_err)
            n += 1
    return n


class _ViewMarkups:
    def GetResources(self):
        return {"Pixmap": "Tree_Annotation", "MenuText": "Markups", "Checkable": shown(),
                "ToolTip": "Shows or hides the markups"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, checked=None):
        on = (not shown()) if checked is None else bool(checked)
        set_shown(App.ActiveDocument, on)


def is_markup(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "MarkupObject"


def make(doc, strokes, notes, camera):
    """The Markup object: strokes [[(x, y, z)]], notes [(text, (x, y, z))]."""
    obj = doc.addObject("Part::FeaturePython", "Markup")
    MarkupObject(obj)
    obj.Strokes = [[tuple(p) for p in s] for s in strokes]
    obj.Camera = camera
    labels = []
    for text, at in notes:
        a = doc.addObject("App::Annotation", "MarkupNote")
        a.LabelText = [text]
        a.Position = V(*at)
        labels.append(a)
    obj.Notes = labels
    if App.GuiUp:
        MarkupView(obj.ViewObject)
        obj.ViewObject.LineColor = INK
        obj.ViewObject.LineWidth = 3
        for a in labels:
            try:
                a.ViewObject.TextColor = INK
            except Exception as _fw_err:
                _fw_log("markup.py:208", _fw_err)
    obj.Label = "Markup%d" % (1 + sum(1 for o in doc.Objects if is_markup(o) and o is not obj))
    markups_folder(doc).addObject(obj)
    if App.GuiUp and not shown():
        set_shown(doc, False)
    doc.recompute()
    return obj


def _gl_class():
    from . import overridedrag
    return overridedrag._gl_class()


class _Capture(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.stroke = None
        events.register("markup-capture", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove,), self.eventFilter)

    def stop(self):
        self.panel = None
        try:
            events.unregister("markup-capture")
        except Exception as _fw_err:
            _fw_log("markup.py:234", _fw_err)

    def _point(self, widget, pos):
        view = Gui.ActiveDocument.ActiveView
        dpr = widget.devicePixelRatioF()
        x, y = pos.x() * dpr, view.getSize()[1] - pos.y() * dpr
        p = view.getPoint((int(round(x)), int(round(y))))
        return (p.x, p.y, p.z)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        panel = self.panel
        if panel is None or not isinstance(obj, _gl_class()):
            return False
        if not panel.alive():
            self.stop()          # the page closed some other way: let go before touching it
            return False
        try:
            return self._handle(panel, obj, event)
        except RuntimeError:
            # the page went away without OK or Cancel (another command closed it): let go
            self.stop()
            return False

    def _handle(self, panel, obj, event):
        t = event.type()
        QE = QtCore.QEvent
        if panel.select_mode.isChecked():
            return False                      # Select: the model is picked as usual
        if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            if panel.erase_mode.isChecked():
                panel.erase_at(self._point(obj, event.position()))
            elif panel.note_mode.isChecked():
                panel.add_note(self._point(obj, event.position()))
            else:
                self.stroke = [self._point(obj, event.position())]
            return True
        if t == QE.MouseMove and self.stroke is not None:
            self.stroke.append(self._point(obj, event.position()))
            panel.preview(self.stroke)
            return True
        if t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if self.stroke is not None:
                stroke, self.stroke = self.stroke, None
                if len(stroke) >= 2:
                    panel.add_stroke(stroke)
                panel.preview(None)
            return True
        return False


class MarkupPanel:
    def __init__(self, doc):
        from pivy import coin
        self.doc = doc
        self.view = Gui.ActiveDocument.ActiveView
        self.camera = self.view.getCamera()
        self.marks = []         # ("stroke", points) or ("note", text, point)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(TITLE)
        self.form.setProperty("swstyle_pm_title", TITLE)
        lay = QtWidgets.QVBoxLayout(self.form)
        self.draw_mode = QtWidgets.QRadioButton("Draw")
        self.draw_mode.setObjectName("SWMarkupDraw")
        self.draw_mode.setChecked(True)
        self.note_mode = QtWidgets.QRadioButton("Note")
        self.note_mode.setObjectName("SWMarkupNote")
        self.erase_mode = QtWidgets.QRadioButton("Erase")
        self.erase_mode.setObjectName("SWMarkupErase")
        self.select_mode = QtWidgets.QRadioButton("Select")
        self.select_mode.setObjectName("SWMarkupSelect")
        for w in (self.draw_mode, self.erase_mode, self.select_mode, self.note_mode):
            lay.addWidget(w)
        colour_btn = QtWidgets.QPushButton("Color...")
        colour_btn.setObjectName("SWMarkupColor")
        colour_btn.clicked.connect(self.pick_colour)
        lay.addWidget(colour_btn)
        self.text_label = QtWidgets.QLabel("Note text:")
        self.text_label.setObjectName("SWMarkupTextLabel")
        lay.addWidget(self.text_label)
        self.text = QtWidgets.QLineEdit()
        self.text.setObjectName("SWMarkupText")
        self.text.setPlaceholderText("Note text")
        lay.addWidget(self.text)
        for w in (self.text_label, self.text):      # the note's text: shown while Note is on
            w.setVisible(False)
            self.note_mode.toggled.connect(w.setVisible)
        undo = QtWidgets.QPushButton("Undo Last")
        undo.setObjectName("SWMarkupUndo")
        undo.clicked.connect(self.undo_last)
        lay.addWidget(undo)
        self.info = QtWidgets.QLabel("Drag over the model to draw; with Note on, click where the note goes.")
        self.info.setObjectName("SWMarkupInfo")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.root = coin.SoSeparator()
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(3)
        colour = coin.SoBaseColor()
        colour.rgb.setValue(*INK)
        self.colour = colour
        self.root.addChild(style)
        self.root.addChild(colour)
        self.kept = coin.SoSeparator()
        self.live = coin.SoSeparator()
        self.root.addChild(self.kept)
        self.root.addChild(self.live)
        self.view.getSceneGraph().addChild(self.root)
        self.capture = _Capture(self)
        ACTIVE[:] = [self]
        # however the page goes (OK, Cancel, another command closing the task dialog, the document
        # closing), the 3D-view filter goes with it
        self.form.destroyed.connect(lambda *a: self._gone())

    def set_mode(self, mode):
        {"draw": self.draw_mode, "erase": self.erase_mode, "select": self.select_mode,
         "note": self.note_mode}[mode].setChecked(True)
        if mode == "note":
            self.text.setFocus()

    def set_colour(self, rgb):
        self.colour.rgb.setValue(*rgb)

    def pick_colour(self):
        try:
            c = self.colour.rgb[0].getValue()
            start = QtGui.QColor.fromRgbF(c[0], c[1], c[2])
        except Exception:
            start = QtGui.QColor.fromRgbF(*INK)
        chosen = QtWidgets.QColorDialog.getColor(start, Gui.getMainWindow(), "Markup Color")
        if chosen.isValid():
            self.set_colour((chosen.redF(), chosen.greenF(), chosen.blueF()))

    def erase_at(self, at):
        """Erase: the mark nearest the click goes."""
        if not self.marks:
            return
        p = V(*at)

        def dist(mark):
            pts = mark[1] if mark[0] == "stroke" else [mark[2]]
            return min((V(*q) - p).Length for q in pts)
        nearest = min(self.marks, key=dist)
        self.marks.remove(nearest)
        self._redraw()

    def _lines(self, pts):
        from pivy import coin
        sep = coin.SoSeparator()
        c = coin.SoCoordinate3()
        c.point.setValues(0, len(pts), pts)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, 1, [len(pts)])
        sep.addChild(c)
        sep.addChild(ls)
        return sep

    def _text(self, text, at):
        from pivy import coin
        sep = coin.SoSeparator()
        t = coin.SoTranslation()
        t.translation.setValue(*at)
        label = coin.SoText2()
        label.string.setValue(text)
        sep.addChild(t)
        sep.addChild(label)
        return sep

    def _redraw(self):
        self.kept.removeAllChildren()
        for mark in self.marks:
            self.kept.addChild(self._lines(mark[1]) if mark[0] == "stroke" else self._text(mark[1], mark[2]))

    def preview(self, stroke):
        self.live.removeAllChildren()
        if stroke and len(stroke) >= 2:
            self.live.addChild(self._lines(stroke))

    def add_stroke(self, stroke):
        self.marks.append(("stroke", stroke))
        self._redraw()

    def add_note(self, at):
        text = self.text.text().strip()
        if not text:
            self.info.setText("Type the note's text first.")
            return
        self.marks.append(("note", text, at))
        self._redraw()

    def undo_last(self):
        if self.marks:
            self.marks.pop()
            self._redraw()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _gone(self):
        """The page's widgets are going: no more events reach it, its preview leaves the view."""
        if ACTIVE and ACTIVE[0] is self:
            ACTIVE[:] = []
        try:
            self.capture.stop()
        except Exception as _fw_err:
            _fw_log("markup.py:434", _fw_err)
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("markup.py:438", _fw_err)

    def alive(self):
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        try:
            return shiboken.isValid(self.form) and shiboken.isValid(self.select_mode)
        except Exception as _fw_err:
            _fw_log("markup.py:449", _fw_err)
            return False

    def _close(self):
        self._gone()
        Gui.Control.closeDialog()

    def accept(self):
        if self.marks:
            self.doc.openTransaction(TITLE)
            try:
                make(self.doc, [m[1] for m in self.marks if m[0] == "stroke"],
                     [(m[1], m[2]) for m in self.marks if m[0] == "note"], self.camera)
            finally:
                self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


class _Command:
    def GetResources(self):
        return {"Pixmap": "Tree_Annotation", "MenuText": TITLE,
                "ToolTip": "Draws freehand marks and notes over the model, kept with the view"}

    def IsActive(self):
        return Gui.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(MarkupPanel(doc)))


class _GoTo:
    def GetResources(self):
        return {"Pixmap": "view-isometric", "MenuText": "Go to Markup View",
                "ToolTip": "Turns the view back to the one the picked markup was drawn in"}

    def IsActive(self):
        return any(is_markup(o) for o in Gui.Selection.getSelection())

    def Activated(self):
        for o in Gui.Selection.getSelection():
            if is_markup(o) and o.Camera:
                Gui.ActiveDocument.ActiveView.setCamera(o.Camera)
                return


class _Mode:
    """The Markup tab's Draw / Erase / Select / Touch / Note / Color: the Markup page opens if it is not."""

    TEXT = {"draw": ("Draw", "Draws freehand marks over the model"), "erase": ("Erase", "Erases the mark you click"),
            "select": ("Select", "Picks the model while the markup stays open"),
            "touch": ("Touch", "Draws with a finger or pen on a touch screen"),
            "note": ("Note", "Puts a note where you click"), "colour": ("Color", "The color of the marks")}

    def __init__(self, mode):
        self.mode = mode

    def GetResources(self):
        text, tip = self.TEXT[self.mode]
        return {"MenuText": text, "ToolTip": tip}

    def IsActive(self):
        if ACTIVE and not ACTIVE[0].alive():
            ACTIVE[0]._gone()
        return Gui.ActiveDocument is not None and (bool(ACTIVE) or not Gui.Control.activeDialog())

    def _apply(self):
        if not ACTIVE:
            return
        panel = ACTIVE[0]
        if not panel.alive():
            panel._gone()
            return
        if self.mode == "colour":
            panel.pick_colour()
        else:
            panel.set_mode("draw" if self.mode == "touch" else self.mode)

    def Activated(self):
        if ACTIVE:
            self._apply()
            return
        doc = App.ActiveDocument
        Gui.Control.showDialog(MarkupPanel(doc))
        QtCore.QTimer.singleShot(0, self._apply)


MODES = ("draw", "erase", "select", "touch", "note", "colour")


def register():
    for mode in MODES:
        name = "SWStyle_Markup" + ("Color" if mode == "colour" else mode.capitalize())
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Mode(mode))
    if "SWStyle_Markup" not in Gui.listCommands():
        Gui.addCommand("SWStyle_Markup", _Command())
    if "SWStyle_ViewMarkups" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ViewMarkups", _ViewMarkups())
    if "SWStyle_GoToMarkupView" not in Gui.listCommands():
        Gui.addCommand("SWStyle_GoToMarkupView", _GoTo())
