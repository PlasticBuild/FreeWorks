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

from . import asmcore as ac
from . import paths

Qt = QtCore.Qt
AXES = (("X", App.Vector(1, 0, 0)), ("Y", App.Vector(0, 1, 0)), ("Z", App.Vector(0, 0, 1)))
STEP_TYPES = ("Regular step (translate and rotate)", "Radial step")
STEP_PROP = "FwStep"            # json: rotation axis and angle, about each origin, spacing distances, radial axis
AUTOSPACE_PARAM = "ExplodeAutoSpace"
SPACING_PARAM = "ExplodeSpacing"
RINGS_PARAM = "ExplodeRotationRings"
SUBPARTS_PARAM = "ExplodeSubassemblyParts"
ROT_ORIGIN_PARAM = "ExplodeRotateOrigin"
ORDER_PARAM = "ExplodeSpaceOrder"
BBOX_PARAM = "ExplodeRadialBBoxCenter"
ORDERS = (("center", "Bounding box center"), ("back", "Bounding box back"), ("front", "Bounding box front"))


def _assembly():
    return ac.assembly_of(App.ActiveDocument)


def _cv():
    import CommandCreateView
    return CommandCreateView


def _ua():
    import UtilsAssembly
    return UtilsAssembly


# ----------------------------------------------------------------------------- the model
def views(asm):
    """The assembly's exploded views (FreeCAD's objects), in order."""
    out = []
    for obj in asm.OutListRecursive:
        if obj.TypeId == "App::FeaturePython" and type(getattr(obj, "Proxy", None)).__name__ == "ExplodedView":
            out.append(obj)
    return out


def _props(view):
    if not hasattr(view, "FwExploded"):
        view.addProperty("App::PropertyBool", "FwExploded", "FreeCAD", "The assembly is shown exploded")
        view.addProperty("App::PropertyStringList", "FwBaseNames", "FreeCAD", "Components of the mated positions")
        view.addProperty("App::PropertyPlacementList", "FwBasePlacements", "FreeCAD", "The mated positions")
        for name in ("FwExploded", "FwBaseNames", "FwBasePlacements"):
            view.setEditorMode(name, 2)


def new_view(asm):
    cv = _cv()
    group = _ua().getViewGroup(asm)
    try:
        if App.GuiUp and group.ViewObject is not None:
            group.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("asmexplode.py:95", _fw_err)
    n = len(views(asm)) + 1
    view = group.newObject("App::FeaturePython", "ExplView%d" % n)
    cv.ExplodedView(view)
    if App.GuiUp:
        cv.ViewProviderExplodedView(view.ViewObject)
    view.Label = "ExplView%d" % n
    _props(view)
    return view


# ----------------------------------------------------------------------------- parts inside subassemblies
def holder(obj):
    """The subassembly component that holds obj (a part picked inside it), else None."""
    for p in getattr(obj, "InList", []) or []:
        if ac.is_subassembly(p) and obj in (p.Group or []):
            return p
    return None


def _frame(obj):
    """The placement obj's own Placement is measured in (its subassembly's, else the assembly's)."""
    h = holder(obj)
    if h is None:
        return App.Placement()
    try:
        g = h.getSubObject(obj.Name + ".", retType=3)
        return g.multiply(obj.Placement.inverse())
    except Exception:
        return App.Placement(h.Placement)


def gplacement(obj):
    return _frame(obj).multiply(obj.Placement)


def set_gplacement(obj, plc):
    obj.Placement = _frame(obj).inverse().multiply(plc)


def gbox(obj):
    """obj's bounding box in the assembly."""
    if ac.is_flexible(obj):
        out = App.BoundBox()
        for m in ac.sub_components(obj):
            b = gbox(m)
            if b.isValid():
                out.add(b)
        return out
    try:
        bb = obj.Shape.BoundBox
    except Exception:
        return App.BoundBox()
    if not bb.isValid():
        return bb
    f = _frame(obj)
    if f.isIdentity():
        return bb
    out = App.BoundBox()
    for i in range(8):
        out.add(f.multVec(bb.getPoint(i)))
    return out


def gcentre(obj):
    return gbox(obj).Center


def movers(comp):
    """What moves when comp moves: a flexible subassembly's own parts (FreeCAD places them in
    the assembly then), else comp itself."""
    if ac.is_flexible(comp):
        return ac.sub_components(comp) or [comp]
    return [comp]


def move_by(comp, plc):
    """Moves comp by plc (applied in the assembly's frame)."""
    for m in movers(comp):
        set_gplacement(m, plc.multiply(gplacement(m)))


def ref_name(obj):
    """The step's reference: "Part." or, inside a subassembly, "Sub.Part."."""
    h = holder(obj)
    return (h.Name + "." if h is not None else "") + obj.Name + "."


def display_name(obj):
    """The Components list's text: PartA<2>@Sub<1> for a part inside a subassembly."""
    h = holder(obj)
    return "%s@%s" % (ac.source_label(obj), h.Label) if h is not None else obj.Label


def nested_parts(asm):
    """Every part inside the assembly's subassemblies."""
    out = []
    for c in ac.components(asm):
        if ac.is_subassembly(c):
            out += [o for o in ac.sub_components(c)]
    return out


def steps(view):
    return list(view.Group)


def step_components(asm, step):
    out = []
    root, subs = step.References if step.References else (None, [])
    for sub in subs or []:
        names = [n for n in sub.split(".") if n]
        obj = asm.Document.getObject(names[-1]) if names else None
        if obj is not None:
            out.append(obj)
    return out


def add_step(asm, view, comps, direction, distance, radial=False, axis=None, angle=0.0, origin=True,
             distances=None, index=None, bbox=False):
    """One explode step: comps along direction by distance (each its own distance in distances,
    for Auto-space), turned by angle about axis (about each component's origin, or about their
    common centre); radial: pushed out from the line along direction through their centre."""
    import json
    cv = _cv()
    step = asm.newObject("App::FeaturePython", "Move")
    cv.ExplodedViewStep(step, 1 if radial else 0)
    if App.GuiUp:
        cv.ViewProviderExplodedViewStep(step.ViewObject)
    move = App.Vector(direction).normalize() * distance if direction.Length > 0 else App.Vector()
    rot = App.Rotation(App.Vector(axis), angle) if axis is not None and abs(angle) > 1e-12 else App.Rotation()
    centre = _centre(comps)
    step.MovementTransform = App.Placement(move, rot, centre if not origin else App.Vector())
    step.References = [asm, [ref_name(c) for c in comps]]
    step.addProperty("App::PropertyString", STEP_PROP, "FreeCAD", "FreeCAD explode step settings")
    step.setEditorMode(STEP_PROP, 2)
    setattr(step, STEP_PROP, json.dumps({
        "direction": list(App.Vector(direction)), "distance": float(distance), "radial": bool(radial),
        "axis": list(App.Vector(axis)) if axis is not None else [0, 0, 1], "angle": float(angle),
        "origin": bool(origin), "distances": [float(d) for d in distances] if distances else None,
        "bbox": bool(bbox)}))
    group = view.Group
    if index is None or index >= len(group):
        group.append(step)
    else:
        group.insert(index, step)
    view.Group = group
    _relabel(view)
    return step


def _sub_map(sub):
    """{the subassembly's own component: this assembly's copy of it} for a subassembly component."""
    out = {}
    try:
        theirs = ac.components(sub.LinkedObject)
    except Exception:
        return out
    mine = ac.sub_components(sub)
    for i, c in enumerate(theirs):
        hit = [o for o in mine if getattr(o, "LinkedObject", None) is c]
        if not hit:
            same = [o for o in mine if getattr(o, "LinkedObject", None) is getattr(c, "LinkedObject", None)]
            k = [x for x in theirs if getattr(x, "LinkedObject", None) is getattr(c, "LinkedObject", None)].index(c)
            hit = same[k:k + 1]
        if hit:
            out[c] = hit[0]
        elif i < len(mine):
            out[c] = mine[i]
    return out


def _step_values(step):
    ""
    data = step_data(step)
    if data:
        return data
    t = step.MovementTransform
    d = App.Vector(t.Base)
    axis = t.Rotation.Axis
    return {"direction": list(d.normalize() if d.Length > 1e-12 else App.Vector(0, 0, 1)), "distance": float(t.Base.Length),
            "radial": getattr(step, "MovementType", "") == "Radial", "axis": list(axis),
            "angle": float(t.Rotation.Angle * 180.0 / 3.141592653589793), "origin": True, "distances": None}


def reuse_subassembly(asm, view, sub):
    """Reuse Subassembly Explode: the subassembly's explode steps (its first exploded view) added
    to this explode, on this assembly's copies of its parts. Returns the steps added."""
    try:
        theirs = views(sub.LinkedObject)
    except Exception:
        theirs = []
    if not theirs:
        return []
    mapping = _sub_map(sub)
    added = []
    for st in steps(theirs[0]):
        comps = [mapping[c] for c in step_components(sub.LinkedObject, st) if c in mapping]
        if not comps:
            continue
        v = _step_values(st)
        added.append(add_step(asm, view, comps, App.Vector(*v["direction"]), v["distance"], radial=v.get("radial", False),
                              axis=App.Vector(*v.get("axis", [0, 0, 1])), angle=v.get("angle", 0.0),
                              origin=v.get("origin", True), distances=v.get("distances"), bbox=v.get("bbox", False)))
    return added


def _relabel(view):
    for i, step in enumerate(view.Group):
        step.Label = "Explode Step%d" % (i + 1)


def step_data(step):
    import json
    try:
        return json.loads(getattr(step, STEP_PROP, "") or "{}") or None
    except ValueError:
        return None


def remove_step(asm, view, step):
    group = [s for s in view.Group if s is not step]
    view.Group = group
    asm.Document.removeObject(step.Name)
    _relabel(view)


def _centre(comps):
    box = App.BoundBox()
    for c in comps:
        try:
            b = gbox(c)
            if b.isValid():
                box.add(b)
        except Exception as _fw_err:
            _fw_log("asmexplode.py:329", _fw_err)
    return box.Center if box.isValid() else App.Vector()


def _order_key(comp, d, order):
    ""

    if order == "center":
        return d.dot(gcentre(comp))
    box = gbox(comp)
    if not box.isValid():
        return d.dot(gcentre(comp))
    ends = [d.dot(box.getPoint(i)) for i in range(8)]
    return min(ends) if order == "back" else max(ends)


def spaced(comps, direction, distance, spacing, order="center"):
    """Auto-space: the components in order along the direction, the farthest moved the whole
    distance and the others less, spacing (0-100 %) apart."""
    d = App.Vector(direction)
    if d.Length < 1e-12 or len(comps) < 2:
        return list(comps), None
    d.normalize()
    order = sorted(comps, key=lambda c: _order_key(c, d, order))
    n = len(order)
    gap = float(spacing) / 100.0 * float(distance) / n
    return order, [float(distance) - (n - 1 - i) * gap for i in range(n)]


def _apply_own(asm, step, data):
    ""
    comps = step_components(asm, step)
    direction = App.Vector(*data["direction"])
    if direction.Length > 1e-12:
        direction.normalize()
    centre = _centre(comps)
    axis = App.Vector(*data.get("axis", [0, 0, 1]))
    angle = float(data.get("angle", 0.0))
    dists = data.get("distances") or [data["distance"]] * len(comps)
    lines = []
    for comp, dist in zip(comps, dists):
        start = gcentre(comp)
        if data.get("radial"):
            out = start - centre
            if not data.get("bbox"):        # out from the axis; Explode from bounding box center: straight out
                out = out - direction * out.dot(direction)
            move = App.Vector(out).normalize() * dist if out.Length > 1e-9 else App.Vector()
        else:
            move = direction * dist
        rot = App.Rotation(axis, angle) if abs(angle) > 1e-12 and axis.Length > 1e-12 else App.Rotation()
        about = gplacement(comp).Base if data.get("origin", True) else centre
        move_by(comp, App.Placement(move, rot, about))
        lines.append([start, gcentre(comp)])
    try:
        step.ViewObject.Proxy.redrawLines(step, lines)
    except Exception as _fw_err:
        _fw_log("asmexplode.py:384", _fw_err)


def apply_steps(asm, view):
    ""
    com, size = _ua().getComAndSize(asm)
    for step in view.Group:
        data = step_data(step)
        if data:
            _apply_own(asm, step, data)
        else:
            step.Proxy.applyStep(step, com, size)


def is_exploded(view):
    return bool(getattr(view, "FwExploded", False))


def collapse(asm, view):
    """Back to the mated positions."""
    if not is_exploded(view):
        return
    for name, plc in zip(view.FwBaseNames, view.FwBasePlacements):
        obj = asm.Document.getObject(name)
        if obj is not None:
            obj.Placement = plc
    view.FwExploded = False
    EXPLODED.pop((asm.Document.Name, view.Name), None)
    _clear_lines(view)
    asm.Document.recompute()


def explode(asm, view):
    """Mated positions kept, then every step applied in order."""
    _props(view)
    if is_exploded(view):
        collapse(asm, view)
    comps = ac.components(asm) + nested_parts(asm)
    view.FwBaseNames = [c.Name for c in comps]
    view.FwBasePlacements = [c.Placement for c in comps]
    try:
        apply_steps(asm, view)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: explode: %s\n" % error)
    view.FwExploded = True
    # no recompute: the assembly would solve its mates again and pull the components back

    for obj in [asm] + comps:
        obj.purgeTouched()
    _keep(asm, view, comps)


# --------------------------------------------------------------- exploded through a rebuild
EXPLODED = {}       # (document, view): True while a rebuild has put the mated positions back
_watcher = None


def _keep(asm, view, comps):
    ""



    global _watcher
    EXPLODED[(asm.Document.Name, view.Name)] = False
    if _watcher is None:
        _watcher = _Rebuild()
        App.addDocumentObserver(_watcher)


def _views_of(doc):
    for (dname, vname) in list(EXPLODED):
        if dname != doc.Name:
            continue
        view = doc.getObject(vname)
        if view is None or not is_exploded(view):
            EXPLODED.pop((dname, vname), None)
            continue
        yield view


class _Rebuild:
    def slotBeforeRecomputeDocument(self, doc):
        try:
            asm = ac.assembly_of(doc)
            for view in _views_of(doc):
                if asm is None or EXPLODED.get((doc.Name, view.Name)):
                    continue
                for name, plc in zip(view.FwBaseNames, view.FwBasePlacements):
                    obj = doc.getObject(name)
                    if obj is not None and not obj.Placement.isSame(plc, 1e-9):
                        obj.Placement = plc
                EXPLODED[(doc.Name, view.Name)] = True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view before rebuild: %s\n" % error)

    def slotRecomputedDocument(self, doc):
        try:
            asm = ac.assembly_of(doc)
            for view in _views_of(doc):
                if asm is None or not EXPLODED.get((doc.Name, view.Name)):
                    continue
                EXPLODED[(doc.Name, view.Name)] = False
                comps = ac.components(asm) + nested_parts(asm)
                view.FwBaseNames = [c.Name for c in comps]
                view.FwBasePlacements = [c.Placement for c in comps]      # mated, as solved now
                try:
                    apply_steps(asm, view)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: explode: %s\n" % error)
                for obj in [asm] + comps:
                    obj.purgeTouched()
                _redraw_lines(asm, view)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view after rebuild: %s\n" % error)

    def slotDeletedDocument(self, doc):
        for key in [k for k in EXPLODED if k[0] == doc.Name]:
            EXPLODED.pop(key, None)

    def slotStartSaveDocument(self, doc, filename):
        ""

        try:
            for view in _views_of(doc):
                SAVING[(doc.Name, view.Name)] = {}
                for name, plc in zip(view.FwBaseNames, view.FwBasePlacements):
                    obj = doc.getObject(name)
                    if obj is not None:
                        SAVING[(doc.Name, view.Name)][name] = App.Placement(obj.Placement)
                        if not obj.Placement.isSame(plc, 1e-9):
                            obj.Placement = plc
        except Exception as error:
            App.Console.PrintLog("FreeCAD: exploded view save: %s\n" % error)

    def slotFinishSaveDocument(self, doc, filename):
        for key in [k for k in SAVING if k[0] == doc.Name]:
            for name, plc in SAVING.pop(key).items():
                obj = doc.getObject(name)
                if obj is not None:
                    obj.Placement = plc
                    obj.purgeTouched()
        asm = ac.assembly_of(doc)
        if asm is not None:
            asm.purgeTouched()

SAVING = {}


def _redraw_lines(asm, view):
    """The explode lines were rebuilt with the components at their mated positions (the rebuild
    solves from there): drawn again to the exploded ones, or they shrank to nothing."""
    try:
        from . import asmexplines
        for o in asmexplines.sketches(asm, view):
            o.recompute()
    except Exception as _fw_err:
        _fw_log("asmexplode.py:lines after rebuild", _fw_err)


def _reopened(doc):
    """A file saved exploded opens exploded: the steps from the mated positions it keeps."""
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None:
        return
    try:
        for view in views(asm):
            if not is_exploded(view) or (doc.Name, view.Name) in EXPLODED:
                continue        # exploded in this session already (a new file saved, then exploded)
            comps = ac.components(asm) + nested_parts(asm)
            view.FwBaseNames = [c.Name for c in comps]
            view.FwBasePlacements = [c.Placement for c in comps]
            apply_steps(asm, view)
            for obj in [asm] + comps:
                obj.purgeTouched()
            _keep(asm, view, comps)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: exploded view on open: %s\n" % error)


def install():
    ""
    global _watcher
    if _watcher is None:
        _watcher = _Rebuild()
        App.addDocumentObserver(_watcher)
    from . import restorehook
    restorehook.on_restored(_reopened)


def _clear_lines(view):
    for step in view.Group:
        try:
            step.ViewObject.Proxy.redrawLines(step, [])
        except Exception as _fw_err:
            _fw_log("asmexplode.py:439", _fw_err)


def exploded_view(asm):
    """The view now exploded, else None."""
    for view in views(asm):
        if is_exploded(view):
            return view
    return None


# ----------------------------------------------------------------------------- the PropertyManager
class ExplodePanel:
    def __init__(self, asm, view=None):
        from . import asmpm
        self.asm = asm
        self.doc = asm.Document
        self.doc.openTransaction("Exploded View")
        self._made = view is None       # asmpkg359: a view this page made itself
        try:
            self.view = view or new_view(asm)
            _props(self.view)
            if is_exploded(self.view):
                collapse(asm, self.view)
            explode(asm, self.view)
            self.comps = []

            kind, lay = asmpm._box("Explode Step Type", "Explode", "ASSEMBLIES_EXPLODED_VIEW")
            self.regular = QtWidgets.QRadioButton(STEP_TYPES[0])
            self.radial = QtWidgets.QRadioButton(STEP_TYPES[1])
            self.regular.setObjectName("FW_ExplodeRegular")
            self.radial.setObjectName("FW_ExplodeRadial")
            self.regular.setChecked(True)
            lay.addWidget(self.regular)
            lay.addWidget(self.radial)
            self.radial.toggled.connect(self._kind_changed)
            self.editing_step = None

            st, lay = asmpm._box("Explode Steps")
            self.tree = QtWidgets.QTreeWidget()
            self.tree.setObjectName("FW_ExplodeSteps")
            self.tree.setHeaderHidden(True)
            self.tree.setFixedHeight(asmpm._rows(self.tree, 6))
            self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._step_menu)
            lay.addWidget(self.tree)

            se, lay = asmpm._box("Add a Step")
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("FW_ExplodeComponents")
            self.list.setProperty("swpickbox", True)
            self.list.setToolTip("Explode Step Components")
            self.list.setStyleSheet(asmpm.PICK_STYLE.replace("#cfe6fb", "#fbd6ec").replace("#3399ff", "#e0569f"))
            self.list.setFixedHeight(asmpm._rows(self.list, 3))
            lay.addWidget(self.list)
            from . import asmpattern
            asmpattern.mark_active(self.list)        # the box the picks go into at open (PM thread 11-27)
            row = QtWidgets.QHBoxLayout()
            self.axis = QtWidgets.QComboBox()
            self.axis.setObjectName("FW_ExplodeAxis")
            self.axis.setToolTip("Explode Direction")
            self.axis.addItems(["%s@%s" % (name, asm.Document.Label) for name, _ in AXES])
            self.axis.setCurrentIndex(2)
            self.reverse = QtWidgets.QToolButton()
            self.reverse.setObjectName("FW_ExplodeReverse")
            from . import pmvalues
            self.reverse.setIcon(pmvalues.reverse_icon())
            self.reverse.setToolTip("Reverse direction")
            self.reverse.setCheckable(True)
            row.addWidget(self.reverse)
            row.addWidget(self.axis, 1)
            lay.addLayout(row)
            self.distance = QtWidgets.QDoubleSpinBox()
            self.distance.setObjectName("FW_ExplodeDistance")
            self.distance.setRange(0.0, 1.0e6)
            self.distance.setDecimals(2)
            self.distance.setSuffix("mm")
            self.distance.setValue(50.0)
            self.distance.setToolTip("Explode Distance")
            lay.addWidget(self.distance)
            row = QtWidgets.QHBoxLayout()
            self.rot_reverse = QtWidgets.QToolButton()
            self.rot_reverse.setObjectName("FW_ExplodeRotateReverse")
            self.rot_reverse.setIcon(pmvalues.reverse_icon())
            self.rot_reverse.setToolTip("Reverse rotation")
            self.rot_reverse.setCheckable(True)
            self.rot_axis = QtWidgets.QComboBox()
            self.rot_axis.setObjectName("FW_ExplodeRotationAxis")
            self.rot_axis.setToolTip("Rotation axis")
            self.rot_axis.addItems(["%s@%s" % (name, asm.Document.Label) for name, _ in AXES])
            self.rot_axis.setCurrentIndex(2)
            row.addWidget(self.rot_reverse)
            row.addWidget(self.rot_axis, 1)
            self.rot_row = QtWidgets.QWidget()
            self.rot_row.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self.rot_row)
            self.angle = QtWidgets.QDoubleSpinBox()
            self.angle.setObjectName("FW_ExplodeAngle")
            self.angle.setRange(0.0, 360.0)
            self.angle.setDecimals(2)
            self.angle.setSuffix("deg")
            self.angle.setToolTip("Rotation angle")
            lay.addWidget(self.angle)
            self.origin = asmpm._check("Rotate about each component origin", ROT_ORIGIN_PARAM, True)
            self.origin.setObjectName("FW_ExplodeRotateOrigin")
            lay.addWidget(self.origin)

            self.bbox = asmpm._check("Explode from bounding box center", BBOX_PARAM, False)
            self.bbox.setObjectName("FW_ExplodeBBoxCenter")
            lay.addWidget(self.bbox)
            row = QtWidgets.QHBoxLayout()
            self.apply = QtWidgets.QPushButton("Add Step")
            self.apply.setObjectName("FW_ExplodeApply")
            self.apply.clicked.connect(self.add)
            self.done = QtWidgets.QPushButton("Reset")
            self.done.setToolTip("Clear the step's components and values")
            self.done.setObjectName("FW_ExplodeDone")
            self.done.clicked.connect(self._done)
            row.addWidget(self.apply)
            row.addWidget(self.done)
            row.addStretch(1)
            lay.addLayout(row)

            op, lay = asmpm._box("Options")
            self.autospace = asmpm._check("Auto-space components after drag", AUTOSPACE_PARAM, False)
            self.autospace.setObjectName("FW_ExplodeAutoSpace")
            lay.addWidget(self.autospace)
            self.spacing = QtWidgets.QSlider(Qt.Horizontal)
            self.spacing.setObjectName("FW_ExplodeSpacing")
            self.spacing.setToolTip("Adjust the spacing between components")
            self.spacing.setRange(0, 100)
            self.spacing.setValue(paths.params().GetInt(SPACING_PARAM, 100))
            self.spacing.valueChanged.connect(lambda v: paths.params().SetInt(SPACING_PARAM, int(v)))
            lay.addWidget(self.spacing)
            self.order_row = QtWidgets.QWidget()
            orow = QtWidgets.QHBoxLayout(self.order_row)
            orow.setContentsMargins(0, 0, 0, 0)
            self.order_buttons = {}
            group = QtWidgets.QButtonGroup(self.order_row)
            want = paths.params().GetString(ORDER_PARAM, "center")
            for key, tip in ORDERS:
                b = QtWidgets.QToolButton()
                b.setObjectName("FW_ExplodeOrder" + key.capitalize())
                b.setText({"center": "\u25a3", "back": "\u25e7", "front": "\u25e8"}[key])
                b.setToolTip(tip)
                b.setCheckable(True)
                b.setChecked(key == want)
                b.toggled.connect(lambda on, k=key: on and paths.params().SetString(ORDER_PARAM, k))
                group.addButton(b)
                orow.addWidget(b)
                self.order_buttons[key] = b
            orow.addStretch(1)
            self._order_group = group
            lay.addWidget(self.order_row)
            for w in (self.spacing, self.order_row):
                w.setVisible(self.autospace.isChecked())
                self.autospace.toggled.connect(w.setVisible)
            self._kind_changed()
            self.subparts = asmpm._check("Select the subassembly parts", SUBPARTS_PARAM, False)
            self.subparts.setObjectName("FW_ExplodeSubParts")
            self.subparts.setToolTip("Pick the parts inside a subassembly instead of the whole subassembly")
            lay.addWidget(self.subparts)
            self.rings = asmpm._check("Show rotation rings", RINGS_PARAM, True)
            self.rings.setObjectName("FW_ExplodeRings")
            self.rings.toggled.connect(self._rings)
            lay.addWidget(self.rings)
            self.reuse = QtWidgets.QPushButton("Reuse Subassembly Explode")
            self.reuse.setObjectName("FW_ExplodeReuseSub")
            self.reuse.setToolTip("Adds the explode steps of the picked subassembly")
            self.reuse.clicked.connect(self.reuse_sub)
            lay.addWidget(self.reuse, 0, Qt.AlignLeft)
            self.form = [kind, st, se, op]
            self._fill()
            self._handle_on()
            self._rings(self.rings.isChecked())
            QtCore.QTimer.singleShot(0, self._preselected)
            Gui.Selection.addObserver(self, 0)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    # ------------------------------------------------------------ picks
    def picked(self):
        ""

        out = []
        comps = ac.components(self.asm)
        subs_on = self.subparts.isChecked()
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames or [""]:
                names = [n for n in sub.split(".") if n] if sub else []
                if names and not sub.endswith("."):
                    names = names[:-1]          # the face / edge / vertex at the end
                doc = self.asm.Document
                path = ([sel.Object] if sel.Object is not self.asm else []) + \
                    [doc.getObject(n) for n in names if doc.getObject(n) is not None]
                if sel.Object in comps and not path:
                    path = [sel.Object]
                top = next((o for o in path if o in comps), None)
                if top is None:
                    continue
                pick = top
                if ac.is_subassembly(top) and subs_on:
                    inner = path[path.index(top) + 1] if path.index(top) + 1 < len(path) else None
                    if inner is not None and inner in ac.sub_components(top):
                        pick = inner
                if pick not in out:
                    out.append(pick)
        return out

    def _preselected(self):
        for comp in self.picked():
            self._add(comp)

    def addSelection(self, doc, obj, sub, pnt):
        from . import safe_later as _sl; _sl.later(0, lambda: [self._add(c) for c in self.picked()], self, "list")

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def _add(self, comp):
        if comp in self.comps:
            return
        self.comps.append(comp)
        self.list.addItem(display_name(comp))
        self._show_handle()

    # ------------------------------------------------------------ the drag handle
    def _handle_on(self):
        """FreeCAD's assembly dragger as the handle; parts don't free drag meanwhile."""
        self.dragger = None
        self.drag_from = None
        try:
            vo = self.asm.ViewObject
            self.movement = vo.EnableMovement
            vo.EnableMovement = False
            self.dragger = vo.getDragger()
            self.gview = Gui.ActiveDocument.ActiveView
            self.cb_move = self.gview.addDraggerCallback(self.dragger, "addMotionCallback", self._dragged)
            self.cb_done = self.gview.addDraggerCallback(self.dragger, "addFinishCallback", self._released)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: explode handle: %s\n" % error)
            self.dragger = None

    def _handle_off(self):
        if self.dragger is None:
            return
        vo = self.asm.ViewObject
        try:
            self.gview.removeDraggerCallback(self.dragger, "addMotionCallback", self.cb_move)
            self.gview.removeDraggerCallback(self.dragger, "addFinishCallback", self.cb_done)
        except Exception as _fw_err:
            _fw_log("asmexplode.py:681", _fw_err)
        vo.DraggerVisibility = False
        vo.EnableMovement = self.movement
        self.dragger = None

    def _show_handle(self):
        if self.dragger is None:
            return
        vo = self.asm.ViewObject
        if not self.comps:
            vo.DraggerVisibility = False
            return
        box = App.BoundBox()
        for comp in self.comps:
            b = gbox(comp)
            if b.isValid():
                box.add(b)
        centre = box.Center if box.isValid() else self.comps[0].Placement.Base
        self.handle_at = App.Placement(centre, App.Rotation())
        self.drag_from = None
        vo.DraggerPlacement = self.handle_at
        vo.DraggerVisibility = True

    def handle_delta(self):
        return self.asm.ViewObject.DraggerPlacement.Base - self.handle_at.Base

    def _dragged(self, *args):
        if not self.comps:
            return
        if self.drag_from is None:
            self.drag_from = [(gplacement(c), [(m, gplacement(m)) for m in movers(c)]) for c in self.comps]
        move = self.handle_delta()
        turn = self.handle_turn()
        for comp, (plc, parts) in zip(self.comps, self.drag_from):
            about = plc.Base if self.origin.isChecked() else self.handle_at.Base
            t = App.Placement(move, turn, about)
            for m, mp in parts:
                set_gplacement(m, t.multiply(mp))
        self.distance.blockSignals(True)
        self.distance.setValue(move.Length)
        self.distance.blockSignals(False)

    def _released(self, *args):
        """The drag ends: the step goes in along the dragged arrow."""
        if self.drag_from is None:
            return
        move = self.handle_delta()
        turn = self.handle_turn()
        for comp, (plc, parts) in zip(self.comps, self.drag_from):
            for m, mp in parts:
                set_gplacement(m, mp)
        self.drag_from = None
        turned = abs(turn.Angle) > 1e-4
        if move.Length < 1e-6 and not turned:
            return
        if move.Length >= 1e-6:
            axis = max(range(3), key=lambda i: abs(move[i]))
            self.axis.setCurrentIndex(axis)
            self.reverse.setChecked(move[axis] < 0)
            self.distance.setValue(abs(move[axis]))
        else:
            self.distance.setValue(0.0)
        if turned:
            import math
            ax = turn.Axis
            i = max(range(3), key=lambda k: abs(ax[k]))
            self.rot_axis.setCurrentIndex(i)
            self.rot_reverse.setChecked(ax[i] < 0)
            self.angle.setValue(math.degrees(turn.Angle))
        else:
            self.angle.setValue(0.0)
        from . import safe_later as _sl; _sl.later(0, self.add, self, "distance")

    def handle_turn(self):
        """The rings' turn since the handle was put on the components."""
        try:
            return self.asm.ViewObject.DraggerPlacement.Rotation.multiply(self.handle_at.Rotation.inverted())
        except Exception:
            return App.Rotation()

    def _rings(self, on):
        """Show rotation rings: the handle's rings come and go (a ring hidden is an empty node)."""
        d = getattr(self, "dragger", None)
        if d is None:
            return
        try:
            import pivy.coin as coin
            if not hasattr(self, "_ring_nodes"):
                self._ring_nodes = {f: d.getField(f).getValue() for f in ("xRotatorDragger", "yRotatorDragger", "zRotatorDragger")}
            for f, node in self._ring_nodes.items():
                d.getField(f).setValue(node if on else coin.SoSeparator())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: rotation rings: %s\n" % error)

    def rings_shown(self):
        d = getattr(self, "dragger", None)
        if d is None or not hasattr(self, "_ring_nodes"):
            return True
        import pivy.coin as coin
        empty = coin.SoSeparator.getClassTypeId()
        return all(d.getField(f).getValue() is not None and d.getField(f).getValue().getTypeId() != empty
                   for f in self._ring_nodes)

    # ------------------------------------------------------------ steps
    def direction(self):
        d = App.Vector(AXES[self.axis.currentIndex()][1])
        return d * -1 if self.reverse.isChecked() else d

    def rotation_axis(self):
        d = App.Vector(AXES[self.rot_axis.currentIndex()][1])
        return d * -1 if self.rot_reverse.isChecked() else d

    def _kind_changed(self, *args):
        radial = self.radial.isChecked()
        self.rot_row.setVisible(not radial)       # a radial step only moves out from the axis
        self.angle.setVisible(not radial)
        self.origin.setVisible(not radial)
        if hasattr(self, "bbox"):
            self.bbox.setVisible(radial)
        if hasattr(self, "autospace"):      # Auto-space spaces a regular step's components only
            self.autospace.setVisible(not radial)
            for w in (self.spacing, self.order_row):
                w.setVisible(not radial and self.autospace.isChecked())
        self.axis.setToolTip("Explode direction (the axis the components move out from)" if radial else "Explode Direction")

    def add(self):
        """Apply: the step goes on the list and the components move (an edited step is replaced)."""
        if not self.comps:
            return None
        collapse(self.asm, self.view)
        comps, dists = list(self.comps), None
        radial = self.radial.isChecked()
        if self.autospace.isChecked() and not radial:
            comps, dists = spaced(comps, self.direction(), self.distance.value(), self.spacing.value(), self.order())
        index = None
        if self.editing_step is not None:
            index = list(self.view.Group).index(self.editing_step) if self.editing_step in self.view.Group else None
            remove_step(self.asm, self.view, self.editing_step)
            self.editing_step = None
            self._step_button()
        step = add_step(self.asm, self.view, comps, self.direction(), self.distance.value(), radial=radial,
                        axis=self.rotation_axis(), angle=0.0 if radial else self.angle.value(),
                        origin=self.origin.isChecked(), distances=dists, index=index,
                        bbox=radial and self.bbox.isChecked())
        explode(self.asm, self.view)
        self._fill()
        self._done()
        return step

    def order(self):
        return next((k for k, b in self.order_buttons.items() if b.isChecked()), "center")

    def reuse_sub(self):
        """Reuse Subassembly Explode: the picked subassembly's own explode steps come in."""
        subs = [c for c in self.comps if ac.is_subassembly(c)]
        if not subs:
            QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Explode",
                                              "Select a subassembly that has an exploded view.")
            return []
        collapse(self.asm, self.view)
        added = []
        for sub in subs:
            added += reuse_subassembly(self.asm, self.view, sub)
        explode(self.asm, self.view)
        self._fill()
        self._done()
        return added

    # ------------------------------------------------------------ Explode Steps right-click
    def _step_at(self, item):
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            return None
        i = self.tree.indexOfTopLevelItem(item)
        group = steps(self.view)
        return group[i] if 0 <= i < len(group) else None

    def _step_menu(self, pos):
        step = self._step_at(self.tree.itemAt(pos))
        if step is None:
            return
        menu = QtWidgets.QMenu(self.tree)
        menu.setObjectName("FW_ExplodeStepMenu")
        menu.addAction("Edit Step", lambda: self.edit_step(step))
        menu.addAction("Delete Step", lambda: self.delete_step(step))
        self.step_menu = menu
        menu.popup(self.tree.viewport().mapToGlobal(pos))

    def edit_step(self, step):
        """Edit Step: its components and values back in Settings; Apply puts it back changed."""
        self._done()
        data = step_data(step) or {}
        self.editing_step = step
        self._step_button()
        mt = step.MovementTransform
        direction = App.Vector(*data["direction"]) if data.get("direction") else App.Vector(mt.Base)
        i = max(range(3), key=lambda k: abs(direction[k])) if direction.Length > 1e-12 else 2
        self.axis.setCurrentIndex(i)
        self.reverse.setChecked(direction[i] < 0)
        self.distance.setValue(data.get("distance", mt.Base.Length))
        (self.radial if data.get("radial", step.MoveType == "Radial") else self.regular).setChecked(True)
        ax = App.Vector(*data.get("axis", [0, 0, 1]))
        k = max(range(3), key=lambda n: abs(ax[n]))
        self.rot_axis.setCurrentIndex(k)
        self.rot_reverse.setChecked(ax[k] < 0)
        self.angle.setValue(data.get("angle", 0.0))
        self.origin.setChecked(data.get("origin", True))
        self.bbox.setChecked(bool(data.get("bbox", False)))
        self.autospace.setChecked(bool(data.get("distances")))
        for comp in step_components(self.asm, step):
            self._add(comp)

    def delete_step(self, step):
        collapse(self.asm, self.view)
        if step is self.editing_step:
            self.editing_step = None
            self._step_button()
        remove_step(self.asm, self.view, step)
        explode(self.asm, self.view)
        self._fill()

    def _step_button(self):
        ""
        try:
            self.apply.setText("Apply" if self.editing_step is not None else "Add Step")
        except Exception as _fw_err:
            _fw_log("asmexplode.py:900", _fw_err)

    def _done(self):
        self.editing_step = None
        self._step_button()
        self.comps = []
        self.list.clear()
        self._show_handle()
        Gui.Selection.clearSelection()

    def _fill(self):
        self.tree.clear()
        for step in steps(self.view):
            item = QtWidgets.QTreeWidgetItem([step.Label])
            for comp in step_components(self.asm, step):
                QtWidgets.QTreeWidgetItem(item, [comp.Label])
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)

    def _finish(self):
        Gui.Selection.removeObserver(self)
        self._handle_off()

    def accept(self):
        self._finish()
        if not steps(self.view) and getattr(self, "_made", False):
            # asmpkg359: OK with no step makes nothing, so it leaves no empty "Exploded View" in Undo either
            # (PM thread 11-27)
            collapse(self.asm, self.view)
            self.doc.abortTransaction()
            self.doc.recompute()
            Gui.Control.closeDialog()
            _refresh()
            return True
        if not steps(self.view):     # nothing exploded: no empty ExplView left behind
            collapse(self.asm, self.view)
            group = self.view.InList
            self.doc.removeObject(self.view.Name)
            for g in group:
                if g.TypeId == "Assembly::ViewGroup" and not g.Group:
                    self.doc.removeObject(g.Name)
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._finish()
        collapse(self.asm, self.view)
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmexplode.py:955", _fw_err)


# ----------------------------------------------------------------------------- commands
class ExplodedViewCommand:
    def GetResources(self):
        return {"MenuText": "Exploded View", "Pixmap": "Assembly_ExplodedView",
                "ToolTip": "Separates the components of the assembly into an exploded view."}

    def Activated(self):
        from . import asmpm
        asm = _assembly()
        if not asmpm.close_open():
            return
        from . import asmui
        asmui.activate(asm)

        # the PropertyManager), it does not start an empty second one
        panel = ExplodePanel(asm, exploded_view(asm))
        asmpm._track(panel)
        Gui.Control.showDialog(panel)

    def IsActive(self):
        asm = _assembly()
        if asm is None or not ac.components(asm):
            return False
        from . import asmui
        return asmui._free()


class ExplodeCollapseCommand:
    ""

    def GetResources(self):
        return {"MenuText": "Explode / Collapse", "Pixmap": "Assembly_ExplodedView",
                "ToolTip": "Collapses the exploded assembly, or explodes it again."}

    def Activated(self):
        asm = _assembly()
        doc = asm.Document
        view = exploded_view(asm)
        if view is not None:
            doc.openTransaction("Collapse")
            collapse(asm, view)
        else:
            doc.openTransaction("Explode")
            explode(asm, views(asm)[-1])
        doc.commitTransaction()
        _refresh()

    def IsActive(self):
        asm = _assembly()
        if asm is None or not views(asm):
            return False
        from . import asmui
        return asmui._free()


def view_of_step(obj):
    """The exploded view an Explode Step row belongs to, else None."""
    try:
        if obj is None or not hasattr(obj, "MovementTransform"):
            return None
        for parent in obj.InList:
            if obj in getattr(parent, "Group", []) and type(getattr(parent, "Proxy", None)).__name__ == "ExplodedView":
                return parent
    except Exception as _fw_err:
        _fw_log("asmexplode.py:1020", _fw_err)
    return None


def edit_step(step):
    ""

    view = view_of_step(step)
    if view is None or not edit_view(view):
        return False
    panel = Gui.Control.activeDialog() and _open_panel()
    if panel is None:
        return False
    panel.edit_step(step)
    return True


def _open_panel():
    from . import asmpm
    p = asmpm.OPEN
    return p if isinstance(p, ExplodePanel) else None


def delete_step(step):
    """Right-click an Explode Step > Delete Step: the step goes and the view shows the rest."""
    view = view_of_step(step)
    if view is None:
        return False
    panel = _open_panel()
    if panel is not None and panel.view is view:
        panel.delete_step(step)
        return True
    asm = view.Proxy.getAssembly(view) if hasattr(view.Proxy, "getAssembly") else _assembly()
    if asm is None:
        return False
    doc = asm.Document
    was = is_exploded(view)
    doc.openTransaction("Delete Step")
    try:
        collapse(asm, view)
        remove_step(asm, view, step)
        if was:
            explode(asm, view)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return True


def edit_view(view):
    """Double-click an exploded view: the Explode PropertyManager on it."""
    from . import asmpm, asmui
    asm = view.Proxy.getAssembly(view) if hasattr(view.Proxy, "getAssembly") else _assembly()
    if asm is None or not asmpm.close_open():
        return False
    asmui.activate(asm)
    panel = ExplodePanel(asm, view)
    asmpm._track(panel)
    Gui.Control.showDialog(panel)
    return True


def patch_view_provider():
    cv = _cv()
    cls = cv.ViewProviderExplodedView
    if getattr(cls, "_fw_explode", False):
        return

    def doubleClicked(self, vobj):
        return edit_view(vobj.Object)

    cls.doubleClicked = doubleClicked
    cls._fw_explode = True


COMMANDS = (("SWStyle_ExplodedView", ExplodedViewCommand),
            ("SWStyle_ExplodeCollapse", ExplodeCollapseCommand))
