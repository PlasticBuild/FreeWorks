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

FOLDER_TYPE = "SWStyle::SurfaceBodies"
ROW_TYPE = "SWStyle::SurfaceBody"
# features that change the surfaces they use (the body goes on in them)
CONSUMERS = ("Knit", "Trim", "Extend", "Untrim", "SurfaceFillet", "SurfaceChamfer", "DeleteFace", "DeleteHole",
             "Delete Face", "Delete Hole", "Surface-Fillet", "Surface-Chamfer", "Surface-Trim", "Surface-Knit",
             "Surface-Extend", "Surface-Untrim")
NOT_BODIES = ("Sketcher::SketchObject", "PartDesign::Body", "App::Origin", "App::Line", "App::Plane",
              "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point", "PartDesign::CoordinateSystem",
              "Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint", "App::DocumentObjectGroup",
              "PartDesign::ShapeBinder", "PartDesign::SubShapeBinder")


def _kind(obj):
    text = str(getattr(obj, "SWStyleKind", "") or "")
    try:
        text += " " + type(obj.Proxy).__name__
    except Exception as _fw_err:
        _fw_log("surfacebodies.py:45", _fw_err)
    return text + " " + obj.Name


def _helper(obj):
    try:
        if getattr(getattr(obj, "Proxy", None), "Type", None) in (FOLDER_TYPE, ROW_TYPE):
            return True
        from . import multibody
        return multibody.is_helper(obj)
    except Exception:
        return False


def is_surface_body(obj):
    """A feature whose result is a surface body: faces, no solid, not a sketch, plane or body feature."""
    try:
        if obj.TypeId in NOT_BODIES or obj.isDerivedFrom("Part::Part2DObject") or _helper(obj):
            return False
        if obj.isDerivedFrom("PartDesign::Feature") or obj.isDerivedFrom("App::DocumentObjectGroup"):
            return False
        if "Invalid" in obj.State and (obj.Shape.isNull()):
            return False
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull() or not shape.Faces or shape.Solids:
            return False
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        if body is not None and body.TypeId == "PartDesign::Body" and obj in getattr(body, "Group", []):
            return False      # a body's own (solid) step
        return not obj.Name.startswith(("Preview", "SWPreview", "SWStylePreview"))
    except Exception:
        return False


def _consumed(obj):
    """True when a later surface feature that changes surfaces (Knit, Trim ...) took this one."""
    for user in getattr(obj, "InList", []) or []:
        if user is obj or _helper(user):
            continue
        try:
            made = getattr(user, "Shape", None) is not None and not user.isDerivedFrom("Part::Part2DObject")
        except Exception:
            made = False
        # Knit with Create solid takes them too: the solid goes on in Solid Bodies
        if made and any(w in _kind(user) for w in CONSUMERS):
            return True
    return False


def bodies(doc):
    """The part's surface bodies now, in tree order: the features that last made or changed each."""
    return [o for o in doc.Objects if is_surface_body(o) and not _consumed(o)]


def folder(doc):
    for obj in doc.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == FOLDER_TYPE:
            return obj
    return None


def rows(doc):
    return [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "Type", None) == ROW_TYPE]


def source(row):
    try:
        return row.Document.getObject(row.SourceName)
    except Exception:
        return None


class Folder:
    Type = FOLDER_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        if "Count" not in obj.PropertiesList:
            obj.addProperty("App::PropertyInteger", "Count", "Surface Bodies", "Number of surface bodies")
            obj.setEditorMode("Count", 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class FolderView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            from . import multibody
            return multibody._icon("folder")
        except Exception:
            return ""

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        try:
            return [r for r in rows(obj.Document) if r.ViewObject is None or r.ViewObject.ShowInTree]
        except Exception:
            return []

    def setupContextMenu(self, vobj, menu):
        from PySide import QtGui
        bodies_now = [source(r) for r in rows(vobj.Object.Document)]
        bodies_now = [b for b in bodies_now if b is not None]
        shown = any(b.ViewObject.Visibility for b in bodies_now if b.ViewObject is not None)
        act = QtGui.QAction("Hide Bodies" if shown else "Show Bodies", menu)
        act.triggered.connect(lambda: show_all(vobj.Object.Document, not shown))
        menu.addAction(act)
        return True

    def onDelete(self, vobj, subelements):
        return False

    def canDragObjects(self):
        return False

    def canDropObjects(self):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


class Row:
    Type = ROW_TYPE

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        if "SourceName" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "SourceName", "Surface Body", "The feature that made this body")
            obj.setEditorMode("SourceName", 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class RowView:
    """A surface body's row: its eye hides and shows the body, a click selects it."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        from pivy import coin
        vobj.addDisplayMode(coin.SoGroup(), "Default")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        src = source(getattr(self, "Object", None)) if getattr(self, "Object", None) is not None else None
        try:
            if src is not None and src.ViewObject is not None and src.ViewObject.Icon is not None:
                import tempfile
                import os
                path = os.path.join(tempfile.gettempdir(), "swstyle-surfacebody-64.png")   # hidpi-1119: 64 px
                if not os.path.exists(path):
                    src.ViewObject.Icon.pixmap(64, 64).save(path)
                return path
        except Exception as _fw_err:
            _fw_log("surfacebodies.py:252", _fw_err)
        return ":/icons/Part_Feature.svg"

    def onChanged(self, vobj, prop):
        if prop != "Visibility":
            return
        src = source(vobj.Object)
        try:
            if src is not None and src.ViewObject is not None and src.ViewObject.Visibility != vobj.Visibility:
                src.ViewObject.Visibility = vobj.Visibility
        except Exception as _fw_err:
            _fw_log("surfacebodies.py:263", _fw_err)

    def doubleClicked(self, vobj):
        select(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        from PySide import QtGui
        src = source(vobj.Object)
        if src is None or src.ViewObject is None:
            return True
        shown = src.ViewObject.Visibility
        act = QtGui.QAction("Hide" if shown else "Show", menu)
        act.triggered.connect(lambda: setattr(vobj, "Visibility", not shown))
        menu.addAction(act)
        go = QtGui.QAction("Go To Feature", menu)
        go.triggered.connect(lambda: select(vobj.Object))
        menu.addAction(go)
        return True

    def onDelete(self, vobj, subelements):
        return False

    def canDragObjects(self):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def select(row):
    """Selects the body (its feature) in the view and the tree."""
    src = source(row)
    if src is None:
        return False
    try:
        import FreeCADGui as Gui
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(src.Document.Name, src.Name)
        return True
    except Exception:
        return False


def show_all(doc, on):
    for r in rows(doc):
        src = source(r)
        try:
            if src is not None and src.ViewObject is not None:
                src.ViewObject.Visibility = on
                r.ViewObject.Visibility = on
        except Exception as _fw_err:
            _fw_log("surfacebodies.py:318", _fw_err)


def _make(doc, kind):
    obj = doc.addObject("App::FeaturePython", "SurfaceBodies" if kind == "folder" else "SurfaceBody")
    (Folder if kind == "folder" else Row)(obj)
    if App.GuiUp:
        (FolderView if kind == "folder" else RowView)(obj.ViewObject)
    if kind == "folder":
        obj.Label = "Surface Bodies"
    return obj


def ensure_folder(doc):
    """For a new part: the folder first, above Solid Bodies, hidden until there is a surface body."""
    box = folder(doc)
    if box is None:
        box = _make(doc, "folder")
        if App.GuiUp:
            box.ViewObject.ShowInTree = False
        box.purgeTouched()
    return box


def _label(obj, text):
    try:
        from . import multibody
        multibody._set_label(obj, text)
    except Exception:
        if obj.Label != text:
            obj.Label = text


def sync(doc):
    """Brings the folder and its rows up to date with the surface bodies."""
    if doc is None:
        return
    try:
        if doc.Restoring or getattr(doc, "Recomputing", False):
            return
    except Exception:
        return
    found = bodies(doc)
    box = folder(doc)
    if box is None and not found:
        return
    if box is None:
        box = _make(doc, "folder")
    have = {r.SourceName: r for r in rows(doc)}
    names = [o.Name for o in found]
    for o in found:
        r = have.get(o.Name)
        if r is None:
            r = _make(doc, "row")
            r.SourceName = o.Name
        _label(r, o.Label)
        if App.GuiUp and r.ViewObject is not None:
            if not r.ViewObject.ShowInTree:
                r.ViewObject.ShowInTree = True
            try:
                on = bool(o.ViewObject.Visibility)
                if r.ViewObject.Visibility != on:
                    r.ViewObject.Visibility = on
            except Exception as _fw_err:
                _fw_log("surfacebodies.py:382", _fw_err)
    for name, r in have.items():
        if name not in names:
            try:
                doc.removeObject(r.Name)
            except Exception as _fw_err:
                _fw_log("surfacebodies.py:388", _fw_err)
    count = len(found)
    if box.Count != count:
        box.Count = count
    _label(box, "Surface Bodies(%d)" % count)
    if App.GuiUp and box.ViewObject is not None and box.ViewObject.ShowInTree != bool(count):
        box.ViewObject.ShowInTree = bool(count)
    for obj in [box] + rows(doc):
        try:
            obj.purgeTouched()
        except Exception as _fw_err:
            _fw_log("surfacebodies.py:399", _fw_err)


_pending = set()


def later(doc):
    if doc is None or doc.Name in _pending:
        return
    _pending.add(doc.Name)

    def run(name=doc.Name):
        _pending.discard(name)
        try:
            d = App.getDocument(name)
        except Exception:
            return
        try:
            sync(d)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Surface Bodies not updated: %s\n" % error)
    try:
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, run)
    except Exception:
        run()


class _Observer:
    def slotRecomputedDocument(self, doc):
        later(doc)

    def slotFinishRestoreDocument(self, doc):
        later(doc)

    def slotDeletedObject(self, obj):
        try:
            if getattr(getattr(obj, "Proxy", None), "Type", None) not in (FOLDER_TYPE, ROW_TYPE):
                later(obj.Document)
        except Exception as _fw_err:
            _fw_log("surfacebodies.py:439", _fw_err)

    def slotUndoDocument(self, doc):
        later(doc)

    def slotRedoDocument(self, doc):
        later(doc)


_observer = []


def install():
    if not _observer:
        _observer.append(_Observer())
        App.addDocumentObserver(_observer[0])
