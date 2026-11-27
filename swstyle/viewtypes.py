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

from . import checkstate

# type key -> (menu text, tooltip, test on a document object)
TYPES = {
    "Planes": ("View Planes", "Shows or hides all planes.",
               lambda o: o.isDerivedFrom("App::Plane") or o.TypeId == "PartDesign::Plane"),
    "Axes": ("View Axes", "Shows or hides all axes.",
             lambda o: o.isDerivedFrom("App::Line") or o.TypeId == "PartDesign::Line"),
    "Origins": ("View Origins", "Shows or hides the origins.",
                lambda o: o.isDerivedFrom("App::Point") and any(p.isDerivedFrom("App::Origin") for p in o.InList)),
    "CoordinateSystems": ("View Coordinate Systems", "Shows or hides all coordinate systems.",
                          lambda o: o.TypeId in ("PartDesign::CoordinateSystem", "Part::LocalCoordinateSystem")),
    "Points": ("View Points", "Shows or hides all reference points.",
               lambda o: o.TypeId == "PartDesign::Point" or (o.isDerivedFrom("App::Point")
                                                             and not any(p.isDerivedFrom("App::Origin") for p in o.InList))),
    "Sketches": ("View Sketches", "Shows or hides all sketches, also those used by features.",
                 lambda o: o.isDerivedFrom("Sketcher::SketchObject")),
    "Curves": ("View Curves", "Shows or hides curves (helices, composite curves, curves through points).",
               lambda o: o.TypeId in ("Part::Helix", "Part::Spiral") or getattr(o, "SWCurve", False)),
    "PrimaryPlanes": ("View Primary Planes", "Shows or hides the Front, Top and Right planes only.",
                      lambda o: o.isDerivedFrom("App::Plane") and any(p.isDerivedFrom("App::Origin") for p in o.InList)),
    "CenterOfMass": ("View Center of Mass", "Shows or hides the Center of Mass point.",
                     lambda o: type(getattr(o, "Proxy", None)).__name__ == "CenterOfMass"),
    "BoundingBox": ("View Bounding Box", "Shows or hides the Bounding Box.",
                    lambda o: type(getattr(o, "Proxy", None)).__name__ == "BoundingBox"),

    "BendLines": ("Bend Lines", "Shows or hides the bend lines of the flat pattern.",
                  lambda o: any(getattr(p, "BendLines", None) is o for p in o.InList)),
    "WeldBead": ("Weld Bead", "Shows or hides all weld beads.",
                 lambda o: type(getattr(o, "Proxy", None)).__name__ in ("WeldBead", "SWWeldedCorner")),
}


def _is_body(o):
    ""

    if o.TypeId == "PartDesign::Body":
        return True
    if not o.isDerivedFrom("Part::Feature") or o.isDerivedFrom("Part::Part2DObject"):
        return False
    if o.TypeId.startswith("PartDesign::") or o.isDerivedFrom("Part::Datum"):
        return False
    if type(getattr(o, "Proxy", None)).__name__ in ("CenterOfMass", "BoundingBox"):
        return False
    try:
        if not o.Shape.Faces:
            return False
    except Exception:
        return False
    for p in o.InList:
        if p.isDerivedFrom("PartDesign::Body") or (p.isDerivedFrom("Part::Feature") and p.TypeId != "App::Part"):
            return False
    return True


# Draft's annotation classes (Proxy class names); FreeCAD's own are by type
_DRAFT_ANNOTATIONS = {"LinearDimension", "AngularDimension", "Dimension", "Label", "Text", "DraftText",
                      "ArcDimension", "AnnotationStyle"}


def _is_annotation(o):
    if getattr(o, "SWStyleKind", "") == "PMI":
        return True         # a part's 3D annotations (notes, DimXpert): Display Annotations / All Annotations hide them
    if o.TypeId in ("App::Annotation", "App::AnnotationLabel", "App::MeasureDistance"):
        return True
    if o.TypeId.startswith("Measure::Measure"):
        return True
    proxy = getattr(o, "Proxy", None)
    return (proxy is not None and type(proxy).__name__ in _DRAFT_ANNOTATIONS
            and type(proxy).__module__.split(".")[0] in ("draftobjects", "Draft", "DraftObjects"))


TYPES["Bodies"] = ("View Bodies", "Shows or hides all solid and surface bodies.", _is_body)
TYPES["AllAnnotations"] = ("View All Annotations", "Shows or hides all annotations: dimensions, notes, "
                           "labels and measurements in the graphics area.", _is_annotation)

# types Hide All Types leaves alone: hiding the bodies would empty the screen
KEEP_ON_HIDE_ALL = ("Bodies",)

_hidden_all = {}    # doc name -> [(object name, was visible)]


def objects_of(key, doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return []
    test = TYPES[key][2]
    out = []
    for o in doc.Objects:
        try:
            if getattr(o, "ViewObject", None) is not None and test(o):
                out.append(o)
        except Exception as _fw_err:
            _fw_log("viewtypes.py:120", _fw_err)
            continue
    return out


def _origin_of(o):
    return next((p for p in o.InList if p.isDerivedFrom("App::Origin")), None)


def is_visible(o):
    """Shown on screen: an origin's planes, axes and point keep Visibility True while the
    Origin itself is hidden, so the Origin counts too."""
    if not o.ViewObject.Visibility:
        return False
    origin = _origin_of(o)
    return origin is None or origin.ViewObject is None or bool(origin.ViewObject.Visibility)



# part with no item of that type, and items made later follow it. Kept in the document's Meta (saved with it).
FLAG = "FreeWorksHideShow:"


DEFAULT_OFF = ("Planes", "PrimaryPlanes", "Axes", "Origins")


def flag(key, doc=None):
    """The document's own Hide/Show setting for a type: True (shown), False (hidden). Shown by default,
    except the origin's planes, axes and point (DEFAULT_OFF)."""
    default = "0" if key in DEFAULT_OFF else "1"
    doc = doc or App.ActiveDocument
    if doc is None:
        return default == "1"
    try:
        return doc.Meta.get(FLAG + key, default) != "0"
    except Exception:
        return default == "1"


def set_flag(key, on, doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return
    try:
        meta = dict(doc.Meta)
        value = "1" if on else "0"
        if meta.get(FLAG + key) != value:
            meta[FLAG + key] = value
            doc.Meta = meta
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Hide/Show %s setting not kept: %s\n" % (key, error))


def shown(key, doc=None):
    objs = objects_of(key, doc)
    if not objs:
        return flag(key, doc)          # nothing of that type yet: the document's setting
    return any(is_visible(o) for o in objs)


KEPT = "FreeWorksHideShowKept:"     # + type: what showed when the type was turned off, and what there was


def _keep(key, objs, doc):
    ""


    import json
    doc = doc or App.ActiveDocument
    if doc is None:
        return
    try:
        meta = dict(doc.Meta)
        if KEPT + key in meta:
            return                      # already off: keep what showed before the first off
        meta[KEPT + key] = json.dumps({"shown": [o.Name for o in objs if is_visible(o)],
                                       "all": [o.Name for o in objs]})
        doc.Meta = meta
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Hide/Show %s: %s\n" % (key, error))


def _kept(key, doc):
    """(shown names, names there were) remembered when the type was turned off, or None; forgotten."""
    import json
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        meta = dict(doc.Meta)
        text = meta.pop(KEPT + key, None)
        if text is None:
            return None
        doc.Meta = meta
        data = json.loads(text)
        return set(data.get("shown") or ()), set(data.get("all") or ())
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Hide/Show %s: %s\n" % (key, error))
        return None


def set_shown(key, on, doc=None):
    objs = objects_of(key, doc)
    if not on:
        _keep(key, objs, doc)
    kept = _kept(key, doc) if on else None
    if kept is not None:
        was, there = kept
        objs = [o for o in objs if o.Name in was or o.Name not in there]
        if not objs:
            objs = objects_of(key, doc)     # nothing of it showed (or all gone): turning it on shows them
    set_flag(key, on, doc)
    if on:
        for origin in {id(org): org for org in map(_origin_of, objs) if org is not None}.values():
            if origin.ViewObject is not None and not origin.ViewObject.Visibility:
                # an origin's features only draw while the Origin is shown; showing it must not
                # bring the other types along, so they are hidden first
                for f in origin.OriginFeatures:
                    f.ViewObject.Visibility = False
                origin.ViewObject.Visibility = True
    for o in objs:
        o.ViewObject.Visibility = bool(on)


def hide_all_types(doc=None):
    """Hide All Types; pressed again it shows what was shown before."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return
    saved = _hidden_all.pop(doc.Name, None)
    if saved is not None:
        for name, was in saved:
            o = doc.getObject(name)
            if o is not None and o.ViewObject is not None:
                o.ViewObject.Visibility = was
        return
    saved, seen = [], set()
    for key in TYPES:
        if key in KEEP_ON_HIDE_ALL:
            continue
        for o in objects_of(key, doc):
            if o.Name in seen:      # Primary Planes are Planes too: save each object once
                continue
            seen.add(o.Name)
            saved.append((o.Name, o.ViewObject.Visibility))
            o.ViewObject.Visibility = False
    _hidden_all[doc.Name] = saved
    TEMP_AXES.hide()
    SKETCH_PLANES.hide()


def all_hidden(doc=None):
    doc = doc or App.ActiveDocument
    return doc is not None and doc.Name in _hidden_all


class _TemporaryAxes:
    """View > Hide/Show > Temporary Axes: the axis of every cylindrical and conical face, drawn as
    a line through the model (not kept in the document)."""

    def __init__(self):
        self.nodes = []
        self.doc = None

    @property
    def on(self):
        return bool(self.nodes) and self.doc is App.ActiveDocument

    def axes(self, doc=None):
        import Part
        from .evaluate import visible_bodies
        out = []
        for body in visible_bodies(doc):
            for face in body.Shape.Faces:
                surf = face.Surface
                if not isinstance(surf, (Part.Cylinder, Part.Cone)):
                    continue
                axis, centre = surf.Axis, surf.Center
                box = face.BoundBox
                half = max(box.DiagonalLength * 0.6, 1.0)
                mid = centre + axis * axis.dot(face.CenterOfMass - centre)
                out.append(Part.LineSegment(mid - axis * half, mid + axis * half).toShape())
        return out

    def show(self):
        from pivy import coin
        self.hide()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return
        sep = coin.SoSeparator()
        col = coin.SoBaseColor()
        col.rgb.setValue(0.25, 0.25, 0.25)
        style = coin.SoDrawStyle()
        style.lineWidth.setValue(1.0)
        style.linePattern.setValue(0xF0FF)
        sep.addChild(col)
        sep.addChild(style)
        for line in self.axes():
            a, b = line.Vertexes[0].Point, line.Vertexes[1].Point
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 2, [(a.x, a.y, a.z), (b.x, b.y, b.z)])
            ls = coin.SoLineSet()
            part = coin.SoSeparator()
            part.addChild(coords)
            part.addChild(ls)
            sep.addChild(part)
        view.getSceneGraph().addChild(sep)
        self.nodes.append((view, sep))
        self.doc = App.ActiveDocument

    def hide(self):
        for view, sep in self.nodes:
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("viewtypes.py:285", _fw_err)
        self.nodes = []
        self.doc = None


TEMP_AXES = _TemporaryAxes()


class _SketchPlanes(_TemporaryAxes):
    ""


    MARGIN = 0.2    # of the sketch size, on each side
    MIN_HALF = 25.0     # mm, for an empty or very small sketch

    def outlines(self, doc=None):
        doc = doc or App.ActiveDocument
        out = []
        if doc is None:
            return out
        for sk in doc.Objects:
            if not sk.isDerivedFrom("Sketcher::SketchObject"):
                continue
            try:
                pl = sk.getGlobalPlacement()
            except Exception:
                pl = sk.Placement
            inv = pl.inverse()
            box = App.BoundBox()
            try:
                for v in sk.Shape.Vertexes:
                    box.add(inv.multVec(v.Point))
            except Exception as _fw_err:
                _fw_log("viewtypes.py:318", _fw_err)
            if box.isValid():
                cx, cy = box.Center.x, box.Center.y
                hx, hy = box.XLength / 2, box.YLength / 2
            else:
                cx = cy = hx = hy = 0.0
            half = max(hx, hy)
            hx = max(hx + half * self.MARGIN, self.MIN_HALF)
            hy = max(hy + half * self.MARGIN, self.MIN_HALF)
            corners = [App.Vector(cx - hx, cy - hy, 0), App.Vector(cx + hx, cy - hy, 0),
                       App.Vector(cx + hx, cy + hy, 0), App.Vector(cx - hx, cy + hy, 0)]
            out.append((sk.Name, [pl.multVec(c) for c in corners]))
        return out

    def show(self):
        from pivy import coin
        self.hide()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None:
            return
        sep = coin.SoSeparator()
        sep.setName("SWSketchPlanes")
        for _name, pts in self.outlines():
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, 5, [(p.x, p.y, p.z) for p in pts + pts[:1]])
            face = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor.setValue(0.55, 0.7, 0.9)
            mat.transparency.setValue(0.85)
            hints = coin.SoShapeHints()
            hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
            fs = coin.SoFaceSet()
            fs.numVertices.setValue(4)
            face.addChild(mat)
            face.addChild(hints)
            face.addChild(coords)
            face.addChild(fs)
            rim = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb.setValue(0.35, 0.5, 0.7)
            ls = coin.SoLineSet()
            ls.numVertices.setValue(5)
            rim.addChild(col)
            rim.addChild(coords)
            rim.addChild(ls)
            sep.addChild(face)
            sep.addChild(rim)
        view.getSceneGraph().addChild(sep)
        self.nodes.append((view, sep))
        self.doc = App.ActiveDocument


SKETCH_PLANES = _SketchPlanes()

_SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"


def _sketches(doc=None):
    doc = doc or App.ActiveDocument
    return [o for o in (doc.Objects if doc else []) if o.isDerivedFrom("Sketcher::SketchObject")]


def grid_shown(doc=None):
    """The sketch grid: the sketch being edited decides, else the setting new sketches take."""
    sk = _editing_sketch()
    if sk is not None and hasattr(sk.ViewObject, "ShowGrid"):
        return bool(sk.ViewObject.ShowGrid)
    return App.ParamGet(_SKETCHER + "/General").GetBool("ShowGrid", False)


def set_grid(on, doc=None):
    ""
    App.ParamGet(_SKETCHER + "/General").SetBool("ShowGrid", bool(on))
    for sk in _sketches(doc):
        vo = getattr(sk, "ViewObject", None)
        if vo is not None and hasattr(vo, "ShowGrid") and vo.ShowGrid != bool(on):
            vo.ShowGrid = bool(on)


def _editing_sketch():
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return None
    try:
        vp = gdoc.getInEdit()
    except Exception:
        return None
    obj = getattr(vp, "Object", None) if vp is not None else None
    return obj if obj is not None and obj.isDerivedFrom("Sketcher::SketchObject") else None


def dimension_names_shown():
    return App.ParamGet(_SKETCHER).GetBool("ShowDimensionalName", True)


def set_dimension_names(on):
    """FreeCAD redraws the dimensions of the sketch in edit when this setting changes; a dimension
    shows its name only when it has one (the Name field of the dimension)."""
    App.ParamGet(_SKETCHER).SetBool("ShowDimensionalName", bool(on))


class _SwitchCmd:
    """A check-box command over a setting: (menu, tooltip, is on, set)."""

    def __init__(self, menu, tip, get, put):
        self.menu, self.tip, self.get, self.put = menu, tip, get, put

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip, "Checkable": bool(self.get()), "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        self.put(not self.get())

    def IsActive(self):
        return App.ActiveDocument is not None


class _OverlayCmd(_SwitchCmd):
    def __init__(self, menu, tip, overlay):
        super().__init__(menu, tip, lambda: overlay.on, lambda on: overlay.show() if on else overlay.hide())


class _TempAxesCmd:
    def GetResources(self):
        return {"MenuText": "Temporary Axes", "ToolTip": "Shows or hides the axes of cylindrical and conical faces.",
                "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        if TEMP_AXES.on:
            TEMP_AXES.hide()
        else:
            TEMP_AXES.show()

    def IsActive(self):
        return App.ActiveDocument is not None


class _TypeCmd:
    def __init__(self, key):
        self.key = key

    def GetResources(self):
        menu, tip, _ = TYPES[self.key]
        return {"MenuText": menu, "ToolTip": tip, "Checkable": shown(self.key), "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        # always a toggle of what is on screen: Gui.runCommand passes 0 whatever the state
        set_shown(self.key, not shown(self.key))

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        # keep the check mark in step with the document
        try:
            for a in Gui.Command.get("SWStyle_View" + self.key).getAction():
                if a.isCheckable() and a.isChecked() != shown(self.key):
                    a.blockSignals(True)
                    a.setChecked(shown(self.key))
                    a.blockSignals(False)
        except Exception as _fw_err:
            _fw_log("viewtypes.py:478", _fw_err)
        return True


class _HideAllCmd:
    def GetResources(self):
        return {"MenuText": "Hide All Types",
                "ToolTip": "Hides planes, axes, origins, coordinate systems, points, sketches, curves and annotations; "
                           "press again to show what was shown before.",
                "Checkable": False, "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        hide_all_types()

    def IsActive(self):
        return App.ActiveDocument is not None


SWITCHES = {
    "SWStyle_ViewTemporaryAxes": _TempAxesCmd,
    "SWStyle_ViewGrid": lambda: _SwitchCmd(
        "Grid", "Shows or hides the sketch grid in every sketch of the document.", grid_shown, set_grid),
    "SWStyle_ViewDimensionNames": lambda: _SwitchCmd(
        "Dimension Names", "Shows the name of each named sketch dimension next to its value.",
        dimension_names_shown, set_dimension_names),
    "SWStyle_ViewSketchPlanes": lambda: _OverlayCmd(
        "Sketch Planes", "Shows or hides the plane of every sketch.", SKETCH_PLANES),
}
_STATE = {
    "SWStyle_ViewTemporaryAxes": lambda: TEMP_AXES.on,
    "SWStyle_ViewGrid": lambda: App.ActiveDocument is not None and grid_shown(),
    "SWStyle_ViewDimensionNames": lambda: App.ActiveDocument is not None and dimension_names_shown(),
    "SWStyle_ViewSketchPlanes": lambda: SKETCH_PLANES.on,
}
COMMANDS = ["SWStyle_View" + key for key in TYPES] + ["SWStyle_HideAllTypes"] + list(SWITCHES)
_installed = False


class _FollowFlags:
    ""


    def __init__(self):
        self.pending = {}          # doc name -> object names

    def slotCreatedObject(self, obj):
        try:
            doc = obj.Document
            if not any(k.startswith(FLAG) and v == "0" for k, v in doc.Meta.items()):
                return
        except Exception:
            return
        names = self.pending.setdefault(doc.Name, [])
        names.append(obj.Name)
        if len(names) == 1:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda name=doc.Name: self.apply(name))

    def apply(self, doc_name):
        names = self.pending.pop(doc_name, [])
        doc = App.listDocuments().get(doc_name)
        if doc is None:
            return
        for name in names:
            o = doc.getObject(name)
            if o is None or getattr(o, "ViewObject", None) is None:
                continue
            for key, (_menu, _tip, test) in list(TYPES.items()):
                try:
                    if not flag(key, doc) and test(o):
                        o.ViewObject.Visibility = False
                        break
                except Exception:
                    continue


_follow = None


def install():
    global _installed, _follow
    if _installed:
        return
    if _follow is None:
        _follow = _FollowFlags()
        App.addDocumentObserver(_follow)
    for key in TYPES:
        name = "SWStyle_View" + key
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _TypeCmd(key))
        checkstate.register(name, lambda key=key: App.ActiveDocument is not None and shown(key))
    if Gui.Command.get("SWStyle_HideAllTypes") is None:
        Gui.addCommand("SWStyle_HideAllTypes", _HideAllCmd())
    checkstate.register("SWStyle_HideAllTypes", lambda: all_hidden())     # pressed in the grid while it hides
    for name, make in SWITCHES.items():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, make())
        checkstate.register(name, _STATE[name])

    for module in ("silhouette", "modelorigin"):
        try:
            import importlib
            importlib.import_module("." + module, __package__).install()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s: %s\n" % (module, error))
    _installed = True
