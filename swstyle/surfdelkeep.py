# SPDX-License-Identifier: LGPL-2.1-or-later
""









import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

TITLE = "Body-Delete/Keep"


def _log(site, err):
    App.Console.PrintLog("FreeCAD: surfdelkeep %s: %r\n" % (site, err))


def surface_bodies(doc, skip=None):
    """The part's bodies outside any Part Design body (surface bodies and loose solids), in tree order."""
    from . import mirrorpm
    out = []
    for o in doc.Objects:
        if o is skip or o.TypeId == "PartDesign::Body" or getattr(o, "Proxy", None).__class__ is Feature:
            continue
        if mirrorpm.free_body(o, None) and not o.InList:
            out.append(o)
    return out


def applies(doc):
    """No Part Design body, and surface bodies to work on."""
    if doc is None:
        return False
    if any(o.TypeId == "PartDesign::Body" for o in doc.Objects):
        return False
    return bool(surface_bodies(doc))


class Feature:
    Type = "SWStyle::SurfaceDeleteKeep"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        if "Bodies" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkList", "Bodies", TITLE, "Bodies to Delete/Keep")
        if "Keep" not in obj.PropertiesList:
            obj.addProperty("App::PropertyBool", "Keep", TITLE, "Keep Bodies: every other surface body is taken out")
        if "Removed" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkListHidden", "Removed", TITLE, "The bodies taken out of the part")

    def removed(self, obj):
        listed = [b for b in obj.Bodies if b is not None]
        if not obj.Keep:
            return listed
        return [b for b in surface_bodies(obj.Document, obj) if b not in listed and b not in (obj.Removed or [])] + \
            [b for b in (obj.Removed or []) if b not in listed]

    def execute(self, obj):
        gone = self.removed(obj)
        if list(obj.Removed or []) != gone:
            obj.Removed = gone
        import Part
        obj.Shape = Part.Shape()
        if App.GuiUp:
            for b in gone:
                try:
                    b.ViewObject.Visibility = False
                except Exception as err:
                    _log("hide", err)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import multibody
            return multibody._icon("delete")
        except Exception:
            return ""

    def claimChildren(self):
        try:
            return list(self.Object.Removed or [])
        except Exception:
            return []

    def onDelete(self, vobj, subs):
        for b in list(vobj.Object.Removed or []):        # the bodies come back
            try:
                b.ViewObject.Visibility = True
            except Exception as err:
                _log("show", err)
        return True

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object, new=False))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc, bodies=(), keep=False):
    from . import naming
    obj = doc.addObject("Part::FeaturePython", "BodyDeleteKeep")
    Feature(obj)
    if App.GuiUp:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, TITLE)
    obj.Bodies = list(bodies)
    obj.Keep = bool(keep)
    doc.recompute()
    return obj


def _picked(doc):
    out = []
    try:
        for s in Gui.Selection.getSelectionEx(doc.Name):
            o = s.Object
            if o is not None and o in surface_bodies(doc) and o not in out:
                out.append(o)
    except Exception as err:
        _log("picked", err)
    return out


def start(doc):
    """The Delete/Keep Body command in a part of surface bodies: the feature and its page."""
    picks = _picked(doc)
    doc.openTransaction(TITLE)
    obj = make(doc, picks)
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(Panel(obj, new=True))
    return obj


class Panel:
    ""

    def __init__(self, obj, new):
        self.doc = obj.Document
        self.name = obj.Name
        self.new = new
        if not new:
            self.doc.openTransaction("Edit " + obj.Label)
        groups = []
        for title in ("Type", "Bodies to Delete/Keep"):
            g = QtWidgets.QWidget()
            g.setWindowTitle(title)
            QtWidgets.QVBoxLayout(g)
            groups.append(g)
        groups[0].setProperty("swstyle_pm_title", TITLE)
        self.delete = QtWidgets.QRadioButton("Delete Bodies")
        self.keep = QtWidgets.QRadioButton("Keep Bodies")
        (self.keep if obj.Keep else self.delete).setChecked(True)
        self.keep.toggled.connect(self._set_keep)
        groups[0].layout().addWidget(self.delete)
        groups[0].layout().addWidget(self.keep)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_SurfaceDeleteKeepBodies")
        self.list.setMaximumHeight(90)
        try:
            from . import pmboxes                  # the list's right-click Delete / Clear Selections
            pmboxes.bind(self.list, self._remove_row, self._clear)
        except Exception as err:
            _log("bind", err)
        groups[1].layout().addWidget(self.list)
        self.form = groups
        self._fill()
        Gui.Selection.addObserver(self)

    def obj(self):
        return self.doc.getObject(self.name)

    def _fill(self):
        self.list.clear()
        o = self.obj()
        for b in (o.Bodies if o is not None else []):
            self.list.addItem(b.Label)

    def _set_keep(self, on):
        o = self.obj()
        if o is not None:
            o.Keep = bool(on)
            self.doc.recompute()

    def _clear(self):
        o = self.obj()
        if o is not None:
            self._show(o.Removed)
            o.Bodies = []
            self.doc.recompute()
            self._fill()

    def _remove_row(self, row):
        o = self.obj()
        if o is not None and 0 <= row < len(o.Bodies):
            self._show(o.Removed)
            bodies = list(o.Bodies)
            del bodies[row]
            o.Bodies = bodies
            self.doc.recompute()
            self._fill()

    def _show(self, bodies):
        for b in list(bodies or []):
            try:
                b.ViewObject.Visibility = True
            except Exception as err:
                _log("show", err)

    def addSelection(self, doc, name, sub, _pos):
        if doc != self.doc.Name:
            return
        o, picked = self.obj(), self.doc.getObject(name)
        if o is None or picked is None or picked is o:
            return
        bodies = list(o.Bodies)
        if picked in bodies:
            bodies.remove(picked)              # a second click takes it off the list
        elif picked in surface_bodies(self.doc, o):
            bodies.append(picked)
        else:
            return
        self._show(o.Removed)
        o.Bodies = bodies
        self.doc.recompute()
        self._fill()
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)

    def _done(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as err:
            _log("observer", err)

    def getStandardButtons(self):
        return int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

    def accept(self):
        o = self.obj()
        if o is None or not o.Bodies:
            App.Console.PrintWarning("Delete/Keep Body: pick the bodies to delete or keep\n")
            return False
        self._done()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception as err:
            _log("reset", err)
        return True

    def reject(self):
        self._done()
        o = self.obj()
        if o is not None:
            self._show(o.Removed)
        self.doc.abortTransaction()
        o = self.obj()
        if self.new and o is not None:         # Cancel on a new feature leaves nothing
            self.doc.removeObject(self.name)
        self.doc.recompute()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception as err:
            _log("reset", err)
        return True
