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

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets

from . import naming

COMMAND = "SWStyle_LiveSectionPlane"
TITLE = "Live Section Plane"
TYPE = "FwLiveSectionPlane"


def _sheet(size):
    import Part
    h = size / 2.0
    return Part.Face(Part.makePolygon([App.Vector(-h, -h, 0), App.Vector(h, -h, 0), App.Vector(h, h, 0),
                                       App.Vector(-h, h, 0), App.Vector(-h, -h, 0)]))


class Feature:
    def __init__(self, obj):
        obj.Proxy = self
        if not hasattr(obj, "FwType"):
            obj.addProperty("App::PropertyString", "FwType", "Live Section Plane", "FreeCAD feature type")
            obj.FwType = TYPE
            obj.setPropertyStatus("FwType", ["Hidden"])
        if not hasattr(obj, "Size"):
            obj.addProperty("App::PropertyLength", "Size", "Live Section Plane", "Side of the plane's sheet")
            obj.Size = 100.0
        if not hasattr(obj, "Reference"):
            obj.addProperty("App::PropertyString", "Reference", "Live Section Plane", "The plane or face it was made on")

    def execute(self, obj):
        obj.Shape = _sheet(max(float(obj.Size), 1.0))     # Placement places it

    def onDocumentRestored(self, obj):
        self.__init__(obj)
        if App.GuiUp:
            _restore_later(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_live_plane(obj):
    return getattr(obj, "FwType", "") == TYPE


# ---- the live cut (one per shown feature, on the active 3D view) ----------------------------------

_CUTS = {}          # (doc, obj name) -> sectionview.Section


def _settings_for(obj):
    from . import sectionview
    s = sectionview.Settings()
    s.ref = ("plane", obj.Document.Name, obj.Name)
    s.ref_name = obj.Label
    s.ref_place = App.Placement(obj.Placement)
    s.show_cap = True
    return s


def _active_view(doc=None):
    try:
        gdoc = Gui.getDocument(doc.Name) if doc is not None else Gui.ActiveDocument
        return gdoc.ActiveView if gdoc is not None else None
    except Exception as _fw_err:
        _fw_log("liveplane.py:95", _fw_err)
        return None


def show_cut(obj, on=True):
    ""
    from . import sectionview
    key = (obj.Document.Name, obj.Name)
    cut = _CUTS.pop(key, None)
    if cut is not None:
        try:
            cut.detach()
        except Exception as _fw_err:
            _fw_log("liveplane.py:106", _fw_err)
    if not on or sectionview.coin is None:
        return None
    view = _active_view(obj.Document)
    if view is None or getattr(view.getSceneGraph(), "getNumChildren", None) is None:
        return None
    cut = sectionview.Section(view, _settings_for(obj))

    def dragged(cut=cut, obj=obj):
        # the handles moved the cut: the feature's plane follows, so it is saved where it was left
        point, normal, u, v, n0, place = sectionview.frame(cut.settings)
        try:
            obj.Placement = App.Placement(point, App.Rotation(App.Vector(0, 0, 1), normal * (-1 if cut.settings.reverse else 1)))
        except Exception as _fw_err:
            _fw_log("liveplane.py:120", _fw_err)
    cut.on_drag = dragged
    cut.attach()
    cut.set_editing(True)
    _CUTS[key] = cut
    return cut


def _restore_later(obj, tries=0):
    """An opened part: a shown Live Section Plane cuts again once its window is up."""
    def go():
        try:
            vobj = obj.ViewObject
            if vobj is None or not vobj.Visibility or cut_of(obj) is not None:
                return
            if show_cut(obj, True) is None and tries < 20:
                _restore_later(obj, tries + 1)
        except Exception as _fw_err:
            _fw_log("liveplane.py:138", _fw_err)
    QtCore.QTimer.singleShot(300, go)


def cut_of(obj):
    """The feature's cut, or None (a cut left from a closed window of the same name is dropped)."""
    key = (obj.Document.Name, obj.Name)
    cut = _CUTS.get(key)
    if cut is not None:
        try:
            cut.view.getSceneGraph()
            alive = cut.view is _active_view(obj.Document) or cut.view == _active_view(obj.Document)
        except Exception:
            alive = False
        if not alive:
            _CUTS.pop(key, None)
            return None
    return cut


if App.GuiUp:
    class View:
        def __init__(self, vobj):
            vobj.Proxy = self

        def attach(self, vobj):
            self.Object = vobj.Object
            try:
                vobj.Transparency = 80
                vobj.ShapeAppearance = [App.Material(DiffuseColor=(0.55, 0.75, 1.0))]
            except Exception as _fw_err:
                _fw_log("liveplane.py:169", _fw_err)
            # an opened part: a shown plane cuts again (once the view exists)
            self._tries = 0
            QtCore.QTimer.singleShot(300, lambda vobj=vobj: self._restore(vobj))

        def _restore(self, vobj):
            try:
                obj = vobj.Object
                if not vobj.Visibility or cut_of(obj) is not None:
                    return
                if show_cut(obj, True) is None and self._tries < 20:     # its window is not up yet
                    self._tries += 1
                    QtCore.QTimer.singleShot(300, lambda vobj=vobj: self._restore(vobj))
            except Exception as _fw_err:
                _fw_log("liveplane.py:183", _fw_err)

        def getIcon(self):
            from . import icons
            path = icons.file_of("I3DVIEW_SECT_VIEW") if hasattr(icons, "file_of") else ""
            return path or ":/icons/Std_ToggleClipPlane.svg"

        def onChanged(self, vobj, prop):
            if prop == "Visibility":
                obj = vobj.Object
                QtCore.QTimer.singleShot(0, lambda: show_cut(obj, bool(vobj.Visibility)))

        def updateData(self, obj, prop):
            if prop == "Placement":
                cut = cut_of(obj)
                if cut is not None and cut.settings.ref_place != obj.Placement:
                    cut.settings.ref_place = App.Placement(obj.Placement)
                    cut.settings.offset = cut.settings.rx = cut.settings.ry = 0.0
                    cut.settings.reverse = False
                    cut.update()

        def onDelete(self, vobj, subelements):
            show_cut(vobj.Object, False)
            return True

        def dumps(self):
            return None

        def loads(self, state):
            return None


# ---- the PropertyManager ------------------------------------------------------------------------

def _pick_placement(obj, sub):
    from . import sectionview
    if sub and sub.split(".")[-1].startswith("Face"):
        return sectionview.face_placement(obj, sub)
    return sectionview.plane_placement(obj)


def _model_size(doc):
    box = App.BoundBox()
    for o in doc.Objects:
        shp = getattr(o, "Shape", None)
        if shp is not None and not shp.isNull() and shp.Solids and getattr(o, "Visibility", False):
            box.add(shp.BoundBox)
    return max(box.DiagonalLength * 1.1, 20.0) if box.isValid() else 100.0


class Panel:
    """Live Section Plane PM: Selections (a plane or planar face). OK makes the feature, Cancel nothing."""

    def __init__(self, doc):
        self.doc = doc
        self.pick = None
        page = QtWidgets.QWidget()
        page.setWindowTitle("Selections")
        page.setProperty("swstyle_pm_title", TITLE)
        page.setProperty("swstyle_pm_icon", "I3DVIEW_SECT_VIEW")
        lay = QtWidgets.QVBoxLayout(page)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("SWStyle_LivePlaneRef")
        self.list.setToolTip("Plane or planar face to put the section plane on")
        self.list.setMaximumHeight(60)
        lay.addWidget(self.list)
        self.form = [page]
        for s in Gui.Selection.getSelectionEx():
            for sub in (s.SubElementNames or ("",)):
                if self._take(s.Object, sub):
                    break
            if self.pick:
                break
        if self.pick is None:
            from . import sectionview
            self.pick = ("Front Plane", None, "", sectionview._standard_placement("Front"))
            self.list.addItem("Front Plane")
        Gui.Selection.addObserver(self)

    def _take(self, obj, sub):
        place = _pick_placement(obj, sub)
        if place is None:
            return False
        name = obj.Label + ("@" + sub.split(".")[-1] if sub else "")
        self.pick = (name, obj, sub, place)
        self.list.clear()
        self.list.addItem(name)
        return True

    def addSelection(self, doc, obj, sub, pnt):
        o = App.getDocument(doc).getObject(obj) if doc in App.listDocuments() else None
        if o is not None:
            self._take(o, sub)

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("liveplane.py:281", _fw_err)

    def accept(self):
        self._close()
        obj = make(self.doc, self.pick[3], self.pick[0])
        Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        return obj is not None

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def make(doc, placement, reference=""):
    """A new Live Section Plane on the placement, shown, with the model cut at it."""
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("Part::FeaturePython", "LiveSectionPlane")
        Feature(obj)
        obj.Size = _model_size(doc)
        obj.Reference = reference
        obj.Placement = placement
        obj.Label = naming.next_label(doc, TITLE)
        if App.GuiUp and obj.ViewObject is not None:
            View(obj.ViewObject)
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    if App.GuiUp:
        show_cut(obj, True)
    return obj


class _Command:
    def GetResources(self):
        return {"MenuText": TITLE, "Pixmap": "Std_ToggleClipPlane",
                "ToolTip": "Adds a section plane to the part that cuts the model while it is shown; drag it to move the cut."}

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(Panel(App.ActiveDocument))


def register():
    if not App.GuiUp:
        return
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
