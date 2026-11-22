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

TITLE = "Surface-Plane"
GAP = 1e-4          # ends closer than this count as joined, mm


def _edges(links):
    out = []
    for obj, subs in links or []:
        subs = [s for s in (subs or []) if s] or [""]
        for sub in subs:
            try:
                if not sub:
                    out += [e.copy() for e in obj.Shape.Edges]
                else:
                    g = obj.Shape.getElement(sub)
                    out += [e.copy() for e in g.Edges]
            except Exception:
                continue
    return out


def build(edges):
    """One flat face bounded by edges (several closed loops: the outer one with holes)."""
    import Part
    if not edges:
        raise RuntimeError("Select a closed sketch, or edges that make a closed loop.")
    try:
        groups = Part.sortEdges(edges, GAP)
    except TypeError:
        groups = Part.sortEdges(edges)
    wires = []
    for g in groups:
        w = Part.Wire(g)
        if not w.isClosed():
            try:
                w.fixWire(None, GAP)
            except Exception as _fw_err:
                _fw_log("planarsurface.py:58", _fw_err)
        if not w.isClosed():
            raise RuntimeError("The edges do not make a closed loop: pick the edges all the way round.")
        wires.append(w)
    try:
        face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    except Exception:
        face = Part.Face(wires[0])
    faces = face.Faces
    if not faces or any(type(f.Surface).__name__ != "Plane" for f in faces):
        raise RuntimeError("The loop is not flat: a Planar Surface needs edges in one plane.")
    if len(faces) == 1:
        return faces[0]
    return Part.makeCompound(faces)


class PlanarSurface:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        # Global links: the sketch may sit inside a Body while the surface does not, and a
        # plain link then warns "go out of the allowed scope" on every recompute.
        kept = None
        if "Bounding" in obj.PropertiesList and obj.getTypeIdOfProperty("Bounding") != "App::PropertyLinkSubListGlobal":
            try:
                kept = list(obj.Bounding)
                obj.removeProperty("Bounding")
            except Exception:
                return
        if "Bounding" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLinkSubListGlobal", "Bounding", "Planar Surface",
                            "Bounding entities: a closed sketch, or edges that make a closed loop")
            if kept:
                obj.Bounding = kept

    def execute(self, obj):
        obj.Shape = build(_edges(obj.Bounding))

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
        return ":/icons/Part_MakeFace.svg"

    def claimChildren(self):
        return []

    def doubleClicked(self, vobj):
        return self.setEdit(vobj)

    def setEdit(self, vobj, mode=0):
        """Edit Feature: the Bounding Entities box again, filled with the picks; OK rebuilds."""
        import FreeCADGui as Gui
        from PySide import QtCore
        from . import pickfirst
        obj = vobj.Object
        Gui.Selection.clearSelection()

        def then():
            links = picked_links()
            Gui.Selection.clearSelection()
            if links:
                obj.Document.openTransaction(TITLE)
                try:
                    obj.Bounding = [(o, subs) for o, subs in links.items()]
                    obj.Document.recompute()
                except BaseException:
                    try:
                        obj.Document.abortTransaction()
                    except Exception:
                        pass
                    raise
                obj.Document.commitTransaction()

        def start():
            pickfirst.ask("Planar Surface", "Bounding Entities", ("Sketch", "Edge"), then, box=True)
            panel = getattr(pickfirst, "_LAST", None)
            if panel is not None:
                for o, subs in obj.Bounding:
                    for sub in [s for s in subs if s] or [""]:
                        key = (o.Document.Name, o.Name, sub)
                        if key not in panel.picks:
                            panel.picks.append(key)
                try:
                    panel._fill()
                except Exception as _fw_err:
                    _fw_log("planarsurface.py:153", _fw_err)
        QtCore.QTimer.singleShot(0, start)
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make(doc, links):
    """A Planar Surface from links [(object, [subs])]."""
    from . import naming
    obj = doc.addObject("Part::FeaturePython", "PlanarSurface")
    PlanarSurface(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    try:
        obj.Label = naming.next_label(doc, TITLE)
    except Exception:
        obj.Label = TITLE + "1"
    obj.Bounding = links
    doc.recompute()
    _absorb(obj)
    return obj


def _absorb(obj):
    ""

    if not App.GuiUp or obj.Shape.isNull() or not obj.Shape.Faces:
        return
    for o, subs in obj.Bounding or []:
        if o.isDerivedFrom("Sketcher::SketchObject"):
            try:
                if o.ViewObject is not None:
                    o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("planarsurface._absorb", _fw_err)


def picked_links():
    """{object: [element, ...]} of the selection, each sub path resolved to the object it names: a
    sketch inside a body comes back as (Body, "Outline.") and must be the sketch itself, as in
    simplefeature.preselected."""
    import FreeCADGui as Gui
    links = {}
    for s in Gui.Selection.getSelectionEx("", 0):
        doc = s.Object.Document
        for sub in s.SubElementNames or [""]:
            parts = sub.split(".")
            holder = s.Object
            for name in parts[:-1]:
                found = doc.getObject(name)
                if found is not None:
                    holder = found
            subs = links.setdefault(holder, [])
            if parts[-1] not in subs:
                subs.append(parts[-1])
    return links


def from_selection():
    """The command with the bounding entities picked: makes the surface (one Undo step)."""
    import FreeCADGui as Gui
    doc = App.ActiveDocument
    links = picked_links()
    if doc is None or not links:
        return None
    doc.openTransaction(TITLE)
    obj = make(doc, [(o, subs) for o, subs in links.items()])
    if "Invalid" in obj.State or obj.Shape.isNull():

        text = obj.getStatusString()
        doc.abortTransaction()
        Gui.Selection.clearSelection()
        _ask_again(links, text)
        return None
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    return obj


def open_page():
    ""

    import FreeCADGui as Gui
    links = picked_links()
    Gui.Selection.clearSelection()
    _ask_again(links, "")


def _ask_again(links, text):
    from PySide import QtCore
    from . import pickfirst

    def start():
        pickfirst.ask("Planar Surface", "Bounding Entities", ("Sketch", "Edge"), from_selection, box=True)
        panel = getattr(pickfirst, "_LAST", None)
        if panel is None:
            return
        for o, subs in links.items():
            for sub in [s for s in subs if s] or [""]:
                key = (o.Document.Name, o.Name, sub)
                if key not in panel.picks:
                    panel.picks.append(key)
        try:
            panel._fill()
            if text:
                panel.message.setText(text)
                panel.message.show()
        except Exception as _fw_err:
            _fw_log("planarsurface.py:254", _fw_err)
        QtCore.QTimer.singleShot(150, _view_keys)
    QtCore.QTimer.singleShot(0, start)


def _view_keys():
    ""
    try:
        from PySide import QtWidgets
        from .pmtakeover import view_widget
        viewport = view_widget()
        if viewport is None:
            return
        parent = viewport.parentWidget()
        target = parent if isinstance(parent, QtWidgets.QGraphicsView) else viewport
        target.setFocus()
    except Exception as error:
        App.Console.PrintLog("FreeCAD planarsurface: view focus: %r\n" % error)
