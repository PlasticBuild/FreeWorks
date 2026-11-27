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

from . import checkstate, paths

VISIBLE, PHANTOM, REMOVED = "Visible", "Phantom", "Removed"
MODES = (VISIBLE, PHANTOM, REMOVED)
PHANTOM_NODE = "SWTangentPhantom"
SMOOTH_DOT = 0.99985     # about 1 degree between the two faces' normals
SMOOTH_DOT_OLD = 0.99863  # about 3 degrees: System Options > Display > Use pre-2009 tangent edge definition


def smooth_limit():
    try:
        from . import optionspages
        old = bool(optionspages.stored("Display", "Use pre-2009 tangent edge definition", False))
    except Exception:
        old = False
    return SMOOTH_DOT_OLD if old else SMOOTH_DOT
VIEW = "User parameter:BaseApp/Preferences/View"
TURNTABLE = 0


def seams_hidden():
    ""

    return not paths.params().GetBool("ShowSeamEdges", False)


def _edge_faces(shape, edges):
    """For each of shape.Edges (in order), the faces it borders: what shape.ancestorsOfType(edge, Part.Face) answers, found
    in one pass over the faces (an edge matched by isSame, as ancestorsOfType matches) instead of one pass per edge."""
    where = {}
    for i, e in enumerate(edges):
        where.setdefault(e.hashCode(), []).append(i)
    out = [[] for _e in edges]
    for face in shape.Faces:
        seen = set()
        for fe in face.Edges:
            for i in where.get(fe.hashCode(), ()):
                if i not in seen and edges[i].isSame(fe):
                    seen.add(i)
                    out[i].append(face)
    return out


_SEAMS = {}         # (doc, object) -> (mark, the shape, seam indices). Holding the shape keeps its OCC data alive, so
                    # no later shape can be given the same address (and so the same hashCode) while it is the one kept


_SEAMS_BY_SHAPE = {}     # extapps/66: (hashCode, edge count) -> (the shape, its seams), the last 24; memtrim empties it


def _cached_seams(obj):
    shape = obj.Shape
    try:
        key = (obj.Document.Name, obj.Name)
        mark = (shape.hashCode(), _count_edges(shape))
        got = _SEAMS.get(key)
        if got is not None and got[0] == mark and got[1].isSame(shape):
            return got[2]
        if got is not None and got[0][1] == mark[1] and got[1].isPartner(shape):
            _SEAMS[key] = (mark, shape, got[2])     # extapps/68: only moved (an assembly solve or drag): same seams
            return got[2]
        # extapps/66: the same shape seen for another object (a Body and its Tip) or a few steps ago (a rollback
        # dragged back and forth); the shape is held, so its hashCode is not reused while it is kept
        prev = _SEAMS_BY_SHAPE.get(mark)
        if prev is not None and prev[0].isSame(shape):
            seams = list(prev[1])
        else:
            seams = seam_edges(shape)
            if len(_SEAMS_BY_SHAPE) >= 24:
                _SEAMS_BY_SHAPE.pop(next(iter(_SEAMS_BY_SHAPE)))
            _SEAMS_BY_SHAPE[mark] = (shape, list(seams))
        _SEAMS[key] = (mark, shape, seams)
        return seams
    except Exception:
        return seam_edges(shape)


def _rebuilding():
    return _files_busy()


def _files_busy():
    """A file is opening or a document rebuilding (FreeCAD lets timers run between features then): the pass
    waits, the next tick after does it once (File handling perf-1127)."""
    try:
        if App.isRestoring():
            return True
        for d in App.listDocuments().values():
            if getattr(d, "Restoring", False) or getattr(d, "Recomputing", False):
                return True
    except Exception:
        return False
    return False


def _count_edges(shape):
    """len(shape.Edges) without making a Python object for every edge (the same unique-edge count)."""
    try:
        return shape.countElement("Edge")
    except Exception:
        return len(shape.Edges)


def _hidden_feature(obj):
    """A feature inside a PartDesign Body that is not shown: FreeCAD draws the Body (its Tip), not this."""
    try:
        if obj.ViewObject.Visibility or obj.isDerivedFrom("PartDesign::Body"):
            return False
        return any(p.isDerivedFrom("PartDesign::Body") for p in obj.InList)
    except Exception:
        return False


def seam_edges(shape):
    """0-based indices into shape.Edges of seam edges (cheap: only edges with one face are looked at)."""
    out = []
    try:
        edges = shape.Edges
        around = _edge_faces(shape, edges)
    except Exception:
        return out
    for i, edge in enumerate(edges):
        try:
            faces = around[i]
            if len(faces) == 1 and edge.isSeam(faces[0]):
                out.append(i)
        except Exception as _fw_err:
            _fw_log("displayextras.py:73", _fw_err)
    return out


def tangent_mode():
    mode = paths.params().GetString("TangentEdges", VISIBLE)
    return mode if mode in MODES else VISIBLE


def set_tangent_mode(mode):
    paths.params().SetString("TangentEdges", mode if mode in MODES else VISIBLE)
    TANGENT.apply_all()
    try:
        from . import hlv       # HLR/HLV and the Wireframe edges of Shaded With Edges draw their own edges
        hlv.HIDDEN.later()
    except Exception as _fw_err:
        _fw_log("displayextras.py:tangent-hlv", _fw_err)


# ---------------------------------------------------------------- which edges are smooth
def _normal(face, point):
    u, v = face.Surface.parameter(point)
    return face.normalAt(u, v)


def smooth_edges(shape):
    """0-based indices into shape.Edges of edges between two smoothly joined faces, and seams."""
    import Part
    out = []
    limit = smooth_limit()
    try:
        edges = shape.Edges
        around = _edge_faces(shape, edges)
    except Exception:
        return out
    for i, edge in enumerate(edges):
        try:
            faces = around[i]
        except Exception as _fw_err:
            _fw_log("displayextras.py:107", _fw_err)
            continue
        if len(faces) == 1:
            try:
                if edge.isSeam(faces[0]):
                    out.append(i)
            except Exception as _fw_err:
                _fw_log("displayextras.py:112", _fw_err)
            continue
        if len(faces) != 2:
            continue
        a, b = faces
        try:
            first, last = edge.ParameterRange
            smooth = True
            for t in (0.25, 0.5, 0.75):
                p = edge.valueAt(first + (last - first) * t)
                if _normal(a, p).dot(_normal(b, p)) < limit:
                    smooth = False
                    break
        except Exception:
            smooth = False
        if smooth:
            out.append(i)
    return out


# ---------------------------------------------------------------- drawing
def _edge_set(vo):
    """[(edge set, its parent)]: taken out of the search's paths, which go with the search."""
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoType.fromName("SoBrepEdgeSet"))
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.apply(vo.RootNode)
    paths_ = sa.getPaths()
    out = []
    for i in range(paths_.getLength()):
        path = paths_[i]
        out.append((path.getTail(), path.getNodeFromTail(1)))
    return out


def _runs(index):
    runs, cur = [], []
    for k in index:
        if k < 0:
            runs.append(cur)
            cur = []
        else:
            cur.append(k)
    if cur:
        runs.append(cur)
    return runs


def _join(runs):
    out = []
    for r in runs:
        out.extend(r)
        out.append(-1)
    return out


class _Tangent:
    def __init__(self):
        self.original = {}      # id of edge set -> (applied index list, original index list)
        self.timer = None
        self.observer = None
        self.dirty = set()      # extapps/68: (document, object) whose shape or display changed since the last pass
        self.full = False       # a pass over every object is asked for

    def _shape_objects(self, doc):
        for o in doc.Objects if doc else []:
            vo = getattr(o, "ViewObject", None)
            if vo is None or not o.isDerivedFrom("Part::Feature"):
                continue
            if o.isDerivedFrom("Part::Part2DObject"):
                continue
            yield o

    def apply_all(self, doc=None):
        docs = [doc] if doc else App.listDocuments().values()
        for d in docs:
            for o in self._shape_objects(d):
                if _hidden_feature(o):
                    continue            # not drawn; a Visibility change brings it back here when it is shown
                try:
                    self.apply(o)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: tangent edges on %s: %s\n" % (o.Name, error))

    def apply(self, obj, mode=None):
        from pivy import coin
        if obj.isDerivedFrom("PartDesign::Body") and getattr(obj, "Tip", None) is not None:
            # a Body draws its Tip's own nodes: its pass found the edges its Tip's pass had already taken out
            # (or the other way round), and its phantom lines were runs of one point: Tangent Edges as Phantom
            # drew nothing on a PartDesign part (vd115, 11-20). The Tip's own pass does it.
            return
        mode = mode or tangent_mode()
        seams0 = None           # the object's seam edges, found once for all its edge sets
        count0 = smooth0 = None     # extapps/66: its edge count and smooth edges, also once (countElement maps the shape)
        for n, (node, parent) in enumerate(_edge_set(obj.ViewObject)):
            key = (obj.Document.Name, obj.Name, n)
            now = list(node.coordIndex.getValues())
            applied, original = self.original.get(key, (None, None))
            base = original if applied is not None and now == applied else now
            # drop an old phantom drawing under this parent
            for k in range(parent.getNumChildren() - 1, -1, -1):
                child = parent.getChild(k)
                if child.getName() == PHANTOM_NODE:
                    parent.removeChild(k)
            if seams0 is None:
                seams0 = _cached_seams(obj) if seams_hidden() else []
            seams = list(seams0)
            if mode == VISIBLE and not seams:
                if base != now:
                    node.coordIndex.setValues(0, len(base), base)
                    node.coordIndex.setNum(len(base))
                self.original.pop(key, None)
                continue
            runs = _runs(base)
            if count0 is None:
                count0 = _count_edges(obj.Shape)
            if len(runs) != count0:
                continue        # not the shape's own edge list: leave it alone
            seams = [i for i in seams if i < len(runs)]
            if mode == VISIBLE:
                smooth = []
            else:
                if smooth0 is None:
                    smooth0 = smooth_edges(obj.Shape)
                smooth = [i for i in smooth0 if i < len(runs) and i not in seams]
            hidden = [list(r) for r in runs]
            for i in smooth + seams:
                if hidden[i]:
                    # a zero-length segment, not a lone point: the edge set counts lines to name the edge
                    # picked, and a one-point run is no line, so every edge after a hidden one was picked
                    # as the one before it (a loft's top circle came in as its bottom circle)
                    hidden[i] = [hidden[i][0], hidden[i][0]]
            new = _join(hidden)
            node.coordIndex.setValues(0, len(new), new)
            node.coordIndex.setNum(len(new))
            self.original[key] = (new, base)
            if mode == PHANTOM and smooth:
                sep = coin.SoSeparator()
                sep.setName(PHANTOM_NODE)
                pick = coin.SoPickStyle()
                pick.style = coin.SoPickStyle.UNPICKABLE
                # one colour for the whole set, unlit (the edge node binds its colours per edge)
                light = coin.SoLightModel()
                light.model = coin.SoLightModel.BASE_COLOR
                bind = coin.SoMaterialBinding()
                bind.value = coin.SoMaterialBinding.OVERALL
                col = coin.SoBaseColor()
                col.rgb.setValue(0.2, 0.2, 0.2)
                style = coin.SoDrawStyle()
                style.lineWidth.setValue(1.0)
                style.linePattern.setValue(0xFF33)      # phantom: a long dash and two short ones
                lines = coin.SoIndexedLineSet()
                idx = _join([runs[i] for i in smooth])
                lines.coordIndex.setValues(0, len(idx), idx)
                for n in (pick, light, bind, col, style, lines):
                    sep.addChild(n)
                parent.addChild(sep)

    def schedule(self, obj=None, kick=False):
        """obj: redo that object only (extapps/68: dragging one part of a 200-part assembly redid all 200 on every
        step). kick: run what is waiting. Neither: a pass over every object, as before."""
        if obj is not None:
            try:
                self.dirty.add((obj.Document.Name, obj.Name))
            except Exception:
                self.full = True
            if len(self.dirty) > 20000:
                self.dirty.clear()
                self.full = True
        elif not kick:
            self.full = True
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setSingleShot(True)
            self.timer.setInterval(60)
            # not while the document is still rebuilding (FreeCAD lets timers run between features): the edges are
            # redrawn by then anyway, and the Recomputed signal asks again at the end
            self.timer.timeout.connect(self._run)
        self.timer.start()

    def _run(self):
        if _rebuilding():
            self.schedule(kick=True)
            return
        doc = App.ActiveDocument
        full, self.full = self.full, False
        if full or doc is None:
            self.dirty.clear()
            self.apply_all(doc)
            return
        names = sorted(n for d, n in self.dirty if d == doc.Name)
        self.dirty = set(k for k in self.dirty if k[0] != doc.Name)
        for name in names:
            o = doc.getObject(name)
            try:
                if o is None or getattr(o, "ViewObject", None) is None or not o.isDerivedFrom("Part::Feature") \
                        or o.isDerivedFrom("Part::Part2DObject") or _hidden_feature(o):
                    continue
                self.apply(o)
            except Exception as error:
                App.Console.PrintLog("FreeWorks: tangent edges on %s: %s\n" % (name, error))

    def install(self):
        if self.observer is None:
            self.observer = _DocObserver(self)
            App.addDocumentObserver(self.observer)


class _DocObserver:
    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, obj, prop):
        if prop in ("Shape", "Visibility", "DisplayMode") and (tangent_mode() != VISIBLE or seams_hidden()):
            self.owner.schedule(obj)            # extapps/68: that object only

    def slotCreatedObject(self, obj):
        if tangent_mode() != VISIBLE or seams_hidden():
            self.owner.schedule(obj)

    def slotRecomputedDocument(self, doc):
        if tangent_mode() != VISIBLE or seams_hidden():
            self.owner.schedule(kick=True)      # the rebuilt objects were marked by their Shape changes


TANGENT = _Tangent()


class _TangentCmd:
    def __init__(self, mode, menu, tip):
        self.mode, self.menu, self.tip = mode, menu, tip

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip, "Checkable": tangent_mode() == self.mode,
                "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        set_tangent_mode(self.mode)

    def IsActive(self):
        return App.ActiveDocument is not None


# ---------------------------------------------------------------- Rotate About Scene Floor
def scene_floor():
    return App.ParamGet(VIEW).GetInt("OrbitStyle", 1) == TURNTABLE


def set_scene_floor(on):
    view, mine = App.ParamGet(VIEW), paths.params()
    if on and not scene_floor():
        mine.SetInt("OrbitStyleBeforeSceneFloor", view.GetInt("OrbitStyle", 1))
        view.SetInt("OrbitStyle", TURNTABLE)
    elif not on and scene_floor():
        back = mine.GetInt("OrbitStyleBeforeSceneFloor", 1)
        view.SetInt("OrbitStyle", back if back != TURNTABLE else 1)


class _SceneFloorCmd:
    def GetResources(self):
        return {"MenuText": "Rotate About Scene Floor",
                "ToolTip": "Rotates the view about the vertical axis of the screen, like a turntable.",
                "Checkable": scene_floor(), "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        set_scene_floor(not scene_floor())

    def IsActive(self):
        return App.ActiveDocument is not None


# ---------------------------------------------------------------- Isolate
class _Isolate:
    def __init__(self):
        self.saved = None       # (doc name, [(object name, was visible)])
        self.bar = None

    @property
    def on(self):
        return self.saved is not None

    def targets(self):
        """The picked bodies: a pick inside a Body counts as the Body."""
        out = []
        for s in Gui.Selection.getSelectionEx("", 0):
            obj = s.Object
            body = next((p for p in obj.InList if p.isDerivedFrom("PartDesign::Body")), None)
            if body is not None and obj.isDerivedFrom("PartDesign::Feature"):
                obj = body
            if obj not in out:
                out.append(obj)
        return out

    def start(self, keep=None):
        from .viewtypes import objects_of
        doc = App.ActiveDocument
        keep = keep if keep is not None else self.targets()
        if doc is None or not keep:
            return
        if self.on:
            self.exit()
        names = {o.Name for o in keep}
        saved = []
        for o in objects_of("Bodies", doc):
            if o.Name in names:
                continue
            saved.append((o.Name, o.ViewObject.Visibility))
            o.ViewObject.Visibility = False
        for o in keep:
            if o.ViewObject is not None and not o.ViewObject.Visibility:
                saved.append((o.Name, False))
                o.ViewObject.Visibility = True
        self.saved = (doc.Name, saved)
        self._show_bar()

    def exit(self):
        if not self.on:
            return
        name, saved = self.saved
        self.saved = None
        doc = App.listDocuments().get(name)
        for obj_name, was in saved if doc else []:
            o = doc.getObject(obj_name)
            if o is not None and o.ViewObject is not None:
                o.ViewObject.Visibility = was
        if self.bar is not None:
            try:
                self.bar.hide()
                self.bar.deleteLater()
            except Exception as _fw_err:
                _fw_log("displayextras.py:382", _fw_err)
            self.bar = None

    def _show_bar(self):
        mw = Gui.getMainWindow()
        view = None
        gl = [w for w in mw.findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget") and w.isVisible()]
        if gl:
            view = max(gl, key=lambda w: w.width() * w.height())
        bar = QtWidgets.QFrame(view.parentWidget() if view is not None else mw)
        bar.setObjectName("SWIsolateBar")
        bar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.addWidget(QtWidgets.QLabel("Isolate"))
        button = QtWidgets.QPushButton("Exit Isolate")
        button.setObjectName("SWExitIsolate")
        button.clicked.connect(self.exit)
        lay.addWidget(button)
        bar.adjustSize()
        bar.move(12, 48)
        bar.show()
        bar.raise_()
        self.bar = bar


ISOLATE = _Isolate()


class _IsolateCmd:
    def GetResources(self):
        return {"MenuText": "Isolate", "ToolTip": "Shows only the selected bodies until Exit Isolate.",
                "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        if ISOLATE.on or Gui.Selection.getSelection():
            ISOLATE.start()
        else:
            _pick_then_isolate()

    def IsActive(self):
        return App.ActiveDocument is not None     # nothing picked: it asks for the bodies (never greyed)


class _PickToIsolate:
    """Isolate with nothing selected: the status bar asks for the bodies; the first pick isolates."""

    def addSelection(self, doc, obj, sub, pnt):
        _stop_picking()
        QtCore.QTimer.singleShot(0, ISOLATE.start)


_PICKING = []


def _stop_picking():
    for o in _PICKING:
        try:
            Gui.Selection.removeObserver(o)
        except Exception as _fw_err:
            _fw_log("displayextras.py:isolatepick", _fw_err)
    del _PICKING[:]


def _pick_then_isolate():
    _stop_picking()
    o = _PickToIsolate()
    Gui.Selection.addObserver(o)
    _PICKING.append(o)
    try:
        Gui.getMainWindow().statusBar().showMessage("Isolate: select the bodies or components to show")
    except Exception as _fw_err:
        _fw_log("displayextras.py:isolateprompt", _fw_err)


class _PickToZoom:
    """Zoom to Selection with nothing selected: the status bar asks for the items; the first pick zooms."""

    def addSelection(self, doc, obj, sub, pnt):
        _stop_picking()
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("Std_ViewFitSelection", 0))


class _ZoomToSelectionCmd:
    """View > Modify > Zoom to Selection. FreeCAD's Fit Selection does nothing with nothing picked; here
    it asks for the items in the status bar and zooms to the first pick (never a dead or grey entry)."""

    def GetResources(self):
        return {"MenuText": "Zoom to Selection", "ToolTip": "Zooms to the picked items.",
                "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        if Gui.Selection.getSelectionEx():
            Gui.runCommand("Std_ViewFitSelection", 0)
            return
        _stop_picking()
        o = _PickToZoom()
        Gui.Selection.addObserver(o)
        _PICKING.append(o)
        try:
            Gui.getMainWindow().statusBar().showMessage("Zoom to Selection: select the items to zoom to")
        except Exception as _fw_err:
            _fw_log("displayextras.py:zoomprompt", _fw_err)

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.ActiveDocument is not None


class _ExitIsolateCmd:
    def GetResources(self):
        return {"MenuText": "Exit Isolate", "ToolTip": "Shows again what was shown before Isolate.",
                "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        ISOLATE.exit()

    def IsActive(self):
        return ISOLATE.on


TANGENT_COMMANDS = {
    "SWStyle_TangentEdgesVisible": (VISIBLE, "Tangent Edges Visible", "Draws tangent edges like other edges."),
    "SWStyle_TangentEdgesPhantom": (PHANTOM, "Tangent Edges as Phantom",
                                    "Draws tangent edges as thin dashed lines."),
    "SWStyle_TangentEdgesRemoved": (REMOVED, "Tangent Edges Removed", "Leaves tangent edges out."),
}
COMMANDS = list(TANGENT_COMMANDS) + ["SWStyle_RotateAboutSceneFloor", "SWStyle_Isolate", "SWStyle_ExitIsolate", "SWStyle_ZoomToSelection"]
_installed = False


def install():
    global _installed
    if _installed:
        return
    for name, (mode, menu, tip) in TANGENT_COMMANDS.items():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _TangentCmd(mode, menu, tip))
        checkstate.register(name, lambda mode=mode: tangent_mode() == mode)
    if Gui.Command.get("SWStyle_RotateAboutSceneFloor") is None:
        Gui.addCommand("SWStyle_RotateAboutSceneFloor", _SceneFloorCmd())
    checkstate.register("SWStyle_RotateAboutSceneFloor", scene_floor)
    if Gui.Command.get("SWStyle_Isolate") is None:
        Gui.addCommand("SWStyle_Isolate", _IsolateCmd())
    if Gui.Command.get("SWStyle_ExitIsolate") is None:
        Gui.addCommand("SWStyle_ExitIsolate", _ExitIsolateCmd())
    if Gui.Command.get("SWStyle_ZoomToSelection") is None:
        Gui.addCommand("SWStyle_ZoomToSelection", _ZoomToSelectionCmd())
    TANGENT.install()
    if tangent_mode() != VISIBLE or seams_hidden():
        QtCore.QTimer.singleShot(0, TANGENT.apply_all)
    _installed = True
