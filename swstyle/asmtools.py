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
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt

from . import asmcore as ac

FADE = 0.75
_editing = None     # (assembly, component, {component: (override, material)}) while Edit Component runs


def _assembly():
    return ac.assembly_of(App.ActiveDocument)


def _picked_components(asm):
    out = []
    comps = ac.components(asm)
    for sel in Gui.Selection.getSelectionEx("", 0):
        if sel.Object in comps and sel.Object not in out:
            out.append(sel.Object)
        for sub in sel.SubElementNames:
            ref = ac.reference(asm, sel.Object, sub) if sub else None
            if ref is not None and ref[0] not in out:
                out.append(ref[0])
            elif sub:
                first = sub.split(".")[0]
                obj = asm.Document.getObject(first)
                if obj in comps and obj not in out:
                    out.append(obj)
    return out


def _tell(title, text):
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, text)


def _fade(comp, level=FADE):
    vobj = comp.ViewObject
    old = (vobj.OverrideMaterial, vobj.ShapeMaterial)
    source = getattr(getattr(comp, "LinkedObject", None), "ViewObject", None)
    material = App.Material()
    material.DiffuseColor = tuple((getattr(source, "ShapeColor", None) or (0.8, 0.8, 0.8))[:3])
    material.Transparency = level
    vobj.ShapeMaterial = material
    vobj.OverrideMaterial = True
    return old


def _restore(comp, old):
    try:
        comp.ViewObject.ShapeMaterial = old[1]
        comp.ViewObject.OverrideMaterial = old[0]
    except Exception as _fw_err:
        _fw_log("asmtools.py:79", _fw_err)


# ============================================================================= Edit Component
def editing():
    return _editing


def _status_editing_part():
    ""

    try:
        from . import chrome
    except Exception:
        return
    if getattr(chrome, "_fw_asm_editing_part", False):
        return
    chrome._fw_asm_editing_part = True
    old = chrome.editing_what

    def editing_what():
        what = old()
        if _editing is not None and what.startswith("Assembly"):
            return "Part" + what[len("Assembly"):]
        return what
    chrome.editing_what = editing_what


def edit_component(asm, comp):
    ""
    global _editing
    _status_editing_part()
    if comp.TypeId == "App::Link":
        _uncut(comp)
    body = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
    if body is not None and getattr(body.Document, "Partial", False):
        # an assembly opened again holds its parts loaded only in part: an edit there is not
        # rebuilt or saved. Load the part fully first (FreeCAD's Reload of a partial document)
        try:
            Gui.reload(body.Document.Name)
            body = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Edit Component: %s\n" % error)
    if body is None or body.TypeId != "PartDesign::Body":
        _tell("Edit Component", "Edit Component works on a part made of a body. %s is not one."
              % comp.Label)
        _recut(asm)
        return False
    view = Gui.ActiveDocument.ActiveView
    view.setActiveObject("pdbody", asm, comp.Name + ".")    # the body, reached through the component
    faded = {}
    from . import asmoptions
    mode = asmoptions.in_context()
    for other in ac.components(asm):
        if other is comp:
            continue
        try:
            if mode == "Force assembly transparency":
                faded[other] = _fade(other, asmoptions.in_context_level() / 100.0)
            elif mode == "Opaque assembly":         # see-through components show solid while editing
                vo = other.ViewObject
                faded[other] = (vo.OverrideMaterial, vo.ShapeMaterial)
                if vo.OverrideMaterial and vo.ShapeMaterial.Transparency > 0:
                    m = vo.ShapeMaterial
                    m.Transparency = 0.0
                    vo.ShapeMaterial = m
            # Maintain assembly transparency: the components keep their look
        except Exception as _fw_err:
            _fw_log("asmtools.py:123", _fw_err)
    try:
        from . import asmrefopts
        asmrefopts.edit_colours(asm, comp)      # Colors: Use specified colors when editing parts in assemblies
    except Exception as error:
        App.Console.PrintLog("FreeCAD: edit colours: %s\n" % error)
    _editing = (asm, comp, faded)
    _PICKS.install()
    try:
        Gui.getMainWindow().statusBar().showMessage("Editing %s" % comp.Label, 4000)
    except Exception as _fw_err:
        _fw_log("asmtools.py:133", _fw_err)
    _refresh()
    return True


class _ModelPicks(QtCore.QObject):
    ""




    def __init__(self):
        super().__init__()
        self.widgets = []
        self.pressed = None

    def install(self):
        self.remove()
        try:
            view = Gui.ActiveDocument.ActiveView.graphicsView()
            self.widgets = [view.viewport()]
            for w in self.widgets:
                w.installEventFilter(self)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context picks: %s\n" % error)
            self.widgets = []

    def remove(self):
        for w in self.widgets:
            try:
                w.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("asmtools.py:_ModelPicks.remove", _fw_err)
        self.widgets = []
        self.pressed = None

    def eventFilter(self, obj, event):
        try:
            if not isinstance(event, QtCore.QEvent):
                return False
            t = event.type()
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                    or event.button() != QtCore.Qt.LeftButton:
                return False
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if t == QtCore.QEvent.MouseButtonPress:
                self.pressed = pos
                return False
            start, self.pressed = self.pressed, None
            if start is None or (pos - start).manhattanLength() > 4 or _editing is None:
                return False
            ctrl = bool(event.modifiers() & QtCore.Qt.ControlModifier)
            dpr = obj.devicePixelRatioF()
            xy = (int(pos.x() * dpr), int((obj.height() - pos.y()) * dpr))
            QtCore.QTimer.singleShot(0, lambda: self._pick(xy, ctrl))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context picks: %s\n" % error)
        return False

    def _pick(self, xy, ctrl):
        if _editing is None:
            return
        asm, comp, _faded = _editing
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        sk = getattr(edit, "Object", None) if edit is not None else None
        if sk is None or "Sketch" not in sk.TypeId:
            return
        if Gui.Control.activeDialog() and _tool_page_open():
            return          # a sketch tool's page (Convert Entities...) takes model picks itself
        try:
            infos = gdoc.ActiveView.getObjectsInfo(xy) or []
        except Exception:
            infos = []
        if not infos:
            return
        info = infos[0]                 # the nearest: a sketch entity in front wins (nothing to add)
        par, sub = info.get("ParentObject"), info.get("SubName", "") or ""
        if par is not asm or "." not in sub:
            return
        other = asm.Document.getObject(sub.split(".")[0])
        if other is None or other is comp or other not in ac.components(asm):
            return
        element = sub.rsplit(".", 1)[-1]
        if not element.startswith(("Face", "Edge", "Vertex")):
            return
        sub = other.Name + "." + element    # through the component, as the tree and Select Other pick it
        picked = [(s.ObjectName, n) for s in Gui.Selection.getSelectionEx("", 0) for n in s.SubElementNames]
        if (asm.Name, sub) in picked:
            Gui.Selection.removeSelection(asm.Document.Name, asm.Name, sub)     # a second click takes it out
            return
        if not ctrl:        # a plain click picks only this; the sketch's own picks stay
            for s in Gui.Selection.getSelectionEx("", 0):
                if s.Object is asm:
                    for n in s.SubElementNames:
                        if not n.startswith(comp.Name + "."):
                            Gui.Selection.removeSelection(asm.Document.Name, asm.Name, n)
        Gui.Selection.addSelection(asm.Document.Name, asm.Name, sub)


def _tool_page_open():
    try:
        from . import sketchtoolpm
        return getattr(sketchtoolpm, "current", lambda: None)() is not None
    except Exception:
        return False


_PICKS = _ModelPicks()


_UNCUT = []         # components an assembly cut went through, shown as their part while edited


def _uncut(comp):
    ""

    try:
        from . import asmfeature
        if asmfeature.is_body(getattr(comp, "LinkedObject", None)):
            asmfeature._release(comp)
            _UNCUT.append(comp)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Edit Component: %s\n" % error)


def _recut(asm):
    if not _UNCUT:
        return
    del _UNCUT[:]
    try:
        from . import asmfeature
        feats = asmfeature.features(asm)
        if feats:
            asmfeature.update(feats[0], True)       # the cut bodies made again on the edited part
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly features after Edit Component: %s\n" % error)


def end_edit():
    """Back to the assembly: the part's body is no longer active, the components show solid."""
    global _editing
    if _editing is None:
        return
    asm, comp, faded = _editing
    _editing = None
    _PICKS.remove()
    try:
        from . import asmextref
        body = asmextref._body_of(comp)
        if body is not None:
            asmextref.prune(body.Document)
    except Exception as _fw_err:
        _fw_log("asmtools.py:151", _fw_err)
    try:
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", None)
    except Exception as _fw_err:
        _fw_log("asmtools.py:155", _fw_err)
    try:
        from . import asmrefopts
        asmrefopts.edit_colours(asm, comp, start=False)
    except Exception as _fw_err:
        _fw_log("asmtools.py:160", _fw_err)
    for other, old in faded.items():
        _restore(other, old)
    try:
        asm.Document.recompute()
    except Exception as _fw_err:
        _fw_log("asmtools.py:166", _fw_err)
    _recut(asm)
    _refresh()


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmtools.py:175", _fw_err)


class EditComponentCommand:
    def GetResources(self):
        return {"MenuText": "Edit Component", "Pixmap": "PartDesign_Body",
                "ToolTip": "Edits the selected part in the context of the assembly. "
                           "Click again to go back to editing the assembly."}

    def Activated(self):
        if _editing is not None:
            end_edit()
            return
        asm = _assembly()
        comps = _picked_components(asm) if asm is not None else []
        if not comps:
            from . import asmshowhidden         # tool first: the next component picked is edited
            asmshowhidden.edit_pick(asm)
            return
        edit_component(asm, comps[0])

    def IsActive(self):
        return _assembly() is not None or _editing is not None


# ============================================================================= Show Hidden Components
def show_hidden(asm):
    hidden = [c for c in ac.components(asm) if not c.Visibility]
    for comp in hidden:
        comp.Visibility = True
    return hidden


class ShowHiddenComponentsCommand:
    def GetResources(self):
        return {"MenuText": "Show Hidden Components", "Pixmap": "Std_ShowObjects",
                "ToolTip": "Shows the hidden components of the assembly."}

    def Activated(self):
        from . import asmshowhidden
        asmshowhidden.show_hidden(_assembly())

    def IsActive(self):
        return _assembly() is not None


# ============================================================================= Smart Fasteners


class SmartFastenersCommand:
    def GetResources(self):
        return {"MenuText": "Smart Fasteners", "Pixmap": "Assembly_InsertLink",
                "ToolTip": "Adds fasteners (screws, bolts, nuts, washers) to the assembly."}

    def Activated(self):
        from . import toolbox
        toolbox.open_smart_fasteners(_assembly())

    def IsActive(self):
        return _assembly() is not None


# ============================================================================= Linear Component Pattern
AXES = (("X", App.Vector(1, 0, 0)), ("Y", App.Vector(0, 1, 0)), ("Z", App.Vector(0, 0, 1)))


def linear_pattern(asm, comps, direction, spacing, count):
    """Instances 2..count of each component, spacing apart along direction; returns the new ones."""
    out = []
    step = App.Vector(direction).normalize() * spacing
    for comp in comps:
        target = comp.LinkedObject
        for i in range(1, count):
            placement = App.Placement(comp.Placement)
            placement.Base = comp.Placement.Base + step * i
            link = ac.insert(asm, target, placement)
            link.Placement = placement
            ac.fix(asm, link)          # the copies hold their place, as a pattern's instances do
            out.append(link)
    asm.Document.recompute()
    return out


class LinearPatternPanel:
    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        box, lay = asmpm._box("Direction 1", "Linear Pattern", "ASSEMBLIES_LINEAR_PATTERN")
        row = QtWidgets.QHBoxLayout()
        self.axis = QtWidgets.QComboBox()
        self.axis.setObjectName("FW_PatternAxis")
        self.axis.addItems([name for name, _ in AXES])
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        row.addWidget(self.axis, 1)
        row.addWidget(self.reverse)
        lay.addLayout(row)
        self.spacing = QtWidgets.QDoubleSpinBox()
        self.spacing.setObjectName("FW_PatternSpacing")
        self.spacing.setRange(0.001, 1.0e6)
        self.spacing.setDecimals(2)
        self.spacing.setSuffix("mm")
        self.spacing.setValue(25.0)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("FW_PatternCount")
        self.count.setRange(2, 1000)
        self.count.setValue(2)
        form = QtWidgets.QFormLayout()
        form.addRow("Spacing:", self.spacing)
        form.addRow("Instances:", self.count)
        lay.addLayout(form)
        seeds, lay2 = asmpm._box("Components to Pattern")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_PatternComponents")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        lay2.addWidget(self.list)
        from . import asmpattern
        asmpattern.mark_active(self.list)        # the box the picks go into at open (PM thread 11-27)
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [box, seeds]
        Gui.Selection.addObserver(self, 0)

    def _add(self, comp):
        if comp in self.comps:
            return
        self.comps.append(comp)
        self.list.addItem(comp.Label)

    def addSelection(self, doc, obj, sub, pnt):
        from . import safe_later as _sl; _sl.later(0, lambda: [self._add(c) for c in _picked_components(self.asm)], self, "list")

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def direction(self):
        d = App.Vector(AXES[self.axis.currentIndex()][1])
        return d * -1 if self.reverse.isChecked() else d

    def accept(self):
        Gui.Selection.removeObserver(self)
        if self.comps:
            doc = self.asm.Document
            doc.openTransaction("Linear Component Pattern")
            try:
                linear_pattern(self.asm, self.comps, self.direction(), self.spacing.value(), self.count.value())
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            _refresh()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Selection.removeObserver(self)
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class LinearComponentPatternCommand:
    def GetResources(self):
        return {"MenuText": "Linear Component Pattern", "Pixmap": "Assembly_InsertLink",
                "ToolTip": "Patterns components in a linear direction."}

    def Activated(self):
        from . import asmpm
        asm = _assembly()
        if not asmpm.close_open():
            return
        from . import asmcpattern
        panel = asmcpattern.LinearPanel(asm, _picked_components(asm))     # Direction 1/2, Instances to Skip
        asmcpattern.add_options(panel)
        asmpm._track(panel)
        Gui.Control.showDialog(panel)

    def IsActive(self):
        asm = _assembly()
        if asm is None or not ac.components(asm):
            return False
        from . import asmui
        return asmui._free()


COMMANDS = (("SWStyle_EditComponent", EditComponentCommand),
            ("SWStyle_LinearComponentPattern", LinearComponentPatternCommand),
            ("SWStyle_SmartFasteners", SmartFastenersCommand),
            ("SWStyle_ShowHiddenComponents", ShowHiddenComponentsCommand))


# ============================================================================= Interference Detection
def _global_shape(unit):
    """unit's shape where the assembly shows it (a part inside a subassembly too)."""
    from . import asmexplode as ax
    if ac.is_flexible(unit):
        import Part
        return Part.Compound([_global_shape(m) for m in ac.sub_components(unit) if not m.Shape.isNull()])
    shape = unit.Shape
    frame = ax._frame(unit)
    if shape.isNull() or frame.isIdentity():
        return shape
    shape = shape.copy()
    shape.Placement = frame.multiply(shape.Placement)
    return shape


def _shown(obj):
    try:
        return bool(obj.Visibility) and (obj.ViewObject is None or obj.ViewObject.Visibility)
    except Exception:
        return bool(getattr(obj, "Visibility", True))


def _suppressed(obj):
    """Suppressed: the component, or the subassembly's own component that this assembly's copy
    links (suppressed inside the subassembly)."""
    if getattr(obj, "FwComponentSuppressed", False):
        return True
    src = getattr(obj, "LinkedObject", None)
    return src is not None and src is not obj and bool(getattr(src, "FwComponentSuppressed", False))


def units(asm, comps=None, subassemblies=True, hidden=False):
    """What is checked against what: the components, or, with Treat subassemblies as components
    off, the parts inside each subassembly; hidden ones left out unless hidden is True."""
    out = []
    try:
        from . import asminsert
        envelope = asminsert.is_envelope
    except Exception:
        envelope = lambda c: False
    for c in list(comps or ac.components(asm)):
        if _suppressed(c):
            continue
        if not hidden and not _shown(c):
            continue
        if comps is None and envelope(c):
            continue
        if ac.is_subassembly(c) and not subassemblies:
            out += [m for m in ac.sub_components(c) if not _suppressed(m) and (hidden or _shown(m))]
        else:
            out.append(c)
    return out


def unit_label(unit):
    from . import asmexplode as ax
    return ax.display_name(unit)


FASTENER_WORDS = ("screw", "bolt", "nut", "washer", "rivet", "fastener", "stud", "dowel", "set screw",
                  "iso 4762", "iso 4017", "iso 4032", "din 912", "din 933", "din 934")


def is_fastener(unit):
    ""
    import re
    names = [getattr(unit, "Label", "")]
    try:
        names.append(ac.part_name(unit))
    except Exception as _fw_err:
        _fw_log("asmtools.py:426", _fw_err)
    text = " ".join(names).lower()
    return any(re.search(r"(^|[^a-z])%s" % re.escape(w), text) for w in FASTENER_WORDS)


def _common(a, b, coincidence, tol):
    if a.isNull() or b.isNull() or not a.BoundBox.intersect(b.BoundBox):
        return None
    try:
        common = a.common(b)
    except Exception:
        return None
    volume = common.Volume if not common.isNull() else 0.0
    if volume > tol:
        return common, volume
    if coincidence:
        try:
            if a.distToShape(b)[0] < 1e-7:
                return common, 0.0
        except Exception as _fw_err:
            _fw_log("asmtools.py:446", _fw_err)
    return None


def loose_faces(shape):
    """The faces of a shape that are not part of a solid: its surface bodies."""
    try:
        solids = shape.Solids
        if not solids:
            return list(shape.Faces)
        own = [f for s in solids for f in s.Faces]
        return [f for f in shape.Faces if not any(f.isSame(o) for o in own)]
    except Exception:
        return []


def _surface_hit(a, a_faces, b, b_faces, tol):
    ""

    import Part
    pieces = []
    try:
        if a_faces and b.Solids:
            for f in a_faces:
                c = Part.Compound(b.Solids).common(f) if len(b.Solids) > 1 else b.Solids[0].common(f)
                if not c.isNull() and c.Area > tol:
                    pieces.append(c)
        if b_faces and a.Solids:
            for f in b_faces:
                c = Part.Compound(a.Solids).common(f) if len(a.Solids) > 1 else a.Solids[0].common(f)
                if not c.isNull() and c.Area > tol:
                    pieces.append(c)
        if a_faces and b_faces:
            for f in a_faces:
                for g in b_faces:
                    if not f.BoundBox.intersect(g.BoundBox):
                        continue
                    c = f.section(g)
                    if not c.isNull() and c.Length > tol:
                        pieces.append(c)
    except Exception:
        return None
    if not pieces:
        return None
    return Part.Compound(pieces), 0.0


CANCELLED = [False]     # the last Calculate was stopped before it went through every pair


def interferences(asm, comps=None, coincidence=False, subassemblies=True, multibody=False, hidden=False, tol=1e-6,
                  surfaces=False, cancel=None):
    ""


    us = units(asm, comps, subassemblies, hidden)
    shapes = [_global_shape(u) for u in us]
    boxes = [None if s.isNull() else s.BoundBox for s in shapes]     # once each (300 parts: 45,000 pairs)
    loose = [loose_faces(s) if surfaces and s is not None and not s.isNull() else [] for s in shapes]
    out = []
    CANCELLED[0] = False
    for i in range(len(us)):
        if boxes[i] is None:
            continue
        if cancel is not None and cancel():
            CANCELLED[0] = True
            return out
        for j in range(i + 1, len(us)):
            if boxes[j] is None or not boxes[i].intersect(boxes[j]):
                continue
            hit = _common(shapes[i], shapes[j], coincidence, tol)
            surface = False
            if hit is None and (loose[i] or loose[j]):
                hit = _surface_hit(shapes[i], loose[i], shapes[j], loose[j], tol)
                surface = hit is not None
            if hit is not None:
                out.append({"a": us[i], "b": us[j], "labels": (unit_label(us[i]), unit_label(us[j])),
                            "common": hit[0], "volume": hit[1], "surface": surface,
                            "fastener": is_fastener(us[i]) or is_fastener(us[j]),
                            "thread": hit[1] > 0 and matching_thread(hit[0], us[i], us[j]),
                            "key": "%s|%s" % tuple(sorted((us[i].Name, us[j].Name)))})
    if multibody:
        for u, shape in zip(us, shapes):
            solids = shape.Solids
            for i in range(len(solids)):
                for j in range(i + 1, len(solids)):
                    hit = _common(solids[i], solids[j], coincidence, tol)
                    if hit is not None:
                        name = unit_label(u)
                        out.append({"a": u, "b": u, "labels": ("%s (Body%d)" % (name, i + 1), "%s (Body%d)" % (name, j + 1)),
                                    "common": hit[0], "volume": hit[1], "fastener": is_fastener(u),
                                    "key": "%s|Body%d|Body%d" % (u.Name, i + 1, j + 1)})
    return out


def component_interferences(asm, comps=None, coincidence=False, tol=1e-6):
    ""

    return [(f["a"], f["b"], f["common"], f["volume"]) for f in interferences(asm, comps, coincidence, tol=tol)]


IGNORED_PROP = "FwIgnoredInterferences"


def ignored(asm):
    return set(getattr(asm, IGNORED_PROP, []) or [])


def set_ignored(asm, key, on=True):
    ""
    if not hasattr(asm, IGNORED_PROP):
        asm.addProperty("App::PropertyStringList", IGNORED_PROP, "FreeCAD", "Ignored interferences")
        asm.setEditorMode(IGNORED_PROP, 2)
    keys = ignored(asm)
    if on:
        keys.add(key)
    else:
        keys.discard(key)
    setattr(asm, IGNORED_PROP, sorted(keys))


NON_INTERFERING = ("Wireframe", "Hidden", "Transparent", "Use current")


class _EscFilter(QtCore.QObject):
    """Esc while Calculate runs: stop it (and not the PropertyManager)."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        try:
            if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.KeyPress \
                    and event.key() == Qt.Key_Escape and getattr(self.panel, "_running", False):
                self.panel._stop = True
                return True
        except Exception as _fw_err:
            _fw_log("asmtools.py:584", _fw_err)
        return False


class InterferencePanel:
    ""




    def __init__(self, asm):
        from . import asmpm
        self.asm = asm
        self.found = []
        self.nodes = []
        self.faded = {}
        self.styled = {}
        sel, lay = asmpm._box("Selected Components", "Interference Detection", "ASSEMBLIES_INTERFERENCE_DETECTION")
        self.selected = QtWidgets.QListWidget()
        self.selected.setObjectName("FW_InterferenceSelected")
        self.selected.setStyleSheet(asmpm.PICK_STYLE)
        self.selected.setFixedHeight(asmpm._rows(self.selected, 3))
        self.selected.addItem(asm.Document.Label)
        lay.addWidget(self.selected)
        self.picked, self.excluded = [], []
        self.active = "selected"
        self.calculate = QtWidgets.QPushButton("Calculate")
        self.calculate.setObjectName("FW_InterferenceCalculate")
        self.calculate.clicked.connect(self.compute)
        lay.addWidget(self.calculate, 0, Qt.AlignLeft)
        exc, lay = asmpm._box("Excluded Components")
        self.use_excluded = QtWidgets.QCheckBox("Excluded Components")
        self.use_excluded.setObjectName("FW_InterferenceUseExcluded")
        lay.addWidget(self.use_excluded)
        self.excluded_list = QtWidgets.QListWidget()
        self.excluded_list.setObjectName("FW_InterferenceExcluded")
        self.excluded_list.setStyleSheet(asmpm.PICK_STYLE)
        self.excluded_list.setFixedHeight(asmpm._rows(self.excluded_list, 3))
        lay.addWidget(self.excluded_list)
        self.hide_excluded = asmpm._check("Hide excluded components", "InterferenceHideExcluded", False)
        self.hide_excluded.setObjectName("FW_InterferenceHideExcluded")
        self.hide_excluded.toggled.connect(lambda *_: self._show())
        lay.addWidget(self.hide_excluded)
        self.remember = asmpm._check("Remember excluded components", "InterferenceRemember", False)
        self.remember.setObjectName("FW_InterferenceRemember")
        lay.addWidget(self.remember)
        self._focus = _BoxFocus(self)
        for name, w in (("selected", self.selected), ("excluded", self.excluded_list)):
            w.setProperty("fw_box", name)
            w.installEventFilter(self._focus)
        self.use_excluded.toggled.connect(self._use_excluded)
        if self.remember.isChecked():
            saved = [asm.Document.getObject(n) for n in getattr(asm, EXCLUDED_PROP, []) or []]
            self.excluded = [c for c in saved if c is not None]
            if self.excluded:
                self.use_excluded.setChecked(True)
        self._use_excluded(self.use_excluded.isChecked())
        res, lay = asmpm._box("Results")
        self.results = QtWidgets.QTreeWidget()
        self.results.setObjectName("FW_InterferenceResults")
        self.results.setHeaderHidden(True)
        self.results.setFixedHeight(asmpm._rows(self.results, 6))
        self.results.itemSelectionChanged.connect(self._picked)
        lay.addWidget(self.results)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("FW_InterferenceSummary")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.ignore = QtWidgets.QPushButton("Ignore")
        self.ignore.setObjectName("FW_InterferenceIgnore")
        self.ignore.setToolTip("Ignore the selected interference (Show ignored interferences lists it again)")
        self.ignore.setVisible(False)
        self.ignore.clicked.connect(self.toggle_ignore)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.ignore)
        self.save_results = QtWidgets.QPushButton("Save Results...")
        self.save_results.setObjectName("FW_InterferenceSaveResults")
        self.save_results.setToolTip("Save the interferences to a report (.csv opens in Excel)")
        self.save_results.setVisible(False)
        self.save_results.clicked.connect(lambda *_: self.ask_save())
        row.addWidget(self.save_results)
        row.addStretch(1)
        lay.addLayout(row)
        self.component_view = asmpm._check("Component view", "InterferenceComponentView", False)
        self.component_view.setObjectName("FW_InterferenceComponentView")
        self.component_view.setToolTip("List the interferences under each component instead of by interference")
        self.component_view.toggled.connect(lambda *_: self._list())
        lay.addWidget(self.component_view)
        opts, lay = asmpm._box("Options")
        self.coincidence = asmpm._check("Treat coincidence as interference", "InterferenceCoincidence", False)
        lay.addWidget(self.coincidence)
        self.show_ignored = asmpm._check("Show ignored interferences", "InterferenceShowIgnored", False)
        self.show_ignored.setObjectName("FW_InterferenceShowIgnored")
        self.show_ignored.toggled.connect(lambda *_: self._list())
        lay.addWidget(self.show_ignored)
        self.subassemblies = asmpm._check("Treat subassemblies as components", "InterferenceSubassemblies", False)
        self.subassemblies.setObjectName("FW_InterferenceSubassemblies")
        lay.addWidget(self.subassemblies)
        self.multibody = asmpm._check("Include multibody part interferences", "InterferenceMultibody", False)
        self.multibody.setObjectName("FW_InterferenceMultibody")
        lay.addWidget(self.multibody)
        self.transparent = asmpm._check("Make interfering parts transparent", "InterferenceTransparent", True)
        self.transparent.toggled.connect(lambda *_: self._show())
        lay.addWidget(self.transparent)
        self.fasteners = asmpm._check("Create fasteners folder", "InterferenceFasteners", True)
        self.fasteners.setObjectName("FW_InterferenceFasteners")
        self.fasteners.toggled.connect(lambda *_: self._list())
        lay.addWidget(self.fasteners)
        self.threads = asmpm._check("Create matching cosmetic threads folder", "InterferenceThreads", True)
        self.threads.setObjectName("FW_InterferenceThreads")
        self.threads.toggled.connect(lambda *_: self._list())
        lay.addWidget(self.threads)
        self.skip_hidden = asmpm._check("Ignore hidden bodies/components", "InterferenceIgnoreHidden", True)
        self.skip_hidden.setObjectName("FW_InterferenceIgnoreHidden")
        lay.addWidget(self.skip_hidden)
        self.surfaces = asmpm._check("Include surface bodies", "InterferenceSurfaces", False)
        self.surfaces.setObjectName("FW_InterferenceSurfaces")
        self.surfaces.setToolTip("Also find surface bodies that cross a solid or another surface")
        lay.addWidget(self.surfaces)
        for box in (self.subassemblies, self.multibody, self.skip_hidden, self.coincidence, self.surfaces):
            box.toggled.connect(lambda *_: self.compute())
        non, lay = asmpm._box("Non-interfering Components")
        self.non = []
        group = QtWidgets.QButtonGroup(non)
        for name in NON_INTERFERING:
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("FW_NonInterfering_%s" % name.replace(" ", ""))
            r.setChecked(name == "Use current")
            r.toggled.connect(lambda on, *_: on and self._show())
            group.addButton(r)
            lay.addWidget(r)
            self.non.append(r)
        self.form = [sel, exc, res, opts, non]
        from . import asmevalpm
        asmevalpm.selection_box_menu(self.selected, lambda: self.picked, self._items, "FW_InterferenceSelectedMenu")
        asmevalpm.selection_box_menu(self.excluded_list, lambda: self.excluded,
                                     lambda: (self._items(), self._save_excluded()), "FW_InterferenceExcludedMenu")
        asmevalpm.results_menu(self, self.results, "FW_InterferenceResultsMenu", self._zoom_shapes)
        Gui.Selection.addObserver(self)

    def _zoom_shapes(self, k):
        if k is None:
            return []
        f = self.found[k]
        if f.get("common") is not None and (f["volume"] > 0 or f.get("surface")):
            return [f["common"]]
        from . import asmevalpm
        return asmevalpm.comp_shapes([f["a"], f["b"]])

    # ------------------------------------------------------------ picks
    def _use_excluded(self, on):
        for w in (self.excluded_list, self.remember, self.hide_excluded):
            if not hasattr(w, "_fw_take_over"):
                from .asmpattern import _takes_over
                _takes_over(w, self.use_excluded, True)      # live: using one turns Excluded Components on
        if on:
            self.active = "excluded"
        elif self.active == "excluded":
            self.active = "selected"
        self._items()

    def _items(self):
        self.selected.clear()
        if not self.picked:
            self.selected.addItem(self.asm.Document.Label)      # the whole assembly
        for c in self.picked:
            self.selected.addItem(c.Label)
        self.excluded_list.clear()
        for c in self.excluded:
            self.excluded_list.addItem(c.Label)

    def pick(self, comp, box=None):
        """A component picked into the active box (Selected Components or Excluded Components)."""
        box = box or self.active
        target = self.excluded if box == "excluded" else self.picked
        other = self.picked if box == "excluded" else self.excluded
        if comp in target:
            return
        target.append(comp)
        if comp in other:
            other.remove(comp)
        self._items()
        if box == "excluded":
            self._save_excluded()

    def _save_excluded(self):
        if not self.remember.isChecked():
            return
        if not hasattr(self.asm, EXCLUDED_PROP):
            self.asm.addProperty("App::PropertyStringList", EXCLUDED_PROP, "FreeCAD", "Excluded from Interference Detection")
            self.asm.setEditorMode(EXCLUDED_PROP, 2)
        setattr(self.asm, EXCLUDED_PROP, [c.Name for c in self.excluded])

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.asm.Document.Name:
            return
        obj = self.asm.Document.getObject(name)
        comps = ac.components(self.asm)
        comp = obj if obj is not None and any(c.Name == obj.Name for c in comps) else None
        if comp is None and obj is self.asm and sub:
            comp = next((c for c in comps if c.Name == sub.split(".")[0]), None)
        if comp is not None:
            QtCore.QTimer.singleShot(0, lambda: self.pick(comp))

    def removeSelection(self, *a):
        pass

    def setSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def checked_components(self):
        """What Calculate checks: the picked components (or the whole assembly), less the excluded."""
        comps = list(self.picked) or list(ac.components(self.asm))
        if self.use_excluded.isChecked():
            comps = [c for c in comps if c not in self.excluded]
        return comps

    # ------------------------------------------------------------ results
    def compute(self):
        if getattr(self, "_running", False):
            self._stop = True
            return
        self._clear()
        import time
        self._running, self._stop = True, False
        start = [time.time(), time.time()]
        bar = Gui.getMainWindow().statusBar()

        def cancel():
            # a long run keeps the window alive: Calculate turns to Cancel, Esc stops it too
            now = time.time()
            if now - start[1] > 0.25:
                start[1] = now
                if self.calculate.text() != "Cancel":
                    self.calculate.setText("Cancel")
                    bar.showMessage("Calculating interferences... press Cancel or Esc to stop")
                QtWidgets.QApplication.processEvents()
            return self._stop

        filt = _EscFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(filt)
        try:
            self.found = interferences(self.asm, comps=self.checked_components(), coincidence=self.coincidence.isChecked(),
                                       subassemblies=self.subassemblies.isChecked(),
                                       multibody=self.multibody.isChecked(), hidden=not self.skip_hidden.isChecked(),
                                       surfaces=self.surfaces.isChecked(), cancel=cancel)
        finally:
            QtWidgets.QApplication.instance().removeEventFilter(filt)
            self._running = False
            try:
                self.calculate.setText("Calculate")
                bar.clearMessage()
            except RuntimeError:
                return
        self.cancelled = CANCELLED[0]
        if self.cancelled:
            bar.showMessage("Interference Detection canceled: %d interference(s) found before it stopped" % len(self.found), 6000)
        self._list()

    def shown_found(self):
        """The interferences the Results list (ignored ones only with Show ignored interferences)."""
        skip = ignored(self.asm)
        return [k for k, f in enumerate(self.found) if self.show_ignored.isChecked() or f["key"] not in skip]

    def _text(self, k):
        f = self.found[k]
        text = "Interference%d - %.2fmm^3" % (k + 1, f["volume"]) if f["volume"] > 0 else \
            "Interference%d - Surface" % (k + 1) if f.get("surface") else \
            "Interference%d - Coincident" % (k + 1)
        return text + (" (Ignored)" if f["key"] in ignored(self.asm) else "")

    def report_rows(self):
        """Results > Save Results: one row per interference the list shows (as the Excel report)."""
        rows = [("Interference", "Volume (mm^3)", "Component 1", "Component 2", "Type", "Ignored")]
        skip = ignored(self.asm)
        for k in self.shown_found():
            f = self.found[k]
            kind = "Matching Cosmetic Thread" if f.get("thread") else "Fastener" if f.get("fastener") else \
                ("Surface" if f.get("surface") else "Coincident" if f["volume"] <= 0 else "Interference")
            names = (list(f.get("labels") or [f["a"].Label, f["b"].Label]) + ["", ""])[:2]
            rows.append(("Interference%d" % (k + 1), "%.2f" % max(f["volume"], 0.0), names[0], names[1],
                         kind, "Yes" if f["key"] in skip else "No"))
        return rows

    def save(self, path):
        import csv
        tab = path.lower().endswith(".txt")
        with open(path, "w", newline="", encoding="utf-8-sig") as out:
            w = csv.writer(out, delimiter="\t" if tab else ",")
            w.writerow(["Interference Detection", self.asm.Document.Label])
            for r in self.report_rows():
                w.writerow(r)
        return path

    def ask_save(self):
        import os
        start = ""
        if self.asm.Document.FileName:
            start = os.path.splitext(self.asm.Document.FileName)[0] + "_Interference.csv"
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Results", start,
                                                         "CSV (Excel) (*.csv);;Text (Tab delimited) (*.txt)")
        if path:
            return self.save(path)
        return None

    def _item(self, parent, text, k=None):
        item = QtWidgets.QTreeWidgetItem([text]) if parent is None else QtWidgets.QTreeWidgetItem(parent, [text])
        if k is not None:
            item.setData(0, Qt.UserRole, k)
            if self.found[k]["key"] in ignored(self.asm):
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#8a8a8a")))
        return item

    def _list(self):
        self.results.clear()
        shown = self.shown_found()
        skip = ignored(self.asm)
        tops = []
        fasteners = None
        threads = None
        if self.threads.isChecked() and any(self.found[k].get("thread") for k in shown):
            threads = self._item(None, "Matching Cosmetic Threads")
            for k in [k for k in shown if self.found[k].get("thread")]:
                item = self._item(threads, self._text(k), k)
                for name in self.found[k]["labels"]:
                    self._item(item, name)
            shown = [k for k in shown if not self.found[k].get("thread")]
        if self.fasteners.isChecked() and any(self.found[k]["fastener"] for k in shown):
            fasteners = self._item(None, "Fasteners")
        if self.component_view.isChecked():
            names = []
            for k in shown:
                for name in self.found[k]["labels"]:
                    if name not in names:
                        names.append(name)
            for name in names:
                ks = [k for k in shown if name in self.found[k]["labels"]]
                parent = fasteners if fasteners is not None and all(self.found[k]["fastener"] for k in ks) else None
                comp = self._item(parent, name)
                for k in ks:
                    self._item(comp, self._text(k), k)
                if parent is None:
                    tops.append(comp)
        else:
            for k in shown:
                f = self.found[k]
                parent = fasteners if fasteners is not None and f["fastener"] else None
                item = self._item(parent, self._text(k), k)
                for name in f["labels"]:
                    self._item(item, name)
                if parent is None:
                    tops.append(item)
        for item in tops:
            self.results.addTopLevelItem(item)
        if fasteners is not None:
            self.results.addTopLevelItem(fasteners)
        if threads is not None:
            self.results.addTopLevelItem(threads)
        self.results.expandAll()
        self.save_results.setVisible(bool(self.shown_found()))
        live = [k for k in range(len(self.found)) if self.found[k]["key"] not in skip]
        n = len(units(self.asm, subassemblies=self.subassemblies.isChecked(), hidden=not self.skip_hidden.isChecked()))
        self.summary.setText("No Interferences" if not live else
                             "%d interference%s among %d components." % (len(live), "" if len(live) == 1 else "s", n))
        self.ignore.setVisible(bool(self.shown_found()))
        self.ignore.setText("Ignore")
        self._show()

    def picked_index(self):
        items = self.results.selectedItems()
        if not items:
            return None
        item = items[0]
        k = item.data(0, Qt.UserRole)
        if k is None and item.parent() is not None:
            k = item.parent().data(0, Qt.UserRole)
        return k

    def toggle_ignore(self):
        k = self.picked_index()
        if k is None:
            try:            # asmpkg373: nothing picked yet: say what to do first
                QtWidgets.QToolTip.showText(self.ignore.mapToGlobal(self.ignore.rect().bottomLeft()),
                                            "Select an interference in Results, then click Ignore.", self.ignore)
            except Exception as _fw_err:
                _fw_log("asmtools.toggle_ignore", _fw_err)
            return
        key = self.found[k]["key"]
        set_ignored(self.asm, key, key not in ignored(self.asm))
        self._list()

    def _show(self, only=None):
        """Red volumes, see-through interfering parts, the chosen look for the others."""
        self._clear()
        involved = set()
        skip = ignored(self.asm)
        for k, f in enumerate(self.found):
            if (only is not None and k != only) or (only is None and f["key"] in skip):
                continue
            from . import asmexplode as ax
            for u in (f["a"], f["b"]):
                involved.update(ax.movers(u))
            if f["volume"] > 0:
                self._red(f["common"])
        if self.transparent.isChecked():
            for comp in involved:
                try:
                    self.faded[comp] = _fade(comp, 0.6)
                except Exception as _fw_err:
                    _fw_log("asmtools.py:992", _fw_err)
        mode = NON_INTERFERING[[r.isChecked() for r in self.non].index(True)]
        hide_out = self.use_excluded.isChecked() and self.hide_excluded.isChecked()
        for comp in ac.components(self.asm):
            if hide_out and comp in self.excluded:
                self.styled[comp] = ("Visibility", comp.Visibility)
                comp.Visibility = False
                continue
            if comp in involved or mode == "Use current":
                continue
            vobj = comp.ViewObject
            if mode == "Transparent":
                self.faded[comp] = _fade(comp, 0.85)
            elif mode == "Hidden":
                self.styled[comp] = ("Visibility", comp.Visibility)
                comp.Visibility = False
            elif mode == "Wireframe" and hasattr(vobj, "DisplayMode"):
                self.styled[comp] = ("DisplayMode", vobj.DisplayMode)
                try:
                    vobj.DisplayMode = "Wireframe"
                except Exception:
                    self.styled.pop(comp, None)

    def _red(self, shape):
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        sep = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(1.0, 0.0, 0.0)
        mat.emissiveColor.setValue(0.5, 0.0, 0.0)
        sep.addChild(mat)
        inp = coin.SoInput()
        inp.setBuffer(shape.writeInventor())
        node = coin.SoDB.readAll(inp)
        if node is None:
            return
        sep.addChild(node)
        view.getSceneGraph().addChild(sep)
        self.nodes.append(sep)

    def _picked(self):
        k = self.picked_index()
        if k is None:
            self.ignore.setText("Ignore")       # asmpkg373: stays in sight (no dead control: its click says what to pick)
            self._show()
            return
        self.ignore.setVisible(True)
        self.ignore.setText("Un-Ignore" if self.found[k]["key"] in ignored(self.asm) else "Ignore")
        self._show(k)

    def _clear(self):
        try:
            root = Gui.ActiveDocument.ActiveView.getSceneGraph()
            for node in self.nodes:
                root.removeChild(node)
        except Exception as _fw_err:
            _fw_log("asmtools.py:1048", _fw_err)
        self.nodes = []
        for comp, old in self.faded.items():
            _restore(comp, old)
        self.faded = {}
        for comp, (prop, value) in self.styled.items():
            try:
                if prop == "Visibility":
                    comp.Visibility = value
                else:
                    setattr(comp.ViewObject, prop, value)
            except Exception as _fw_err:
                _fw_log("asmtools.py:1060", _fw_err)
        self.styled = {}

    def accept(self):
        self._clear()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmtools.py:1068", _fw_err)
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class _BoxFocus(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            box = obj.property("fw_box")
            if box:
                self.panel.active = box
        return False


EXCLUDED_PROP = "FwInterferenceExcluded"


def matching_thread(common, a, b):
    ""

    try:
        if common is None or common.isNull() or not (is_fastener(a) or is_fastener(b)):
            return False
        cyl = [f for f in common.Faces if type(f.Surface).__name__ == "Cylinder"]
        if not cyl:
            return False
        ax0 = cyl[0].Surface.Axis
        c0 = cyl[0].Surface.Center
        for f in cyl[1:]:
            d = f.Surface.Center - c0
            if abs(abs(f.Surface.Axis.dot(ax0)) - 1) > 1e-6 or (d - ax0 * d.dot(ax0)).Length > 1e-4:
                return False
        others = [f for f in common.Faces if type(f.Surface).__name__ not in ("Cylinder", "Plane")]
        return not others
    except Exception:
        return False


class AssemblyInterferenceCommand:
    def GetResources(self):
        return {"MenuText": "Interference Detection", "Pixmap": "Part_Common",
                "ToolTip": "Finds interferences between the components of the assembly."}

    def Activated(self):
        from . import asmpm
        asm = _assembly()
        if asm is None:      # a part: the look's multibody Interference Detection
            Gui.runCommand(PART_INTERFERENCE, 0)
            return
        if not asmpm.close_open():
            return
        panel = InterferencePanel(asm)
        asmpm._track(panel)
        Gui.Control.showDialog(panel)
        QtCore.QTimer.singleShot(0, panel.compute)

    def IsActive(self):
        asm = _assembly()
        if asm is None:
            try:
                return Gui.Command.get(PART_INTERFERENCE).isActive()
            except Exception:
                return False
        if not ac.components(asm):
            return False
        from . import asmui
        return asmui._free()


PART_INTERFERENCE = "SWStyle_InterferenceDetection"
COMMANDS = COMMANDS + (("SWStyle_AssemblyInterference", AssemblyInterferenceCommand),)


# ============================================================================= No External References
def external_refs_off():
    ""
    from . import asmrefopts
    return not asmrefopts.on(asmrefopts.ALLOW_EXTERNAL)


def set_external_refs_off(on):
    from . import asmrefopts, optionspages
    page, text, _default = asmrefopts.ALLOW_EXTERNAL
    optionspages.set_stored(page, text, not on)
    try:
        Gui.getMainWindow().statusBar().showMessage(
            "No External References: %s" % ("on: in-context edits copy geometry, no references" if on else "off"), 4000)
    except Exception as _fw_err:
        _fw_log("asmtools.py:nxr", _fw_err)


class NoExternalReferencesCommand:
    def GetResources(self):
        return {"MenuText": "No External References", "Pixmap": "PartDesign_SubShapeBinder",
                "ToolTip": "When on, editing a part in the assembly makes no external references: "
                           "geometry taken from other components is copied, and a new part is not "
                           "mated in place."}

    def Activated(self, *args):
        set_external_refs_off(not external_refs_off())

    def IsActive(self):
        return True


COMMANDS = COMMANDS + (("SWStyle_NoExternalReferences", NoExternalReferencesCommand),)
try:
    from . import checkstate as _checkstate
    _checkstate.register("SWStyle_NoExternalReferences", external_refs_off)
except Exception as _fw_err:
    _fw_log("asmtools.py:nxr-check", _fw_err)
try:

    _checkstate.register("SWStyle_EditComponent", lambda: _editing is not None)
except Exception as _fw_err:
    _fw_log("asmtools.py:editcomp-check", _fw_err)
