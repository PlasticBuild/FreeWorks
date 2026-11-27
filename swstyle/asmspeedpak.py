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

from . import asmcore as ac
from . import checkstate

SP_PROP = "FwSpeedPakOf"          # the SpeedPak's own part (or subassembly)
STAMP_PROP = "FwSpeedPakStamp"    # what the part looked like when the SpeedPak was made
FACES_PROP = "FwSpeedPakFaces"    # Faces to include (indexes into the part's faces)
BODIES_PROP = "FwSpeedPakBodies"  # Bodies to include (indexes into the part's solids)
EXFACES_PROP = "FwSpeedPakExcludeFaces"
EXBODIES_PROP = "FwSpeedPakExcludeBodies"
GRAPHICS_PROP = "FwSpeedPakGraphics"   # the whole look, drawn but not pickable, when some are included
NO_GHOST_PROP = "FwSpeedPakNoGhost"
HIDDEN_PROP = "FwGraphicsHidden"  # a graphics component hidden by Display Graphics Components
STATE = {"display": True}


def is_speedpak(obj):
    return obj is not None and getattr(obj, SP_PROP, None) is not None


def own(obj):
    return getattr(obj, SP_PROP) if is_speedpak(obj) else obj


def links(asm):
    return [c for c in ac.components(asm) if c.TypeId == "App::Link"]


def speedpak_components(asm):
    return [c for c in links(asm) if is_speedpak(c.LinkedObject)]


def is_graphics(comp):
    target = getattr(comp, "LinkedObject", None)
    return is_speedpak(target) or (target is not None and target.isDerivedFrom("Mesh::Feature"))


def stamp(target):
    try:
        s = target.Shape
        b = s.BoundBox
        return "%d %.6f %.6f %.6f %.6f %.6f %.6f %.6f" % (len(s.Faces), s.Volume, b.XMin, b.YMin, b.ZMin,
                                                          b.XMax, b.YMax, b.ZMax)
    except Exception:
        return ""


def light_shape(target):
    """One body with the part's (or subassembly's) faces, in its own frame."""
    import Part
    shape = target.Shape.copy()
    shape.Placement = App.Placement()
    solids = shape.Solids
    if len(solids) == 1:
        return solids[0].copy()
    return Part.Compound(solids) if solids else shape


def excluded_faces(graphics, ex_faces=(), ex_bodies=()):
    """Indexes of the faces left out: the excluded faces and every face of an excluded body."""
    out = set(i for i in ex_faces or () if 0 <= i < len(graphics.Faces))
    solids = graphics.Solids
    for b in ex_bodies or ():
        if 0 <= b < len(solids):
            for f in solids[b].Faces:
                for i, g in enumerate(graphics.Faces):
                    if g.isSame(f):
                        out.add(i)
    return out


def included_shape(target, graphics, faces=(), bodies=(), ex_faces=(), ex_bodies=()):
    ""

    import Part
    faces, bodies = list(faces or ()), list(bodies or ())
    ex_faces, ex_bodies = list(ex_faces or ()), list(ex_bodies or ())
    if not faces and not bodies and not ex_faces and not ex_bodies:
        return graphics
    gone = excluded_faces(graphics, ex_faces, ex_bodies) if (ex_faces or ex_bodies) else set()
    all_faces = graphics.Faces
    parts = []
    if not faces and not bodies:        # exclude only: everything else stays pickable
        parts = [f.copy() for i, f in enumerate(all_faces) if i not in gone]
        return Part.Compound(parts) if parts else _empty()
    for i in faces:
        if 0 <= i < len(all_faces) and i not in gone:
            parts.append(all_faces[i].copy())
    solids = graphics.Solids
    for i in bodies:
        if 0 <= i < len(solids) and i not in set(ex_bodies):
            parts.append(solids[i].copy())
    return Part.Compound(parts) if parts else graphics


def quick_include(target, level, steps=10):
    """The Quick include slider: the biggest faces first, more of them further right (0 = none)."""
    try:
        faces = light_shape(target).Faces
    except Exception:
        return []
    order = sorted(range(len(faces)), key=lambda i: -faces[i].Area)
    n = int(round(len(order) * max(0, min(level, steps)) / float(steps)))
    return sorted(order[:n])


def can_add(comp):
    from . import asmfeature as af
    target = getattr(comp, "LinkedObject", None)
    return target is not None and not is_speedpak(target) and not af.is_body(target) \
        and not target.isDerivedFrom("Mesh::Feature")


def _relink(asm, comp, new_target, new_shape):
    """comp shows new_target; its mates stay on the same faces."""
    from . import asmfeature as af
    old = af._local(comp.LinkedObject)
    plan = af._plan(asm, comp, old, new_shape)
    names = {j.Name for j, _p, _v in plan}
    af._hush()
    af._QUIET.update(names)
    try:
        comp.LinkedObject = new_target
    finally:
        af._QUIET.difference_update(names)
    af._apply(plan)


def _ghost(sp, graphics, shape):
    """The graphics-only look kept with the SpeedPak: the whole part when some faces or bodies are
    included, nothing with Remove ghost (only the included geometry is drawn)."""
    if shape is graphics or getattr(sp, NO_GHOST_PROP, False):
        return _empty()
    return graphics


def add(comp, faces=(), bodies=(), ex_faces=(), ex_bodies=(), remove_ghost=False):
    """Add SpeedPak: comp is shown from a light copy of its part; faces/bodies are the SpeedPak
    PM's Faces to include and Bodies to include; remove_ghost its Remove ghost."""
    if not can_add(comp):
        return None
    asm = ac.assembly_of(comp.Document)
    target = comp.LinkedObject
    doc = comp.Document
    from . import asmfeature as af
    sp = doc.addObject("Part::FeaturePython", "SpeedPak")
    af.CutBody(sp)
    sp.addProperty("App::PropertyXLink", SP_PROP, "FreeCAD", "The part or subassembly this SpeedPak stands for")
    sp.addProperty("App::PropertyString", STAMP_PROP, "FreeCAD", "The part when the SpeedPak was made")
    _props(sp)
    setattr(sp, SP_PROP, target)
    sp.Label = ac.part_name(comp)
    setattr(sp, FACES_PROP, sorted(set(int(i) for i in faces or ())))
    setattr(sp, BODIES_PROP, sorted(set(int(i) for i in bodies or ())))
    setattr(sp, EXFACES_PROP, sorted(set(int(i) for i in ex_faces or ())))
    setattr(sp, EXBODIES_PROP, sorted(set(int(i) for i in ex_bodies or ())))
    setattr(sp, NO_GHOST_PROP, bool(remove_ghost))
    graphics = light_shape(target)
    shape = included_shape(target, graphics, getattr(sp, FACES_PROP), getattr(sp, BODIES_PROP),
                           getattr(sp, EXFACES_PROP), getattr(sp, EXBODIES_PROP))
    sp.Shape = shape
    setattr(sp, GRAPHICS_PROP, _ghost(sp, graphics, shape))
    setattr(sp, STAMP_PROP, stamp(target))
    if App.GuiUp and sp.ViewObject is not None:
        ViewProviderSpeedPak(sp.ViewObject)
        try:
            sp.ViewObject.ShowInTree = False
            sp.ViewObject.Visibility = False
            vo = target.ViewObject
            if vo is not None and hasattr(vo, "ShapeAppearance"):
                sp.ViewObject.ShapeAppearance = vo.ShapeAppearance
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:199", _fw_err)
    _relink(asm, comp, sp, shape)
    af._redraw(sp)
    doc.recompute()
    return sp


def remove(comp):
    """Remove SpeedPak: comp gets its own part back."""
    sp = getattr(comp, "LinkedObject", None)
    if not is_speedpak(sp):
        return False
    asm = ac.assembly_of(comp.Document)
    target = own(sp)
    from . import asmfeature as af
    _relink(asm, comp, target, af._local(target))
    if not [c for c in links(asm) if c.LinkedObject is sp]:
        comp.Document.removeObject(sp.Name)
    comp.Document.recompute()
    return True


def out_of_date(asm):
    return [c for c in speedpak_components(asm)
            if getattr(c.LinkedObject, STAMP_PROP, "") != stamp(own(c.LinkedObject))]


def update(asm):
    """Update SpeedPak: each SpeedPak made again from its part. Returns the components updated."""
    from . import asmfeature as af
    done = []
    seen = set()
    for comp in speedpak_components(asm):
        sp = comp.LinkedObject
        target = own(sp)
        try:
            target.Document.recompute()
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:237", _fw_err)
        now = stamp(target)
        if sp.Name in seen or getattr(sp, STAMP_PROP, "") == now:
            continue
        seen.add(sp.Name)
        graphics = light_shape(target)
        shape = included_shape(target, graphics, getattr(sp, FACES_PROP, ()), getattr(sp, BODIES_PROP, ()),
                               getattr(sp, EXFACES_PROP, ()), getattr(sp, EXBODIES_PROP, ()))
        if hasattr(sp, GRAPHICS_PROP):
            setattr(sp, GRAPHICS_PROP, _ghost(sp, graphics, shape))
        users = [c for c in links(asm) if c.LinkedObject is sp]
        plans = []
        for c in users:
            plans += af._plan(asm, c, af._local(sp), shape)
        af._set_shape(sp, shape, plans)
        setattr(sp, STAMP_PROP, now)
        af._redraw(sp)
        done += users
    if done:
        asm.Document.recompute()
    return done


def display_graphics():
    return STATE["display"]


def set_display_graphics(on, asm=None):
    STATE["display"] = bool(on)
    asm = asm or _assembly()
    if asm is None:
        return []
    out = []
    for comp in ac.components(asm):
        if not is_graphics(comp):
            continue
        if not on and comp.Visibility:
            comp.Visibility = False
            if not hasattr(comp, HIDDEN_PROP):
                comp.addProperty("App::PropertyBool", HIDDEN_PROP, "FreeCAD", "Hidden by Display Graphics Components")
                comp.setPropertyStatus(HIDDEN_PROP, "Hidden")
            setattr(comp, HIDDEN_PROP, True)
            out.append(comp)
        elif on and getattr(comp, HIDDEN_PROP, False):
            comp.Visibility = True
            setattr(comp, HIDDEN_PROP, False)
            out.append(comp)
    return out


def _empty():
    import Part
    return Part.Shape()


def _props(sp):
    for typ, name, tip in (("App::PropertyIntegerList", FACES_PROP, "SpeedPak: Faces to include"),
                           ("App::PropertyIntegerList", BODIES_PROP, "SpeedPak: Bodies to include"),
                           ("App::PropertyIntegerList", EXFACES_PROP, "SpeedPak: Faces to exclude"),
                           ("App::PropertyIntegerList", EXBODIES_PROP, "SpeedPak: Bodies to exclude"),
                           ("Part::PropertyPartShape", GRAPHICS_PROP, "SpeedPak: the graphics-only look"),
                           ("App::PropertyBool", NO_GHOST_PROP, "SpeedPak: Remove ghost")):
        if not hasattr(sp, name):
            sp.addProperty(typ, name, "FreeCAD", tip)
            sp.setPropertyStatus(name, "Hidden")


def included(sp):
    return list(getattr(sp, FACES_PROP, []) or []), list(getattr(sp, BODIES_PROP, []) or [])


def _graphics_node(shape):
    ""
    from pivy import coin
    sep = coin.SoSeparator()
    style = coin.SoPickStyle()
    style.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(style)
    if shape is None or shape.isNull():
        return sep
    try:
        text = shape.writeInventor(2, 0.1)
        inp = coin.SoInput()
        inp.setBuffer(text)
        node = coin.SoDB.readAll(inp)
        if node is not None:
            sep.addChild(node)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: SpeedPak graphics: %s\n" % error)
    return sep


class ViewProviderSpeedPak:
    """A SpeedPak: its pickable faces as any shape; with faces or bodies included, the rest of the
    part drawn as graphics only."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self.vobj = vobj
        self.node = None
        self._draw()

    def _draw(self):
        try:
            root = self.vobj.RootNode
        except Exception:
            return
        if self.node is not None:
            try:
                root.removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("asmspeedpak.py:350", _fw_err)
            self.node = None
        shape = getattr(self.Object, GRAPHICS_PROP, None)
        if shape is None or shape.isNull():
            return
        self.node = _graphics_node(shape)
        root.addChild(self.node)

    def updateData(self, obj, prop):
        if prop == GRAPHICS_PROP:
            self._draw()

    def getIcon(self):
        try:
            icon = getattr(self.Object, SP_PROP).ViewObject.Icon
            if icon is not None and not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:368", _fw_err)
        return ":/icons/Tree_Part.svg"

    def dumps(self):
        return None

    def loads(self, state):
        return None


try:
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    QtWidgets = None


class SpeedPakPanel:
    ""

    def __init__(self, comp):
        from . import asmpm
        self.comp = comp
        self.asm = ac.assembly_of(comp.Document)
        self.target = comp.LinkedObject
        self.faces, self.bodies = [], []
        self.ex_faces, self.ex_bodies = [], []
        self.marks = None
        box, lay = asmpm._box("Include", "SpeedPak")
        box.setObjectName("FW_SpeedPak")
        lay.addWidget(QtWidgets.QLabel(comp.Label))
        lay.addWidget(QtWidgets.QLabel("Faces to include:"))
        self.face_list = QtWidgets.QListWidget()
        self.face_list.setObjectName("FW_SpeedPakFaces")
        self.face_list.setStyleSheet(asmpm.PICK_STYLE)
        self.face_list.setFixedHeight(asmpm._rows(self.face_list, 4))
        lay.addWidget(self.face_list)
        lay.addWidget(QtWidgets.QLabel("Bodies to include:"))
        self.body_list = QtWidgets.QListWidget()
        self.body_list.setObjectName("FW_SpeedPakBodies")
        self.body_list.setFixedHeight(asmpm._rows(self.body_list, 3))
        lay.addWidget(self.body_list)
        lay.addWidget(QtWidgets.QLabel("Quick include:"))
        self.quick = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.quick.setObjectName("FW_SpeedPakQuick")
        self.quick.setRange(0, 10)
        self.quick.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.quick.valueChanged.connect(self._quick)
        lay.addWidget(self.quick)
        note = QtWidgets.QLabel("Only included faces and bodies can be picked and mated; the rest is graphics only. "
                                "Include nothing to keep every face.")
        note.setWordWrap(True)
        lay.addWidget(note)

        exbox, exlay = asmpm._box("Exclude", "SpeedPakExclude")
        exbox.setObjectName("FW_SpeedPakExclude")
        self.exclude_mode = QtWidgets.QCheckBox("Pick to exclude")
        self.exclude_mode.setObjectName("FW_SpeedPakExcludeMode")
        self.exclude_mode.setToolTip("On: faces and bodies you pick go in the exclude lists")
        exlay.addWidget(self.exclude_mode)
        exlay.addWidget(QtWidgets.QLabel("Faces to exclude:"))
        self.exface_list = QtWidgets.QListWidget()
        self.exface_list.setObjectName("FW_SpeedPakExFaces")
        self.exface_list.setStyleSheet(asmpm.PICK_STYLE)
        self.exface_list.setFixedHeight(asmpm._rows(self.exface_list, 3))
        exlay.addWidget(self.exface_list)
        exlay.addWidget(QtWidgets.QLabel("Bodies to exclude:"))
        self.exbody_list = QtWidgets.QListWidget()
        self.exbody_list.setObjectName("FW_SpeedPakExBodies")
        self.exbody_list.setFixedHeight(asmpm._rows(self.exbody_list, 2))
        exlay.addWidget(self.exbody_list)
        self.show_marks = QtWidgets.QCheckBox("Show included / excluded marks")
        self.show_marks.setObjectName("FW_SpeedPakMarks")
        self.show_marks.setChecked(True)
        self.show_marks.toggled.connect(lambda _on: self._marks())
        exlay.addWidget(self.show_marks)
        exnote = QtWidgets.QLabel("Included faces are marked green, excluded faces red. Excluded faces and bodies "
                                  "are graphics only.")
        exnote.setWordWrap(True)
        exlay.addWidget(exnote)

        # Shown once something is included: with nothing included there is no ghost
        obox, olay = asmpm._box("Options", "SpeedPakOptions")
        obox.setObjectName("FW_SpeedPakOptions")
        self.remove_ghost = QtWidgets.QCheckBox("Remove ghost")
        self.remove_ghost.setObjectName("FW_SpeedPakRemoveGhost")
        self.remove_ghost.setToolTip("Draw only the included faces and bodies, not the rest of the part")
        olay.addWidget(self.remove_ghost)
        self.options_box = obox
        obox.setVisible(False)
        self.form = [box, exbox, obox]
        Gui.Selection.addObserver(self, 0)

    def _quick(self, level):
        self.faces = quick_include(self.target, level)
        self._show()

    def _show(self):
        self.face_list.clear()
        for i in self.faces:
            self.face_list.addItem("Face%d" % (i + 1))
        self.body_list.clear()
        for i in self.bodies:
            self.body_list.addItem("Body %d" % (i + 1))
        if hasattr(self, "exface_list"):
            self.exface_list.clear()
            for i in self.ex_faces:
                self.exface_list.addItem("Face%d" % (i + 1))
            self.exbody_list.clear()
            for i in self.ex_bodies:
                self.exbody_list.addItem("Body %d" % (i + 1))
            self._marks()
        if hasattr(self, "options_box"):
            self.options_box.setVisible(bool(self.faces or self.bodies or self.ex_faces or self.ex_bodies))

    def _marks(self):
        clear_marks(self.marks)
        self.marks = None
        if self.show_marks.isChecked():
            self.marks = show_marks(self.comp, self.faces, self.bodies, self.ex_faces, self.ex_bodies)

    def pick(self, sub, exclude=None):
        """A face or (with a body pick, Alt) a body of the component: toggles it in its list
        (the exclude lists when Pick to exclude is on). A pick moves it out of the other list."""
        name = (sub or "").split(".")[-1]
        if exclude is None:
            exclude = hasattr(self, "exclude_mode") and self.exclude_mode.isChecked()
        faces, other_f = (self.ex_faces, self.faces) if exclude else (self.faces, self.ex_faces)
        bodies, other_b = (self.ex_bodies, self.bodies) if exclude else (self.bodies, self.ex_bodies)
        if name.startswith("Face"):
            i = int(name[4:]) - 1
            if i in faces:
                faces.remove(i)
            else:
                faces.append(i)
                faces.sort()
                if i in other_f:
                    other_f.remove(i)
        elif name.startswith("Solid"):
            i = int(name[5:]) - 1
            if i in bodies:
                bodies.remove(i)
            else:
                bodies.append(i)
                if i in other_b:
                    other_b.remove(i)
        self._show()

    def addSelection(self, doc, obj, sub, pnt):
        if obj != self.comp.Name and (sub or "").split(".")[0] != self.comp.Name:
            return
        from . import safe_later as _sl; _sl.later(0, lambda: (self.pick(sub), Gui.Selection.clearSelection()), self, "exclude_mode")

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def _done(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:521", _fw_err)
        clear_marks(self.marks)
        self.marks = None
        Gui.Control.closeDialog()
        return True

    def accept(self):
        doc = self.comp.Document
        faces, bodies = list(self.faces), list(self.bodies)
        ex_faces, ex_bodies = list(self.ex_faces), list(self.ex_bodies)
        ghost = self.remove_ghost.isChecked() and bool(faces or bodies or ex_faces or ex_bodies)
        self._done()
        doc.openTransaction("Add SpeedPak")
        try:
            add(self.comp, faces, bodies, ex_faces, ex_bodies, remove_ghost=ghost)
        finally:
            doc.commitTransaction()
        return True

    def reject(self):
        return self._done()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


MARK_COLOURS = {"in": (0.1, 0.8, 0.2), "out": (0.9, 0.15, 0.15)}


def show_marks(comp, faces=(), bodies=(), ex_faces=(), ex_bodies=()):
    """The graphical marks of the SpeedPak PM: the included faces (and bodies) drawn over the
    component in green, the excluded ones in red, half see-through. Returns the coin node (on the
    active view's scene graph) for clear_marks, or None."""
    try:
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        sg = view.getSceneGraph()
    except Exception:
        return None
    try:
        target = comp.LinkedObject
        full = target.Shape.copy()
        full.Placement = comp.getGlobalPlacement() if hasattr(comp, "getGlobalPlacement") else comp.Placement
    except Exception:
        return None
    root = coin.SoSeparator()
    root.setName("FW_SpeedPakMarks")
    gone = excluded_faces(full, ex_faces, ex_bodies)
    groups = {"in": [i for i in faces if 0 <= i < len(full.Faces)],
              "out": sorted(gone)}
    for b in bodies:
        if 0 <= b < len(full.Solids):
            for f in full.Solids[b].Faces:
                for i, g in enumerate(full.Faces):
                    if g.isSame(f) and i not in groups["in"]:
                        groups["in"].append(i)
    count = 0
    for kind, ids in groups.items():
        if not ids:
            continue
        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor = MARK_COLOURS[kind]
        mat.emissiveColor = tuple(c * 0.5 for c in MARK_COLOURS[kind])
        mat.transparency = 0.35
        sep.addChild(mat)
        poly = coin.SoPolygonOffset()
        poly.factor = -2.0
        poly.units = -2.0
        sep.addChild(poly)
        coords, index = [], []
        for i in ids:
            try:
                pts, tris = full.Faces[i].tessellate(0.1 * max(1.0, full.BoundBox.DiagonalLength / 50.0))
            except Exception:
                continue
            base = len(coords)
            coords.extend((p.x, p.y, p.z) for p in pts)
            for t in tris:
                index.extend((t[0] + base, t[1] + base, t[2] + base, -1))
            count += 1
        if not index:
            continue
        c = coin.SoCoordinate3()
        c.point.setValues(0, len(coords), coords)
        sep.addChild(c)
        fs = coin.SoIndexedFaceSet()
        fs.coordIndex.setValues(0, len(index), index)
        sep.addChild(fs)
        sep.setName("FW_SpeedPakMarks_" + kind)
        root.addChild(sep)
    if not count:
        return None
    sg.addChild(root)
    return (sg, root)


def clear_marks(marks):
    if not marks:
        return
    try:
        marks[0].removeChild(marks[1])
    except Exception as _fw_err:
        _fw_log("asmspeedpak.py:623", _fw_err)


def open_panel(comp):
    """Add SpeedPak: the SpeedPak PM for comp."""
    from . import asmpm
    if not can_add(comp):
        return None
    if Gui.Control.activeDialog() and not asmpm.close_open():
        Gui.Control.closeDialog()
    panel = SpeedPakPanel(comp)
    asmpm._track(panel)
    Gui.Control.showDialog(panel)
    return panel


# ---------------------------------------------------------------- commands
def _assembly():
    try:
        from . import asmtools
        return asmtools._assembly()
    except Exception as _fw_err:
        _fw_log("asmspeedpak.py:646", _fw_err)
        return None


def _tell(title, text):
    try:
        from . import asmtools
        asmtools._tell(title, text)
    except Exception:
        App.Console.PrintMessage(text + "\n")


class UpdateSpeedPakCommand:
    def GetResources(self):
        return {"MenuText": "Update SpeedPak", "Pixmap": "view-refresh",
                "ToolTip": "Updates the SpeedPak components of the assembly from their parts."}

    def Activated(self, *args):
        asm = _assembly()
        if asm is None:
            return
        if not speedpak_components(asm):
            # always live (no greyed button): with no SpeedPak it says so
            Gui.getMainWindow().statusBar().showMessage("Update SpeedPak: this assembly has no SpeedPak components.", 6000)
            return
        doc = asm.Document
        doc.openTransaction("Update SpeedPak")
        try:
            done = update(asm)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        if not done:
            _tell("Update SpeedPak", "The SpeedPaks of this assembly are up to date.")

    def IsActive(self):
        return _assembly() is not None


class DisplayGraphicsCommand:
    def GetResources(self):
        return {"MenuText": "Display Graphics Components", "Pixmap": "Std_ToggleVisibility",
                "ToolTip": "Shows or hides graphics components: SpeedPak and mesh components."}

    def Activated(self, *args):
        asm = _assembly()
        if asm is None:
            return
        doc = asm.Document
        doc.openTransaction("Display Graphics Components")
        try:
            set_display_graphics(not display_graphics(), asm)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()

    def IsActive(self):
        return _assembly() is not None


COMMANDS = [("SWStyle_UpdateSpeedPak", UpdateSpeedPakCommand()),
            ("SWStyle_DisplayGraphicsComponents", DisplayGraphicsCommand())]


# ----------------------------------------------------------------------------- mass, BOM
def _speedpak_of(obj):
    sp = getattr(obj, "LinkedObject", None) if obj is not None and obj.TypeId == "App::Link" else obj
    return sp if is_speedpak(sp) else None


def install():
    try:
        from . import massprops
        if not getattr(massprops, "_fw_speedpak", False):
            massprops._fw_speedpak = True
            solids0 = massprops._solids_of

            def _solids_of(obj):
                sp = _speedpak_of(obj)
                if sp is None:
                    return solids0(obj)
                try:
                    shape = own(sp).Shape.copy()
                    shape.Placement = App.Placement()
                    if obj is not sp:
                        shape.Placement = App.Placement(obj.Placement)
                    return list(shape.Solids)
                except Exception:
                    return solids0(obj)
            massprops._solids_of = _solids_of
    except Exception as error:
        App.Console.PrintLog("FreeCAD: SpeedPak mass: %s\n" % error)
    try:
        from . import drawtables
        if not getattr(drawtables, "_fw_speedpak", False):
            drawtables._fw_speedpak = True
            items0 = drawtables.bom_items

            def bom_items(view, *args, **kwargs):
                items = items0(view, *args, **kwargs)
                out, index, sp_keys = [], {}, set()
                for it in items:
                    base = it[4] if len(it) > 4 else None
                    merge = is_speedpak(base)
                    if merge:
                        part = own(base)
                        try:
                            name = drawtables._part_number(part.Document, "Default", part)
                        except Exception:
                            name = part.Label
                        key = ("sp", part.Document.Name, name, it[3])
                        it = [name, it[1], it[2], it[3], part] + list(it[5:])
                    else:
                        key = ("it", id(it))
                        try:
                            if base is not None:
                                key = ("sp", base.Document.Name, it[0], it[3])
                        except Exception as _fw_err:
                            _fw_log("asmspeedpak.py:753", _fw_err)
                    if merge:
                        sp_keys.add(key)
                    if (merge or key in sp_keys) and key in index:   # a SpeedPak: one row with its part's other instances
                        out[index[key]][2] += it[2]
                        continue
                    index.setdefault(key, len(out))
                    out.append(list(it))
                return out
            drawtables.bom_items = bom_items
    except Exception as error:
        App.Console.PrintLog("FreeCAD: SpeedPak BOM: %s\n" % error)


# ----------------------------------------------------------------------------- the graphics circle
CIRCLE = {"on": False, "overlay": None, "kept": {}}
RADIUS = 60


def circle_on():
    return CIRCLE["on"]


def _comps_of(sp):
    asm = ac.assembly_of(sp.Document)
    return asm, [c for c in links(asm) if getattr(c, "LinkedObject", None) is sp] if asm is not None else []


def _reshape(sp, shape):
    from . import asmfeature as af
    asm, comps = _comps_of(sp)
    old = af._local(sp)
    plan = []
    for c in comps:
        plan += af._plan(asm, c, old, shape)
    af._set_shape(sp, shape, plan)
    # a reference whose name did not change still holds the old shape's element: name it again
    for joint, prop, value in plan:
        try:
            setattr(joint, prop, (value[0], list(value[1])))
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:794", _fw_err)


def _mated_faces(sp, full):
    """Faces of full (the whole SpeedPak look) the mates on its components hold."""
    from . import asmfeature as af
    asm, comps = _comps_of(sp)
    out = set()
    for j in ac.joint_group(asm).Group if asm is not None else []:
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            if not ref or ref[0] not in comps:
                continue
            for sub in ref[1]:
                elem = sub.rpartition(".")[2]
                if elem.startswith("Face"):
                    try:
                        out.add(int(elem[4:]) - 1)
                    except ValueError as _fw_err:
                        _fw_log("asmspeedpak.py:813", _fw_err)
    return out


def set_circle(on, asm=None):
    """Display SpeedPak Graphics Circle on / off."""
    asm = asm or ac.assembly_of(App.ActiveDocument)
    on = bool(on)
    if on == CIRCLE["on"]:
        return on
    CIRCLE["on"] = on
    sps = [] if asm is None else list(dict.fromkeys(c.LinkedObject for c in speedpak_components(asm)))
    if on:
        for sp in sps:
            faces, bodies = included(sp)
            graphics = getattr(sp, GRAPHICS_PROP, None)
            if (faces or bodies) and graphics is not None and not graphics.isNull():
                CIRCLE["kept"][sp.Name] = True
                _reshape(sp, graphics.copy())          # every face pickable inside the circle
        _overlay(True)
    else:
        for sp in sps:
            if not CIRCLE["kept"].pop(sp.Name, False):
                continue
            full = sp.Shape.copy()
            faces, bodies = included(sp)
            more = sorted(set(faces) | _mated_faces(sp, full))
            setattr(sp, FACES_PROP, more)
            _reshape(sp, included_shape(own(sp), full, more, bodies,
                                        getattr(sp, EXFACES_PROP, ()), getattr(sp, EXBODIES_PROP, ())))
        _overlay(False)
    if asm is not None:
        asm.Document.recompute()
    return on


class CircleOverlay(QtWidgets.QWidget if Gui else object):
    """The circle round the pointer over the graphics area (it lets every click through)."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("FW_SpeedPakCircle")
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setGeometry(view.rect())
        self.at = None
        view.installEventFilter(self)
        view.setMouseTracking(True)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.MouseMove:
            self.at = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self.update()
        elif t == QtCore.QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, e):
        if self.at is None:
            return
        from PySide import QtGui
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        try:
            from . import asmoptions
            alpha = asmoptions.speedpak_opacity() / 100.0     # Options > Display: 10..100 %
        except Exception:
            alpha = 1.0
        ink = QtGui.QColor(40, 110, 220)
        ink.setAlphaF(alpha)
        pen = QtGui.QPen(ink, 1.5)
        pen.setStyle(QtCore.Qt.DashLine)
        p.setPen(pen)
        p.drawEllipse(self.at, RADIUS, RADIUS)
        p.end()


def _view_widget():
    mw = Gui.getMainWindow()
    gl = [w for w in mw.findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget") and w.isVisible()]
    return max(gl, key=lambda w: w.width() * w.height()) if gl else None


def _overlay(on):
    old = CIRCLE["overlay"]
    CIRCLE["overlay"] = None
    if old is not None:
        try:
            old.parent().removeEventFilter(old)
            old.hide()
            old.deleteLater()
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:908", _fw_err)
    if on and Gui is not None:
        view = _view_widget()
        if view is not None:
            ov = CircleOverlay(view)
            ov.show()
            ov.raise_()
            CIRCLE["overlay"] = ov


class GraphicsCircleCommand:
    def GetResources(self):
        return {"MenuText": "Display SpeedPak Graphics Circle", "Accel": "Alt+S",
                "ToolTip": "Shows a circle round the pointer: every face of a SpeedPak inside it can be picked.",
                }

    def Activated(self, *args):
        set_circle(not circle_on())

    def IsActive(self):
        asm = ac.assembly_of(App.ActiveDocument) if App.ActiveDocument else None
        return asm is not None and bool(speedpak_components(asm))


COMMANDS.append(("SWStyle_SpeedPakGraphicsCircle", GraphicsCircleCommand()))


def register():
    install()
    try:
        checkstate.register("SWStyle_SpeedPakGraphicsCircle", circle_on)
    except Exception as _fw_err:
        _fw_log("asmspeedpak.py:940", _fw_err)
    for name, cmd in COMMANDS:
        try:
            Gui.addCommand(name, cmd)
        except Exception as _fw_err:
            _fw_log("asmspeedpak.py:945", _fw_err)
    checkstate.register("SWStyle_DisplayGraphicsComponents", display_graphics)
