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

PREFIX = "SWStyle_EP_"

# the buttons that did nothing (or were grey) in a part with no solid; the cuts, Hole Wizard and the
# swept and lofted features already start their own flow there (featureflow: plane pick, Hole page, PMs)
NATIVES = {
    "SWStyle_BoundaryCut": "solid", "PartDesign_Fillet": "solid", "PartDesign_Chamfer": "solid",
    "PartDesign_Draft": "solid", "PartDesign_Thickness": "solid", "SWStyle_Wrap": "solid",
    "SWStyle_Intersect": "solid",
    # Insert > Features (features-395): grey in an empty part before
    "SWStyle_Split": "solid", "SWStyle_Dome": "solid", "SWStyle_Thread": "solid", "SWStyle_Scale": "solid",
    "SWStyle_Freeform": "solid", "SWStyle_Deform": "solid", "SWStyle_Flex": "solid", "SWStyle_Indent": "solid",
    "SWStyle_AdvancedHole": "solid", "SWStyle_StudWizard": "solid",
    # Surfaces tab (look audit AJ3): the two cuts need a solid; in a surfaces-only part they were grey
    "SWStyle_ThickenedCut": "solid", "SWStyle_CutWithSurface": "solid",
}

# cuts that need a real solid: surfaces alone are not enough (their own command decides, at the click)
SOLID_ONLY = {"SWStyle_ThickenedCut", "SWStyle_CutWithSurface"}

DATUMS = ("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem",
          "Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint")


def _label(native):
    try:
        from . import catalog
        for c in catalog._ALL:
            if native in c.natives:
                return c.label, c.icon
    except Exception as _fw_err:
        _fw_log("solidfirstlive.py:label", _fw_err)
    return native, None


def _shapes(doc):
    for o in doc.Objects if doc is not None else []:
        if o.TypeId.startswith(("Sketcher::", "App::")) or o.TypeId in DATUMS or not hasattr(o, "Shape"):
            continue        # sketches, the origin and datum planes, axes and points are no body
        try:
            yield o.Shape
        except Exception:
            continue


def has_solid(doc):
    """A solid (or a surface Intersect or Wrap could work on) anywhere in the part."""
    for shape in _shapes(doc):
        try:
            if not shape.isNull() and (shape.Solids or shape.Faces):
                return True
        except Exception:
            continue
    return False


def has_surface(doc):
    """Surface bodies in the part (faces with no solid)."""
    for shape in _shapes(doc):
        try:
            if not shape.isNull() and shape.Faces and not shape.Solids:
                return True
        except Exception:
            continue
    return False


def _native_ready(native, doc):
    try:
        from . import simplefeature as sf
        spec = next((s for s in sf.SPECS.values() if s.command == native and s.needs_body), None)
        if spec is not None:
            return bool(sf.ready(spec, doc))
    except Exception as _fw_err:
        _fw_log("solidfirstlive.py:ready", _fw_err)
    for shape in _shapes(doc):
        try:
            if not shape.isNull() and shape.Solids:
                return True
        except Exception:
            continue
    return False


def ready(native, doc=None):
    """True when the native command can do its own work in this part."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return True
    if native in SOLID_ONLY:
        return _native_ready(native, doc)
    return has_solid(doc)


class SolidFirstPage:
    ""

    def __init__(self, native):
        from PySide import QtWidgets
        self.native = native
        label, icon = _label(native)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", label)
        if icon:
            self.form.setProperty("swstyle_pm_icon", icon)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        surfaces = has_surface(App.ActiveDocument)
        if surfaces:
            text = QtWidgets.QLabel("%s works on a solid body, and the part has only surfaces. Thicken a "
                                    "surface into a solid, or add a boss, then use %s on it." % (label, label))
        else:
            text = QtWidgets.QLabel("%s works on a solid body, and the part has none yet. Start the part with a "
                                    "boss, then use %s on it." % (label, label))
        text.setObjectName("SWSolidFirstMessage")
        text.setWordWrap(True)
        lay.addWidget(text)
        keys = (("Thicken", "SWSolidFirstThicken"),) if surfaces else ()
        for key, name in keys + (("BossExtrude", "SWSolidFirstExtrude"), ("BossRevolve", "SWSolidFirstRevolve")):
            cmd = self._command(key)
            if cmd is None:
                continue
            b = QtWidgets.QPushButton(_key_label(key))
            b.setObjectName(name)
            b.clicked.connect(lambda checked=False, c=cmd: self._start(c))
            lay.addWidget(b)
        lay.addStretch(1)

    def _command(self, key):
        try:
            from . import catalog
            c = catalog.BY_KEY.get(key)
            listed = set(Gui.listCommands())
            return next((n for n in (c.natives if c else ()) if n in listed), None)
        except Exception as _fw_err:
            _fw_log("solidfirstlive.py:command", _fw_err)
            return None

    def _start(self, command, before=None):
        Gui.Control.closeDialog()
        from PySide import QtCore

        def go():
            if before is not None:
                before()
            _run(command)
        QtCore.QTimer.singleShot(200, go)

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Cancel    # sketchfirst-1126: int() of the enum raised in Qt6

    def reject(self):
        Gui.Control.closeDialog()
        return True


class SketchFirstPage(SolidFirstPage):
    ""


    def __init__(self, key):
        from PySide import QtWidgets
        self.native = key
        label, icon = _label_key(key)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", label)
        if icon:
            self.form.setProperty("swstyle_pm_icon", icon)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        text = QtWidgets.QLabel("%s works in a sketch. Open a sketch first (pick one in the FeatureManager design "
                                "tree and use Edit Sketch, or start a new one), then use %s." % (label, label))
        text.setObjectName("SWSketchFirstMessage")
        text.setWordWrap(True)
        lay.addWidget(text)
        has_sketch = any(o.TypeId.startswith("Sketcher::") for o in (App.ActiveDocument.Objects
                                                                     if App.ActiveDocument else ()))
        for k, name in ((("EditSketch", "SWSketchFirstEdit"),) if has_sketch else ()) + (("Sketch", "SWSketchFirstSketch"),):
            cmd = self._command(k)
            if cmd is None:
                continue
            b = QtWidgets.QPushButton(_key_label(k))
            b.setObjectName(name)
            if k == "EditSketch":      # sketchfirst2-1126: Edit Sketch picks the part's last sketch itself
                b.clicked.connect(lambda checked=False, c=cmd: self._start(c, pick_last_sketch))
            else:
                b.clicked.connect(lambda checked=False, c=cmd: self._start(c))
            lay.addWidget(b)
        lay.addStretch(1)


def pick_last_sketch():
    """Selects the last sketch of the active document (Edit Sketch needs one picked); False when there is none."""
    doc = App.ActiveDocument
    sketches = [o for o in (doc.Objects if doc is not None else []) if o.TypeId.startswith("Sketcher::")]
    if not sketches:
        return False
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, sketches[-1].Name)
    return True


def _label_key(key):
    try:
        from . import catalog
        c = catalog.BY_KEY.get(key)
        if c is not None:
            return c.label, c.icon
    except Exception as _fw_err:
        _fw_log("solidfirstlive.py:labelkey", _fw_err)
    return key, None


def sketch_first(key):
    """Show the open-a-sketch-first page for a sketch tool that was clicked with no sketch open (False if a PM is up)."""
    try:
        if Gui.Control.activeDialog():
            return False
    except Exception:
        pass
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(SketchFirstPage(key))
    return True


class BodyFirstPage(SolidFirstPage):
    """bodyfirst-1126: Move/Copy Bodies, Combine, Mirror Body and Delete/Keep Body in a part with no Body (only Part-workbench
    solids, or nothing): a Message page that says what to do, with the buttons that start a boss."""

    def __init__(self, label):
        from PySide import QtWidgets
        self.native = label
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Message")
        self.form.setProperty("swstyle_pm_title", label)
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.setContentsMargins(4, 4, 4, 4)
        text = QtWidgets.QLabel("%s works on the solid bodies made in this part, and it has none yet (a solid brought in "
                                "from the Part workbench is not a body). Start a body with a boss, then use %s on it." %
                                (label, label))
        text.setObjectName("SWBodyFirstMessage")
        text.setWordWrap(True)
        lay.addWidget(text)
        for key, name in (("BossExtrude", "SWSolidFirstExtrude"), ("BossRevolve", "SWSolidFirstRevolve")):
            cmd = self._command(key)
            if cmd is None:
                continue
            b = QtWidgets.QPushButton(_key_label(key))
            b.setObjectName(name)
            b.clicked.connect(lambda checked=False, c=cmd: self._start(c))
            lay.addWidget(b)
        lay.addStretch(1)


def body_first(label):
    """Shows the no-body page; False when a PropertyManager is already open."""
    try:
        if Gui.Control.activeDialog():
            return False
    except Exception:
        pass
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(BodyFirstPage(label))
    return True


def _key_label(key):
    try:
        from . import catalog
        c = catalog.BY_KEY.get(key)
        if c is not None:
            return c.label
    except Exception as _fw_err:
        _fw_log("solidfirstlive.py:key", _fw_err)
    return {"BossExtrude": "Extruded Boss/Base", "BossRevolve": "Revolved Boss/Base", "Thicken": "Thicken"}[key]


class _Live:
    def __init__(self, native):
        self.native = native

    def GetResources(self):
        cmd = Gui.Command.get(self.native)
        info = {}
        try:
            info = cmd.getInfo() if cmd is not None else {}
        except Exception:
            info = {}
        text = info.get("menuText") or ""
        if not text or text == self.native:
            text = _label(self.native)[0]
        # no Accel: the native keeps its own key (two actions on one key would make it ambiguous)
        return {"Pixmap": info.get("pixmap", "") or "", "MenuText": text or self.native,
                "ToolTip": info.get("toolTip", "") or ""}

    def IsActive(self):
        if App.ActiveDocument is None or Gui.Command.get(self.native) is None:
            return False
        if ready(self.native):
            try:
                return bool(Gui.Command.get(self.native).isActive())
            except Exception:
                return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        if ready(self.native):
            _run(self.native)
            return
        if Gui.Control.activeDialog():
            return
        Gui.Selection.clearSelection()
        Gui.Control.showDialog(SolidFirstPage(self.native))


def _run(native):
    ""

    try:
        from . import featureflow
        if featureflow.run(native):
            return
    except Exception as _fw_err:
        _fw_log("solidfirstlive.py:run", _fw_err)
    Gui.runCommand(native, 0)


def wrapper(native):
    return PREFIX + native


def register():
    have = set(Gui.listCommands())
    for native in NATIVES:
        name = wrapper(native)
        if name in have:
            continue
        try:
            Gui.addCommand(name, _Live(native))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
