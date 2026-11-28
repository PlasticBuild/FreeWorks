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

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import asmtools


import re as _fw_re
_ONE_PICK = _fw_re.compile(r"^(Edge|Face|Vertex)\d+@(.+)$")


def shown_pick(raw):
    ""

    m = _ONE_PICK.match(raw or "")
    if m is None:
        return raw or ""
    from . import asmpm
    return "%s<1>@%s" % (m.group(1), asmpm.instance_name(m.group(2)))


def show_pick(box, raw):
    """Only the box's text changes: the document's name, which the page saves and reads back, is kept
    on the box (pick_raw)."""
    box.setProperty("swRaw", raw or "")
    box.setText(shown_pick(raw))


def pick_raw(box):
    raw = box.property("swRaw")
    return raw if raw and box.text() == shown_pick(raw) else box.text()


def mark_active(box, on=True):
    """pmboxes' active-box mark (the box the next pick goes into; Enter and Esc work from the view while
    it is empty) on a box that keeps its own pick colours (PM thread 11-27)."""
    try:
        from . import pmboxes
        own = box.styleSheet()
        pmboxes.mark(box, on)
        if own and box.styleSheet() != own:
            box.setStyleSheet(own)
    except Exception as _fw_err:
        __import__("FreeCAD").Console.PrintLog("FreeCAD asmpattern.mark_active: %s\n" % _fw_err)

def click_box(panel, key, widget):
    ""


    panel.__dict__.setdefault("_fw_boxes", []).append(widget)

    class F(QtCore.QObject):
        def eventFilter(self, obj, ev):
            try:
                if isinstance(ev, QtCore.QEvent) and ev.type() == QtCore.QEvent.MouseButtonPress:
                    panel._user_box = key
                    for w in list(panel._fw_boxes):
                        mark_active(w, w is widget)
            except Exception as _fw_err:
                __import__("FreeCAD").Console.PrintLog("FreeCAD asmpattern.click_box: %s\n" % _fw_err)
            return False
    f = F(widget)
    widget.installEventFilter(f)
    if hasattr(widget, "viewport"):
        widget.viewport().installEventFilter(f)
    panel.__dict__.setdefault("_fw_filters", []).append(f)


def user_box(panel):
    return panel.__dict__.get("_user_box") if hasattr(panel, "__dict__") else None

V = App.Vector
PLANES = (("Front Plane", V(0, 0, 0), V(0, 0, 1)), ("Top Plane", V(0, 0, 0), V(0, 1, 0)),
          ("Right Plane", V(0, 0, 0), V(1, 0, 0)))


# ----------------------------------------------------------------------------- the geometry
def circular_pattern(asm, comps, point, axis, angle, count, equal=True):
    """Instances 2..count of each component round the axis (point, axis); angle is the total
    (equal spacing) or the angle between instances, in degrees. Returns the new components."""
    out = []
    step = angle / count if equal and abs(angle - 360.0) < 1e-9 else \
        (angle / (count - 1) if equal else angle)
    for comp in comps:
        target = comp.LinkedObject
        for i in range(1, count):
            turn = App.Placement(V(), App.Rotation(V(axis), step * i), V(point))
            placement = turn.multiply(comp.Placement)
            link = ac.insert(asm, target, placement)
            link.Placement = placement
            ac.fix(asm, link)
            out.append(link)
    asm.Document.recompute()
    return out


def circular_moves(point, direction, angle, count, equal, second, skipped):
    """[(label, turn)] for the circular instances after the seed, less the skipped ones."""
    skipped = set(skipped)
    out = []

    def add(axis, values, direction2=False):
        degrees, instances, spaced = values
        instances = int(instances)
        if instances <= 1:
            return
        step = degrees / instances if spaced and abs(degrees - 360.0) < 1e-9 else \
            (degrees / (instances - 1) if spaced else degrees)
        for i in range(1, instances):
            label = "(%d,2)" % (i + 1) if direction2 else "(%d)" % (i + 1)
            if label not in skipped:
                out.append((label, App.Placement(V(), App.Rotation(V(axis), step * i), V(point))))

    add(direction, (angle, count, equal))
    if second is not None:
        add(direction * -1, second, True)
    return out


FLIPS = ((1, 1, -1), (1, -1, 1), (-1, 1, 1), (-1, -1, -1))


def _reflection(n):
    m = App.Matrix()
    m.A11, m.A12, m.A13 = 1 - 2 * n.x * n.x, -2 * n.x * n.y, -2 * n.x * n.z
    m.A21, m.A22, m.A23 = -2 * n.y * n.x, 1 - 2 * n.y * n.y, -2 * n.y * n.z
    m.A31, m.A32, m.A33 = -2 * n.z * n.x, -2 * n.z * n.y, 1 - 2 * n.z * n.z
    return m


def plane_reflection(point, normal):
    """The 4x4 reflection in the plane (point, normal)."""
    n = V(normal).normalize()
    m = _reflection(n)
    t = n * (2 * V(point).dot(n))
    m.A14, m.A24, m.A34 = t.x, t.y, t.z
    return m


def hand_key(seed_placement, hand_placement, point, normal):
    """What an opposite hand copy keeps against its seed: K with copy = reflection * seed * K."""
    r = plane_reflection(point, normal)
    k = seed_placement.toMatrix().inverse().multiply(r).multiply(hand_placement.toMatrix())
    return list(k.A)


def hand_placement(seed_placement, point, normal, key):
    """The opposite hand copy's placement for the seed's placement now: the mirror image of the
    seed stays the mirror image (two reflections make a turn)."""
    k = App.Matrix(*key)
    m = plane_reflection(point, normal).multiply(seed_placement.toMatrix()).multiply(k)
    return App.Placement(m)


MIRROR_TYPES = ("Center of mass", "Bounding box center", "Component origin")


def mirrored_placement(placement, point, normal, flip=FLIPS[0], ref=None):
    ""



    n = V(normal).normalize()
    base = V(placement.Base)
    d = (base - point).dot(n)
    new_base = base - n * (2 * d)
    f = App.Matrix()
    f.A11, f.A22, f.A33 = flip
    turned = _reflection(n).multiply(placement.Rotation.toMatrix()).multiply(f)
    out = App.Placement(new_base, App.Rotation(turned))
    if ref is not None:
        world = placement.multVec(V(ref))
        want = world - n * (2 * (world - V(point)).dot(n))
        out.Base = out.Base + (want - out.multVec(V(ref)))
    return out


def mirror_ref(comp, mirror_type):
    """The component's own point Mirror type names (None for Component origin)."""
    if mirror_type not in MIRROR_TYPES[:2]:
        return None
    try:
        shape = comp.LinkedObject.Shape
        if mirror_type == MIRROR_TYPES[0] and shape.Solids:
            c = shape.Solids[0].CenterOfMass if len(shape.Solids) == 1 else \
                sum((x.CenterOfMass * x.Volume for x in shape.Solids), V()) * (1.0 / sum(x.Volume for x in shape.Solids))
        else:
            c = shape.BoundBox.Center
        # the shape as the component shows it: the part's own placement is the component's
        own = App.Placement(getattr(comp.LinkedObject, "Placement", App.Placement()))
        return list(own.inverse().multVec(c))
    except Exception as _fw_err:
        _fw_log("asmpattern.py:158", _fw_err)
        return None


def _points(shape, most=300):
    pts = [v.Point for v in shape.Vertexes]
    for e in shape.Edges[:most]:
        try:
            pts.append(e.valueAt(0.5 * (e.FirstParameter + e.LastParameter)))
        except Exception as _fw_err:
            _fw_log("asmpattern.py:166", _fw_err)
    return pts[:most]


def best_flip(comp, point, normal):
    ""

    try:
        local = comp.LinkedObject.Shape
        mirror = local.transformed(comp.Placement.toMatrix()).mirror(V(point), V(normal))
        target = _points(mirror)
    except Exception:
        return FLIPS[0]
    if not target:
        return FLIPS[0]
    best, score = FLIPS[0], None
    for flip in FLIPS:
        placed = local.transformed(mirrored_placement(comp.Placement, point, normal, flip).toMatrix())
        got = _points(placed)
        s = sum(min((p - q).Length for q in target) for p in got) / max(1, len(got))
        if score is None or s < score - 1e-9:
            best, score = flip, s
    return best


def opposite_hand(asm, comp, point, normal, name=None):
    ""


    target = comp.LinkedObject
    own = App.Placement(getattr(target, "Placement", App.Placement()))
    local = comp.Placement.inverse()                 # the plane in the component's own frame
    lp, ln = local.multVec(V(point)), local.Rotation.multVec(V(normal))
    doc = target.Document
    m = doc.addObject("Part::Mirroring", "%s_Mirror" % target.Name)
    m.Source = target
    m.Base = own.multVec(lp)                         # ... and in the part document's frame
    m.Normal = own.Rotation.multVec(ln)
    m.Label = name or "%s (opposite hand)" % target.Label
    doc.recompute()
    if App.GuiUp and m.ViewObject is not None and doc is asm.Document:
        m.ViewObject.Visibility = False
        if target.ViewObject is not None:
            target.ViewObject.Visibility = False
    placement = comp.Placement.multiply(own.inverse()).multiply(App.Placement(m.Placement).inverse()) \
        if not m.Placement.isIdentity() else comp.Placement.multiply(own.inverse())
    link = ac.insert(asm, m, placement)
    link.Placement = placement
    ac.fix(asm, link)
    return link


TRANSFER = ("Solid bodies", "Surface bodies", "Axes", "Planes", "Cosmetic threads", "Custom properties",
            "Absorbed sketches", "Unabsorbed sketches", "Hole Wizard data", "Sheet metal information")
TRANSFER_ON = ("Solid bodies", "Surface bodies", "Axes", "Planes", "Cosmetic threads", "Custom properties",
               "Hole Wizard data", "Sheet metal information")
LAST_FILES = []


def _free_path(folder, name):
    """folder/name.FCStd, or name_2, name_3... so no file is ever overwritten."""
    import os
    base = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in name).strip() or "Mirror"
    path = os.path.join(folder, base + ".FCStd")
    i = 2
    while os.path.exists(path):
        path = os.path.join(folder, "%s_%d.FCStd" % (base, i))
        i += 1
    return path


def _transfer(src_doc, new_doc, base, normal, what):
    ""
    import Part
    made = []
    for o in src_doc.Objects:
        t = o.TypeId
        kind = None
        if t == "PartDesign::Plane":
            kind = "Planes"
        elif t in ("PartDesign::Line",):
            kind = "Axes"
        elif t == "Sketcher::SketchObject":
            used = any(getattr(x, "Profile", None) and x.Profile[0] == o for x in o.InList if hasattr(x, "Profile"))
            kind = "Absorbed sketches" if used else "Unabsorbed sketches"
        if kind is None or kind not in what:
            continue
        try:
            sh = o.Shape.copy()
            if sh.isNull():
                continue
            f = new_doc.addObject("Part::Feature", o.Name)
            f.Shape = sh.mirror(V(base), V(normal))
            f.Label = o.Label
            if f.ViewObject is not None:
                f.ViewObject.Visibility = False
            made.append(f)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: opposite hand: %s: %s\n" % (o.Label, error))
            from . import fwtell
            fwtell.tell("Not everything could be mirrored into the opposite-hand part.", error)
    meta = dict(new_doc.Meta or {})
    if "Custom properties" in what:
        from . import customprops
        for k, v in dict(src_doc.Meta or {}).items():
            if k.startswith(customprops.PREFIX):
                meta[k] = v
    keys = {"Cosmetic threads": ("Thread",), "Hole Wizard data": ("Hole",), "Sheet metal information": ("SheetMetal", "Bend", "KFactor")}
    for kind, words in keys.items():
        if kind not in what:
            continue
        rows = []
        for o in src_doc.Objects:
            for prop in o.PropertiesList:
                if any(w in prop for w in words) and o.getGroupOfProperty(prop) in ("FreeWorks", "FreeCAD", "SolidWorks", "Hole", "Thread"):
                    try:
                        rows.append("%s.%s=%s" % (o.Label, prop, getattr(o, prop)))
                    except Exception as _fw_err:
                        _fw_log("asmpattern.py:282", _fw_err)
        if rows:
            meta["FwOppositeHand:" + kind] = "\n".join(rows)[:20000]
    new_doc.Meta = meta
    return made


PREMADE = {}       # pkg300: opposite hand part documents made before the Mirror Components step opens


def _hand_title(asm, comp, name=None, folder=None):
    """The opposite hand file's part title, or None when it goes in the part's own document."""
    import os
    target = comp.LinkedObject
    folder = folder or (os.path.dirname(asm.Document.FileName) if asm.Document.FileName else "")
    if not (folder and os.path.isdir(folder)) or target.Document is asm.Document:
        return None
    return name or "%s (opposite hand)" % target.Label


def _hand_doc_name(title):
    return "".join(ch if ch.isalnum() else "_" for ch in title) or "Mirror"


def premake_hand_docs(asm, comps, names, hand):
    """Make the new opposite hand part documents before the step opens: a document made inside an
    Undo step takes a share of it (Ctrl+Z in the new part then emptied it)."""
    if not (hand and hand.get("files")):
        return
    for c in comps:
        title = _hand_title(asm, c, names.get(c), hand.get("folder"))
        if title and title not in PREMADE:
            d = App.newDocument(_hand_doc_name(title))
            d.UndoMode = 0
            PREMADE[title] = d.Name
    try:
        App.setActiveDocument(asm.Document.Name)
        if App.GuiUp:
            Gui.setActiveDocument(asm.Document.Name)
    except Exception as _fw_err:
        _fw_log("asmpattern.py:premake", _fw_err)


def drop_premade():
    """After the step: a pre-made document nothing used closes (an error stopped the mirror)."""
    for title, n in list(PREMADE.items()):
        PREMADE.pop(title, None)
        d = App.listDocuments().get(n)
        if d is not None and not d.Objects and not d.FileName:
            App.closeDocument(n)


def own_undo_after_step(new):
    """pkg300: the new part document gets its own Undo back once the open step is closed (while it
    is open, any change to the new part would take a share of the assembly's step)."""
    def back(name=new.Name):
        d = App.listDocuments().get(name)
        if d is not None:
            d.UndoMode = 1
    try:
        busy = App.getActiveTransaction()
    except Exception:
        busy = None
    if busy and App.GuiUp:
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, back)
    else:
        back()


def _new_hand_doc(title):
    n = PREMADE.pop(title, None)
    d = App.listDocuments().get(n) if n else None
    if d is None:
        d = App.newDocument(_hand_doc_name(title))
    return d


def opposite_hand_file(asm, comp, point, normal, name=None, folder=None, break_link=False,
                       transfer=TRANSFER_ON, visual=True):
    ""



    import os
    target = comp.LinkedObject
    folder = folder or (os.path.dirname(asm.Document.FileName) if asm.Document.FileName else "")
    if not (folder and os.path.isdir(folder)) or target.Document is asm.Document:
        # nowhere to save a new file (the assembly is not saved yet), or a part kept in the
        # assembly itself: the opposite hand goes in the part's own document
        return opposite_hand(asm, comp, point, normal, name)
    own = App.Placement(getattr(target, "Placement", App.Placement()))
    local = comp.Placement.inverse()
    lp, ln = local.multVec(V(point)), local.Rotation.multVec(V(normal))
    base, nrm = own.multVec(lp), own.Rotation.multVec(ln)
    title = name or "%s (opposite hand)" % target.Label
    new = _new_hand_doc(title)
    new.UndoMode = 0        # pkg300: the new part keeps no share of the Mirror Components step (Ctrl+Z there emptied it)
    new.Label = title
    own_undo_after_step(new)        # pkg300: its own Undo once the step is closed
    shape = target.Shape.copy().mirror(V(base), V(nrm))
    solids = "Solid bodies" in transfer
    surfaces = "Surface bodies" in transfer
    if not (solids and surfaces):
        import Part
        keep = list(shape.Solids) if solids else []
        if surfaces:
            inside = set()
            for x in shape.Solids:
                inside.update(f.hashCode() for f in x.Faces)
            keep += [f for f in shape.Faces if f.hashCode() not in inside]
        shape = Part.makeCompound(keep)
        break_link = True                       # a filtered copy cannot follow the original
    path = _free_path(folder, title)
    if path:
        try:
            new.saveAs(path)            # saved first: a link to the original needs a saved part
            LAST_FILES.append(path)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: opposite hand part not saved: %s\n" % error)
            path = None
    if not path or not target.Document.FileName:
        break_link = True               # no files to link between: the mirror image as it is now
    if break_link:
        m = new.addObject("Part::Feature", "OppositeHand")
        m.Shape = shape
    else:
        src = new.addObject("App::Link", "Original")
        src.setLink(target)
        src.Placement = own
        m = new.addObject("Part::Mirroring", "OppositeHand")
        m.Source = src
        m.Base = base
        m.Normal = nrm
        if App.GuiUp and src.ViewObject is not None:
            src.ViewObject.Visibility = False
    m.Label = title
    _transfer(target.Document, new, base, nrm, set(transfer))
    new.recompute()
    if visual and App.GuiUp and m.ViewObject is not None and target.ViewObject is not None:
        for prop in ("ShapeAppearance", "ShapeColor", "Transparency", "LineColor"):
            try:
                setattr(m.ViewObject, prop, getattr(target.ViewObject, prop))
            except Exception as _fw_err:
                _fw_log("asmpattern.py:353", _fw_err)
    if path:
        try:
            new.save()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: opposite hand part not saved: %s\n" % error)
    try:
        App.setActiveDocument(asm.Document.Name)
        if App.GuiUp:
            Gui.setActiveDocument(asm.Document.Name)
    except Exception as _fw_err:
        _fw_log("asmpattern.py:364", _fw_err)
    placement = comp.Placement.multiply(own.inverse()).multiply(App.Placement(m.Placement).inverse()) \
        if not m.Placement.isIdentity() else comp.Placement.multiply(own.inverse())
    link = ac.insert(asm, m, placement)
    link.Placement = placement
    ac.fix(asm, link)
    return link


def mirror_components(asm, comps, point, normal, opposite=(), flips=None, names=None, mirror_type=None,
                      hand=None):
    ""




    out = []
    for comp in comps:
        if comp in opposite:
            h = dict(hand or {})
            if h.pop("files", False):
                out.append(opposite_hand_file(asm, comp, point, normal, (names or {}).get(comp), **h))
            else:
                out.append(opposite_hand(asm, comp, point, normal, (names or {}).get(comp)))
            continue
        flip = (flips or {}).get(comp) or best_flip(comp, point, normal)
        placement = mirrored_placement(comp.Placement, point, normal, flip, mirror_ref(comp, mirror_type))
        link = ac.insert(asm, comp.LinkedObject, placement)
        link.Placement = placement
        ac.fix(asm, link)
        out.append(link)
    asm.Document.recompute()
    return out


def axis_of(shape):
    """(point, direction) of a round face, circular edge or straight edge; None otherwise."""
    g = ac.geometry(shape)
    if g is None:
        return None
    if g[0] in ("axis", "line"):
        return V(g[1]), V(g[2])
    return None


def plane_of(shape):
    g = ac.geometry(shape)
    if g is None or g[0] != "plane":
        return None
    return V(g[1]), V(g[2])


DATUM_PLANES = ("App::Plane", "PartDesign::Plane", "Part::DatumPlane")
DATUM_LINES = ("App::Line", "PartDesign::Line", "Part::DatumLine")


def datum(sel_obj, sub):
    """A plane or axis picked whole (the assembly's Front/Top/Right Plane or an axis from the tree,
    a reference plane): ("plane" | "axis", point, unit direction, label), else None. A plane's
    direction is its normal; an axis is FreeCAD's line along its X."""
    try:
        names = [n for n in (sub or "").split(".")]
        if sub and names[-1]:
            return None             # a face, edge or vertex: not a datum picked whole
        obj = sel_obj
        for n in [n for n in names if n]:
            obj = obj.Document.getObject(n) or obj
        if obj is None or obj.TypeId not in DATUM_PLANES + DATUM_LINES:
            return None
        plc = obj.getGlobalPlacement()
        plane = obj.TypeId in DATUM_PLANES
        d = plc.Rotation.multVec(V(0, 0, 1) if plane else V(1, 0, 0))
        d.normalize()
        return ("plane" if plane else "axis"), V(plc.Base), d, obj.Label
    except Exception as _fw_err:
        _fw_log("asmpattern.py:datum", _fw_err)
        return None


# ----------------------------------------------------------------------------- PropertyManagers
class _Panel:
    """Shared: the Components box and the pick routing (a component, or the axis or plane)."""

    def _components_box(self, title):
        from . import asmpm
        box, lay = asmpm._box(title)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_PatternComponents")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 3))
        lay.addWidget(self.list)
        mark_active(self.list)        # the box the picks go into at open
        click_box(self, "comps", self.list)

        box.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        return box

    def _add(self, comp):
        if comp in self.comps or getattr(comp, "TypeId", "") in ("App::Origin",) + tuple(DATUM_PLANES) + tuple(DATUM_LINES):
            return      # pkg310: the Origin or a plane/axis is never a component to pattern
        self.comps.append(comp)
        self.list.addItem(comp.Label)

    def _route(self):
        """A pick of the reference's kind (an axis, a plane) goes to the reference box while it is
        empty or active; anything else adds its component."""
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames:
                found = datum(sel.Object, sub)
                if found is not None:
                    # an origin plane or axis picked in the tree: a reference, never a component to
                    # pattern (pkg310: it went in as "Origin" before)
                    if hasattr(self, "take_datum"):
                        self.take_datum(found)
                    continue
                ref = ac.reference(self.asm, sel.Object, sub) if sub else None
                if ref is None:
                    continue
                shape = ac.element(*ref)
                if self.take_reference(ref, shape):
                    continue
                self._add(ref[0])
            if sel.Object in ac.components(self.asm):
                self._add(sel.Object)

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, self._route)

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def _done(self):
        Gui.Selection.removeObserver(self)
        Gui.Control.closeDialog()

    def reject(self):
        self._done()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class CircularPatternPanel(_Panel):
    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.axis = None            # (point, direction, label) of a picked axis
        box, lay = asmpm._box("Direction 1", "Circular Pattern", "ASSEMBLIES_CIRCULAR_PATTERN")
        row = QtWidgets.QHBoxLayout()

        self.axis_box = QtWidgets.QLineEdit("")
        self.axis_box.setObjectName("FW_PatternAxisPick")
        self.axis_box.setReadOnly(True)
        self.axis_box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        self.axis_box.setToolTip("Pattern Axis: pick a round face, a circular edge or a straight edge")
        self.reverse = asmpm.reverse_button("FW_PatternReverse")
        row.addWidget(self.reverse)
        row.addWidget(self.axis_box, 1)
        click_box(self, "axis", self.axis_box)
        lay.addLayout(row)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("FW_PatternAngle")
        self.angle.setRange(0.001, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self.angle.setValue(15.0)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("FW_PatternCount")
        self.count.setRange(2, 1000)
        self.count.setValue(2)
        self.equal = QtWidgets.QCheckBox("Equal spacing")
        self.equal.setObjectName("FW_PatternEqual")
        self.equal.setChecked(False)
        self.equal.toggled.connect(self._equal)
        form = QtWidgets.QFormLayout()
        form.addRow("Angle:", self.angle)
        form.addRow("Instances:", self.count)
        lay.addLayout(form)
        lay.addWidget(self.equal)

        box2, lay2 = asmpm._box("Direction 2")
        self.symmetric = QtWidgets.QCheckBox("Symmetric")
        self.symmetric.setObjectName("FW_PatternSymmetric")
        self.symmetric.setChecked(True)
        lay2.addWidget(self.symmetric)
        self.angle2 = QtWidgets.QDoubleSpinBox()
        self.angle2.setObjectName("FW_PatternAngle2")
        self.angle2.setRange(0.001, 360.0)
        self.angle2.setDecimals(2)
        self.angle2.setSuffix("deg")
        self.angle2.setValue(360.0)
        self.count2 = QtWidgets.QSpinBox()
        self.count2.setObjectName("FW_PatternCount2")
        self.count2.setRange(1, 1000)
        self.count2.setValue(1)
        self.equal2 = QtWidgets.QCheckBox("Equal spacing")
        self.equal2.setObjectName("FW_PatternEqual2")
        self.equal2.setChecked(True)
        form2 = QtWidgets.QFormLayout()
        form2.addRow("Angle:", self.angle2)
        form2.addRow("Instances:", self.count2)
        lay2.addLayout(form2)
        lay2.addWidget(self.equal2)
        self.symmetric.toggled.connect(self._symmetric)
        self._symmetric(True)
        seeds = self._components_box("Components to Pattern")
        from . import asmcpattern
        self.skip = asmcpattern.SkipBox(self.instance_labels, "Instances to Override", "Skipped instances")
        for w in (self.count, self.count2):
            w.valueChanged.connect(self.skip.refresh)
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [box, box2, seeds, self.skip.box]
        QtCore.QTimer.singleShot(0, lambda: asmcpattern._fold(box2))
        Gui.Selection.addObserver(self, 0)
        self.editing = None
        self.preview = None
        try:
            self.preview = asmcpattern.InstancePreview(asm)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: circular pattern preview: %s\n" % error)
        self._preview_due = False
        for w in (self.angle, self.count, self.angle2, self.count2):
            w.valueChanged.connect(self.update_preview)
        for w in (self.reverse, self.equal, self.equal2, self.symmetric):
            w.toggled.connect(self.update_preview)
        self.skip.list.itemChanged.connect(self.update_preview)
        self.update_preview()

    def update_preview(self, *args):
        """Shown once the values settle (one redraw for a run of changes)."""
        if self.preview is None:
            return
        try:
            if self._preview_due:
                return
            self._preview_due = True
            from . import safe_later as _sl; _sl.later(0, self.refresh_preview, self, "angle")
        except Exception as error:
            self._preview_due = False
            App.Console.PrintLog("FreeCAD: circular pattern preview: %s\n" % error)

    def refresh_preview(self):
        self._preview_due = False
        if self.preview is None or getattr(self, "_closed", False):
            return
        try:
            from . import asmcpattern
            if self.editing is not None and not self.preview.hidden:
                self.preview.hide_old(asmcpattern.instances(self.editing))
            if self.axis is None:
                self.preview.show(self.comps, [])
                return
            point, direction = self.pattern_axis()
            moves = circular_moves(point, direction, self.angle.value(), self.count.value(),
                                   self.equal.isChecked(), self._second(), self.skip.skipped())
            self.preview.show(self.comps, [move for _label, move in moves])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: circular pattern preview: %s\n" % error)

    def _end_preview(self, keep_old):
        self._closed = True
        if self.preview is None:
            return
        try:
            self.preview.clear()
            if not keep_old:
                self.preview.restore_old()
            else:
                self.preview.hidden = []
        except Exception as error:
            App.Console.PrintLog("FreeCAD: circular pattern preview: %s\n" % error)

    def _add(self, comp):
        super()._add(comp)
        if hasattr(self, "preview") and self.preview is not None:
            self.update_preview()

    def _symmetric(self, on):
        for w in (self.angle2, self.equal2):       # live: a change there turns Symmetric off
            if not hasattr(w, "_fw_take_over"):
                _takes_over(w, self.symmetric, False)

    def instance_labels(self):
        out = ["(%d)" % i for i in range(2, self.count.value() + 1)]
        n2 = self.count.value() if self.symmetric.isChecked() else self.count2.value()
        if self.count2.value() > 1:
            out += ["(%d,2)" % i for i in range(2, n2 + 1)]
        return out

    def _second(self):
        """Direction 2's (angle, count, equal): Symmetric copies Direction 1's."""
        if self.count2.value() <= 1:
            return None
        if self.symmetric.isChecked():
            return self.angle.value(), self.count.value(), self.equal.isChecked()
        return self.angle2.value(), self.count2.value(), self.equal2.isChecked()

    def values(self):
        point, direction = self.pattern_axis()
        return {"point": list(point), "axis": list(self.axis[1]) if self.axis else [0, 0, 1],
                "axis_point": list(self.axis[0]) if self.axis else [0, 0, 0],
                "axis_label": self.axis[2] if self.axis else "", "reverse": self.reverse.isChecked(),
                "angle": self.angle.value(), "count": self.count.value(), "equal": self.equal.isChecked(),
                "symmetric": self.symmetric.isChecked(), "angle2": self.angle2.value(),
                "count2": self.count2.value(), "equal2": self.equal2.isChecked()}

    def load(self, v):
        if v.get("axis_label"):
            try:
                from . import asmcpattern
                got, how = asmcpattern.substitute_axis(self.asm, v["axis_label"], v["axis_point"], v["axis"])
                if how != "ok":
                    App.Console.PrintMessage("FreeCAD: pattern axis %s: %s\n" % (
                        v["axis_label"], "replaced by " + got if got else "missing (the axis is kept)"))
                    v = dict(v, axis_label=got or v["axis_label"] + " (missing)")
            except Exception as error:
                App.Console.PrintLog("FreeCAD: pattern axis: %s\n" % error)
            self.axis = (V(*v["axis_point"]), V(*v["axis"]), v["axis_label"])
            show_pick(self.axis_box, v["axis_label"])
        self.reverse.setChecked(bool(v.get("reverse")))
        self.equal.blockSignals(True)
        self.equal.setChecked(v.get("equal", True))
        self.equal.blockSignals(False)
        self.angle.setValue(v.get("angle", 360.0))
        self.count.setValue(v.get("count", 4))
        self.symmetric.setChecked(v.get("symmetric", True))
        self.angle2.setValue(v.get("angle2", 360.0))
        self.count2.setValue(v.get("count2", 1))
        self.equal2.setChecked(v.get("equal2", True))
        self.skip.refresh()
        self.skip.set(v.get("skip", []))

    def _equal(self, on):
        ""
        self.angle.setValue(360.0 if on else 360.0 / max(2, self.count.value()))

    def take_reference(self, ref, shape):
        found = axis_of(shape)
        if found is None:
            return False
        user = user_box(self)
        if user == "comps":
            return False        # asmpkg364: Components to Pattern clicked: the pick adds its component
        if user != "axis" and self.comps and ref[0] in self.comps and self.axis is not None:
            return False
        self.axis = (found[0], found[1], "%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
        show_pick(self.axis_box, self.axis[2])
        self.update_preview()
        return True

    def take_datum(self, found):
        ""

        kind, point, direction, label = found
        if kind != "axis":
            return
        self.axis = (V(point), V(direction), label)
        show_pick(self.axis_box, label)
        self.update_preview()

    def pattern_axis(self):
        point, direction = (self.axis[0], self.axis[1]) if self.axis else (V(), V(0, 0, 1))
        return point, (direction * -1 if self.reverse.isChecked() else direction)

    def _need_axis(self):
        Gui.getMainWindow().statusBar().showMessage("Select an edge or axis for the direction reference.", 6000)
        self._user_box = "axis"
        for w in list(self.__dict__.get("_fw_boxes", [])):
            mark_active(w, w is self.axis_box)
        self.axis_box.setFocus()

    def accept(self):
        if self.comps and self.axis is None:
            self._need_axis()
            return False
        Gui.Selection.removeObserver(self)
        self._end_preview(keep_old=False)
        if self.comps:
            doc = self.asm.Document
            doc.openTransaction("Circular Component Pattern")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                point, direction = self.pattern_axis()
                second = self._second()

                def make(seed):
                    out = asmcpattern.numbered(circular_pattern(self.asm, [seed], point, direction, self.angle.value(),
                                                                self.count.value(), self.equal.isChecked()))
                    if second is not None:
                        made = circular_pattern(self.asm, [seed], point, direction * -1, *second)
                        out += [("(%d,2)" % (i + 2), l) for i, l in enumerate(made)]
                    return out
                asmcpattern.build(self.asm, "circular", self.comps, make, self.values(), self.skip.skipped(), label)
            finally:
                doc.commitTransaction()
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._end_preview(False)
        return super().reject()


class MirrorPanel(_Panel):
    ""











    STEPS = ("Step 1: Selections", "Step 2: Set Orientation", "Step 3: Opposite-Hand Version", "Step 4: Import Features")

    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.plane = None
        self.step = 0
        # the steps' header (the PropertyManager's title box)
        head, hlay = asmpm._box("Mirror Components", "Mirror Components", "ASSEMBLIES_MIRROR_COMPONENTS")
        self.step_label = QtWidgets.QLabel(self.STEPS[0])
        self.step_label.setObjectName("FW_MirrorStep")
        hlay.addWidget(self.step_label)
        nav = QtWidgets.QHBoxLayout()
        self.back = QtWidgets.QToolButton()
        self.back.setObjectName("FW_MirrorBack")
        self.back.setArrowType(QtCore.Qt.LeftArrow)
        self.back.setToolTip("Back")
        self.next = QtWidgets.QToolButton()
        self.next.setObjectName("FW_MirrorNext")
        self.next.setArrowType(QtCore.Qt.RightArrow)
        self.next.setToolTip("Next")
        nav.addStretch(1)
        self.back.clicked.connect(lambda: self.go(self.step - 1))
        self.next.clicked.connect(lambda: self.go(self.step + 1))
        nav.addWidget(self.back)
        nav.addWidget(self.next)
        hlay.addLayout(nav)
        # Step 1
        box, lay = asmpm._box("Selections")
        lay.addWidget(QtWidgets.QLabel("Mirror plane:"))

        self.plane_box = QtWidgets.QLineEdit("")
        self.plane_box.setObjectName("FW_MirrorPlane")
        self.plane_box.setReadOnly(True)
        self.plane_box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        self.plane_box.setToolTip("A plane or a flat face: pick one in the graphics area or the tree")
        lay.addWidget(self.plane_box)
        lay.addWidget(QtWidgets.QLabel("Components to Mirror:"))
        self.sel_list = QtWidgets.QListWidget()
        self.sel_list.setObjectName("FW_MirrorComponents")
        self.sel_list.setStyleSheet(asmpm.PICK_STYLE)
        self.sel_list.setFixedHeight(asmpm._rows(self.sel_list, 4))
        self.sel_list.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        drop = QtGui.QAction("Delete", self.sel_list)
        drop.triggered.connect(self._drop_current)
        self.sel_list.addAction(drop)
        lay.addWidget(self.sel_list)
        click_box(self, "plane", self.plane_box)
        click_box(self, "comps", self.sel_list)
        # Step 2
        seeds = self._components_box("Orient Components")
        self.list.setToolTip("A checked component gets an opposite hand version; pick one to set its orientation")
        self.opposite = QtWidgets.QCheckBox("Create opposite hand version")
        self.opposite.setObjectName("FW_MirrorOpposite")
        self.opposite.setToolTip("A new part, the mirror image of the part (for a part that is not "
                                 "symmetric: a left hand from a right hand)")
        self.opposite.toggled.connect(self._opposite_all)
        seeds.layout().addWidget(self.opposite)
        orient, olay = asmpm._box("Orientation")
        olay.addWidget(QtWidgets.QLabel("Orientation of the component picked above:"))
        self.flips = {}
        self.orient = QtWidgets.QButtonGroup(orient)
        row = QtWidgets.QHBoxLayout()
        for i, f in enumerate(FLIPS):
            b = QtWidgets.QRadioButton("%d" % (i + 1))
            b.setObjectName("FW_MirrorOrient%d" % (i + 1))
            b.setToolTip("Mirror copy orientation %d (axes %s)" % (i + 1, " ".join("+" if x > 0 else "-" for x in f)))
            self.orient.addButton(b, i)
            row.addWidget(b)
        olay.addLayout(row)
        self.orient.buttonClicked.connect(self._orient_picked)
        self.list.currentRowChanged.connect(self._show_orient)
        olay.addWidget(QtWidgets.QLabel("Mirror type:"))
        self.mirror_type = QtWidgets.QButtonGroup(orient)
        for i, text in enumerate(MIRROR_TYPES):
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("FW_MirrorType%d" % (i + 1))
            self.mirror_type.addButton(b, i)
            olay.addWidget(b)
        self.mirror_type.button(0).setChecked(True)
        self.sync = QtWidgets.QCheckBox("Synchronize movement of flexible subassembly components")
        self.sync.setObjectName("FW_MirrorSync")
        self.sync.setChecked(True)
        olay.addWidget(self.sync)
        # Step 3
        files, flay = asmpm._box("Opposite-Hand Version")
        self.new_files = QtWidgets.QRadioButton("Create new files")
        self.new_files.setObjectName("FW_MirrorNewFiles")
        self.derived = QtWidgets.QRadioButton("Create new derived configuration")
        self.derived.setObjectName("FW_MirrorDerived")
        self.new_files.setChecked(True)
        flay.addWidget(self.new_files)
        flay.addWidget(self.derived)
        self.prefix_on = QtWidgets.QCheckBox("Add prefix:")
        self.prefix_on.setObjectName("FW_MirrorPrefixOn")
        from . import asmoptions
        pre, suf = asmoptions.mirror_affix()    # Options > Assemblies, Opposite hand mirror components
        self.prefix_on.setChecked(bool(pre))
        self.prefix = QtWidgets.QLineEdit(pre or "Mirror")
        self.prefix.setObjectName("FW_MirrorPrefix")
        self.suffix_on = QtWidgets.QCheckBox("Add suffix:")
        self.suffix_on.setObjectName("FW_MirrorSuffixOn")
        self.suffix_on.setChecked(bool(suf))
        self.suffix = QtWidgets.QLineEdit(suf)
        self.suffix.setObjectName("FW_MirrorSuffix")
        for a, b in ((self.prefix_on, self.prefix), (self.suffix_on, self.suffix)):
            r = QtWidgets.QHBoxLayout()
            r.addWidget(a)
            r.addWidget(b, 1)
            flay.addLayout(r)
            _takes_over(b, a, True)          # typing a prefix or suffix turns it on
        self.one_folder = QtWidgets.QCheckBox("Place files in one folder")
        self.one_folder.setObjectName("FW_MirrorOneFolder")
        frow = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit(os.path.dirname(asm.Document.FileName) if asm.Document.FileName else "")
        self.folder.setObjectName("FW_MirrorFolder")
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("FW_MirrorBrowse")
        self.browse.clicked.connect(self._browse)
        frow.addWidget(self.folder, 1)
        frow.addWidget(self.browse)
        flay.addWidget(self.one_folder)
        flay.addLayout(frow)
        self.one_folder.toggled.connect(self._files_shown)
        self.break_link = QtWidgets.QCheckBox("Break link to original part")
        self.break_link.setObjectName("FW_MirrorBreakLink")
        self.break_link.setToolTip("The new part keeps the mirror image as it is now; changes to the original no longer reach it")
        flay.addWidget(self.break_link)
        self.new_files.toggled.connect(self._files_shown)
        # Step 4
        imp, ilay = asmpm._box("Transfer")
        self.transfer = {}
        for name in TRANSFER:
            c = QtWidgets.QCheckBox(name)
            c.setObjectName("FW_MirrorTransfer_" + name.replace(" ", ""))
            c.setChecked(name in TRANSFER_ON)
            ilay.addWidget(c)
            self.transfer[name] = c
        prop, play = asmpm._box("Propagate from Original Part")
        self.visual = QtWidgets.QCheckBox("Propagate visual properties")
        self.visual.setObjectName("FW_MirrorVisual")
        self.visual.setChecked(True)
        play.addWidget(self.visual)
        self.files_box = files
        self.import_box = imp
        self.pages = [[box], [seeds, orient], [files], [imp, prop]]
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [head, box, seeds, orient, files, imp, prop]
        self._files_shown()

        mark_active(self.plane_box, self.plane is None)
        mark_active(self.sel_list, self.plane is not None)
        mark_active(self.list, False)
        from . import safe_later as _sl; _sl.later(0, lambda: self.go(0), self, "step_label")
        Gui.Selection.addObserver(self, 0)

    # --- steps
    def steps(self):
        """The steps this mirror has: 3 and 4 only with an opposite hand version made as a new file."""
        n = 2
        if self.opposite_set():
            n = 3 if self.derived.isChecked() else 4
        return n

    def _need_plane(self):
        Gui.getMainWindow().statusBar().showMessage("Select a plane or planar face for the Mirror plane.", 6000)
        self.plane_box.setFocus()

    def go(self, step):
        step = max(0, min(step, self.steps() - 1))
        if step > 0 and self.plane is None:
            self._need_plane()      # the next steps orient the copies about the plane
            step = 0
        self.step = step
        for i, page in enumerate(self.pages):
            for w in page:
                on = i == step
                w.setVisible(on)
                box = w.parentWidget()
                while box is not None and not box.inherits("Gui::TaskView::TaskBox"):
                    box = box.parentWidget()
                if box is not None:
                    box.setVisible(on)
        self.step_label.setText(self.STEPS[step])
        self.back.setVisible(step > 0)          # no step there: the arrow is not shown (no greyed control)
        self.next.setVisible(step < self.steps() - 1)
        mark_active(self.list, step == 1)      # Orient Components takes the picks in step 2
        if step == 1:
            self._show_orient()

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Place files in one folder", self.folder.text())
        if d:
            self.folder.setText(d)
            self.one_folder.setChecked(True)

    def _drop_current(self):
        i = self.sel_list.currentRow()
        if 0 <= i < len(self.comps):
            self.comps.pop(i)
            self.sel_list.takeItem(i)
            self.list.takeItem(i)

    def _add(self, comp):
        if comp in self.comps:
            return
        self.comps.append(comp)
        self.sel_list.addItem(comp.Label)
        it = QtWidgets.QListWidgetItem(comp.Label)
        it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
        it.setCheckState(QtCore.Qt.Checked if self.opposite.isChecked() else QtCore.Qt.Unchecked)
        self.list.addItem(it)
        self.list.setCurrentRow(self.list.count() - 1)
        if not getattr(self, "_watching", False):
            self.list.itemChanged.connect(self._files_shown)
            self._watching = True

    def _opposite_all(self, on):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
        self._files_shown()

    def opposite_set(self):
        return [c for i, c in enumerate(self.comps) if self.list.item(i).checkState() == QtCore.Qt.Checked]

    def _files_shown(self, *args):
        """Filenames matter only for opposite hand versions; the folder and Break link only for new files."""
        if getattr(self, "pages", None) and self.step >= self.steps():
            from . import safe_later as _sl; _sl.later(0, lambda: self.go(self.steps() - 1), self, "step_label")
        on = bool(self.opposite_set())
        files = self.new_files.isChecked()
        # the files step shows only with an opposite hand version (steps()); in it, what does not
        # apply is not shown (no greyed controls)
        for w in (self.one_folder, self.break_link, self.folder, self.browse):
            w.setVisible(on and files)
        for w in (self.folder, self.browse):
            if not hasattr(w, "_fw_take_over"):
                _takes_over(w, self.one_folder, True)       # a folder typed or browsed: one folder on
        try:
            self.next.setVisible(self.step < self.steps() - 1)
        except Exception as _fw_err:
            _fw_log("asmpattern.py:956", _fw_err)

    def _current(self):
        i = self.list.currentRow()
        return self.comps[i] if 0 <= i < len(self.comps) else None

    def _show_orient(self, *args):
        comp = self._current()
        if comp is None:
            return
        try:
            point, normal = self.mirror_plane()
            flip = self.flips.get(comp) or best_flip(comp, point, normal)
            self.orient.button(FLIPS.index(tuple(flip))).setChecked(True)
        except Exception as _fw_err:
            _fw_log("asmpattern.py:971", _fw_err)

    def _orient_picked(self, button):
        comp = self._current()
        if comp is not None:
            self.flips[comp] = FLIPS[self.orient.id(button)]

    def part_name(self, comp):
        base = comp.LinkedObject.Label
        pre = self.prefix.text() if self.prefix_on.isChecked() else ""
        suf = self.suffix.text() if self.suffix_on.isChecked() else ""
        return "%s%s%s" % (pre, base, suf) if (pre or suf) else None

    def mirror_type_name(self):
        return MIRROR_TYPES[max(0, self.mirror_type.checkedId())]

    def hand(self):
        """The Opposite-Hand Version options for mirror_components."""
        if self.derived.isChecked():
            return None
        return {"files": True, "break_link": self.break_link.isChecked(),
                "folder": self.folder.text() if self.one_folder.isChecked() and self.folder.text() else None,
                "transfer": tuple(n for n, c in self.transfer.items() if c.isChecked()),
                "visual": self.visual.isChecked()}

    def values(self):
        point, normal = self.mirror_plane() or (None, None)
        return {"plane": pick_raw(self.plane_box), "point": list(point) if point else None,
                "normal": list(normal) if normal else None,
                "opposite": [c.Name for c in self.opposite_set()],
                "flips": {c.Name: list(f) for c, f in self.flips.items()},
                "prefix": self.prefix.text() if self.prefix_on.isChecked() else None,
                "suffix": self.suffix.text() if self.suffix_on.isChecked() else None,
                "mirror_type": self.mirror_type_name(), "sync": self.sync.isChecked(),
                "derived": self.derived.isChecked(), "break_link": self.break_link.isChecked(),
                "folder": self.folder.text() if self.one_folder.isChecked() else None,
                "transfer": [n for n, c in self.transfer.items() if c.isChecked()],
                "visual": self.visual.isChecked()}

    def load(self, v):
        if v.get("point") and v.get("normal"):
            self.plane = (V(*v["point"]), V(*v["normal"]))
            show_pick(self.plane_box, v.get("plane") or "")
        names = set(v.get("opposite", []))
        for i, c in enumerate(self.comps):
            self.list.item(i).setCheckState(QtCore.Qt.Checked if c.Name in names else QtCore.Qt.Unchecked)
        self.flips = {c: tuple(v["flips"][c.Name]) for c in self.comps if c.Name in v.get("flips", {})}
        self.prefix_on.setChecked(v.get("prefix") is not None)
        self.prefix.setText(v.get("prefix") or "")
        self.suffix_on.setChecked(v.get("suffix") is not None)
        self.suffix.setText(v.get("suffix") or "")
        if v.get("mirror_type") in MIRROR_TYPES:
            self.mirror_type.button(MIRROR_TYPES.index(v["mirror_type"])).setChecked(True)
        elif "mirror_type" not in v:
            self.mirror_type.button(2).setChecked(True)     # made before Mirror type: Component origin
        self.sync.setChecked(v.get("sync", True))
        (self.derived if v.get("derived") else self.new_files).setChecked(True)
        self.break_link.setChecked(bool(v.get("break_link")))
        if v.get("folder"):
            self.one_folder.setChecked(True)
            self.folder.setText(v["folder"])
        if "transfer" in v:
            for n, c in self.transfer.items():
                c.setChecked(n in v["transfer"])
        self.visual.setChecked(v.get("visual", True))
        self._show_orient()
        self._files_shown()

    def take_reference(self, ref, shape):
        found = plane_of(shape)
        if found is None or (self.comps and ref[0] in self.comps) or self.step != 0:
            return False
        if user_box(self) == "comps":
            return False        # asmpkg364: Components to Mirror clicked: a flat face adds its component
        self.set_plane(found, "%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
        return True

    def take_datum(self, found):
        kind, point, normal, label = found
        if kind == "plane" and self.step == 0:
            self.set_plane((point, normal), label)

    def set_plane(self, plane, label):
        self.plane = plane
        show_pick(self.plane_box, label)
        mark_active(self.plane_box, False)
        mark_active(self.sel_list, True)
        self._user_box = "comps"                # asmpkg364: so the next flat face is a component, not the plane
        if hasattr(self, "preview_changed"):
            self.preview_changed()

    def mirror_plane(self):
        return self.plane

    def accept(self):
        if self.comps and self.plane is None:
            self._need_plane()
            return False
        Gui.Selection.removeObserver(self)
        if self.comps:
            doc = self.asm.Document
            opposite = self.opposite_set()
            premake_hand_docs(self.asm, [c for c in self.comps if c in opposite],
                              {c: self.part_name(c) for c in self.comps}, self.hand())     # pkg300
            doc.openTransaction("Mirror Components")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                point, normal = self.mirror_plane()
                opposite = self.opposite_set()
                mtype = self.mirror_type_name()
                hand = self.hand()

                def make(seed):
                    return [("(1)", l) for l in mirror_components(self.asm, [seed], point, normal,
                                                                  [seed] if seed in opposite else (), self.flips,
                                                                  {seed: self.part_name(seed)}, mtype, hand)]

                def spec(seed, link):
                    if seed in opposite:      # an opposite hand part: it stays the seed's mirror image
                        return {"point": list(point), "normal": list(normal),
                                "hand": hand_key(seed.Placement, link.Placement, point, normal)}
                    flip = self.flips.get(seed) or best_flip(seed, point, normal)
                    return {"point": list(point), "normal": list(normal), "flip": list(flip),
                            "ref": mirror_ref(seed, mtype)}
                asmcpattern.build(self.asm, "mirror", self.comps, make, self.values(), (), label, spec)
            finally:
                doc.commitTransaction()
                drop_premade()      # pkg300
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True


# ----------------------------------------------------------------------------- Sketch / Curve Driven
def centroid(comp):
    try:
        shape = comp.LinkedObject.Shape.transformed(comp.Placement.toMatrix())
        return V(shape.CenterOfMass) if hasattr(shape, "CenterOfMass") else V(shape.BoundBox.Center)
    except Exception:
        return V(comp.Placement.Base)


def sketch_points(shape):
    ""

    on_edges = [v.Point for e in shape.Edges for v in e.Vertexes]
    alone = [v.Point for v in shape.Vertexes if all((v.Point - q).Length > 1e-6 for q in on_edges)]
    pts = alone or [v.Point for v in shape.Vertexes]
    out = []
    for p in pts:
        if all((p - q).Length > 1e-6 for q in out):
            out.append(V(p))
    return out


def sketch_pattern(asm, comps, points, reference=None):
    """An instance of each component at each point: its centroid (or reference) moved there; a
    point where the seed already is gets none."""
    out = []
    for comp in comps:
        ref = V(reference) if reference is not None else centroid(comp)
        for p in points:
            move = p - ref
            if move.Length < 1e-6:
                continue
            placement = App.Placement(comp.Placement)
            placement.Base = placement.Base + move
            link = ac.insert(asm, comp.LinkedObject, placement)
            link.Placement = placement
            ac.fix(asm, link)
            out.append(link)
    asm.Document.recompute()
    return out


def curve_stations(edge, count, spacing=None, equal=True, reverse=False):
    """Parameters along edge for count instances (the seed's first): equal spacing over the whole
    curve (a closed curve shares it out), else spacing apart (mm along the curve)."""
    length = edge.Length
    closed = edge.isClosed() if hasattr(edge, "isClosed") else False
    step = (length / count if closed else length / max(1, count - 1)) if equal else float(spacing)
    first, last = edge.FirstParameter, edge.LastParameter
    out = []
    for i in range(count):
        d = step * i
        if d > length + 1e-6:
            break
        if reverse:
            out.append(edge.getParameterByLength(max(0.0, length - d)) if d > 0 else last)
        else:
            out.append(edge.getParameterByLength(min(d, length)) if d > 0 else first)
    return out


def _frame(t, n):
    """A rotation whose X is t and Z is n (made square to t)."""
    t = V(t).normalize()
    n = V(n) - t * V(n).dot(t)
    if n.Length < 1e-9:
        return App.Rotation(V(1, 0, 0), t)
    n.normalize()
    return App.Rotation(t, n.cross(t), n, "XZY")


def _normal_at(face, p):
    import Part
    try:
        u, v = face.Surface.parameter(p)
        n = V(face.normalAt(u, v))
        return n * -1 if face.Orientation == "Reversed" else n
    except Exception:
        return None


def curve_pattern(asm, comps, edge, count, spacing=None, equal=True, tangent=False, reverse=False,
                  offset=False, normal_face=None):
    ""





    out = []
    for comp in comps:
        for move in curve_moves(comp, edge, count, spacing, equal, tangent, reverse, offset, normal_face):
            placement = move.multiply(comp.Placement)
            link = ac.insert(asm, comp.LinkedObject, placement)
            link.Placement = placement
            ac.fix(asm, link)
            out.append(link)
    asm.Document.recompute()
    return out


def curve_moves(comp, edge, count, spacing=None, equal=True, tangent=False, reverse=False, offset=False,
                normal_face=None):
    """The move of each instance after the seed along the curve (instance = move x seed)."""
    stations = curve_stations(edge, count, spacing, equal, reverse)
    if not stations:
        return []
    p0 = edge.valueAt(stations[0])
    t0 = edge.tangentAt(stations[0])
    n0 = _normal_at(normal_face, p0) if normal_face is not None else None
    out = []
    if True:
        off = centroid(comp) - p0
        for u in stations[1:]:
            p = edge.valueAt(u)
            t = edge.tangentAt(u)
            if n0 is not None:
                n = _normal_at(normal_face, p) or n0
                turn = _frame(t, n).multiply(_frame(t0, n0).inverted())
            else:
                turn = App.Rotation(t0, t)
            if tangent:
                move = App.Placement(p - p0, App.Rotation()).multiply(App.Placement(V(), turn, p0))
            elif offset:
                move = App.Placement(p + turn.multVec(off) - (p0 + off), App.Rotation())
            else:
                move = App.Placement(p - p0, App.Rotation())
            out.append(move)
    return out


class _Path:
    """A wire walked by length: point and tangent s mm from its start (a closed one wraps)."""

    def __init__(self, wire):
        self.edges = list(wire.OrderedEdges) if hasattr(wire, "OrderedEdges") else list(wire.Edges)
        self.closed = wire.isClosed()
        self.lengths = [e.Length for e in self.edges]
        self.length = sum(self.lengths)
        # each edge's direction along the wire (an edge may run backwards in it)
        self.forward = []
        end = None
        for i, e in enumerate(self.edges):
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if end is None:
                nxt = self.edges[i + 1] if len(self.edges) > 1 else None
                fwd = nxt is None or min((b - v.Point).Length for v in nxt.Vertexes) <= \
                    min((a - v.Point).Length for v in nxt.Vertexes) + 1e-9
            else:
                fwd = (a - end).Length <= (b - end).Length
            self.forward.append(fwd)
            end = b if fwd else a

    def at(self, s):
        if self.closed:
            s = s % self.length
        s = max(0.0, min(self.length, s))
        for e, n, fwd in zip(self.edges, self.lengths, self.forward):
            if s <= n + 1e-9 or e is self.edges[-1]:
                d = min(s, n) if fwd else n - min(s, n)
                u = e.getParameterByLength(max(0.0, min(n, d)))
                t = e.tangentAt(u)
                return e.valueAt(u), (t if fwd else t * -1)
            s -= n
        e = self.edges[-1]
        return e.valueAt(e.LastParameter), e.tangentAt(e.LastParameter)

    def nearest(self, p):
        """Length along the path of its point nearest p."""
        import Part
        best, s0, walked = None, 0.0, 0.0
        for e, n, fwd in zip(self.edges, self.lengths, self.forward):
            d, pts, _info = e.distToShape(Part.Vertex(p))
            if best is None or d < best - 1e-9:
                u = e.Curve.parameter(pts[0][0])
                part = Part.Edge(e.Curve, e.FirstParameter, u).Length if u > e.FirstParameter + 1e-12 else 0.0
                best, s0 = d, walked + (part if fwd else n - part)
            walked += n
        return s0


def _chord_step(path, s, pitch, sign=1.0):
    """The length along the path (forwards, or backwards for sign -1) whose point is pitch
    (straight line) from the point at s."""
    p = path.at(s)[0]
    lo, hi = s, s + sign * pitch * 4.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if (path.at(mid)[0] - p).Length < pitch:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def chain_pattern(asm, comps, wire, spacing, count, fill=False, kind="Distance", links=None, plane=None,
                  flip=False, reverse=False, group2=(), linear=False):
    ""






    out = []
    for comp in comps:
        for src, move in chain_moves(comp, wire, spacing, count, fill, kind, links, plane, flip, reverse, group2, linear):
            placement = move.multiply(src.Placement)
            link = ac.insert(asm, src.LinkedObject, placement)
            link.Placement = placement
            ac.fix(asm, link)
            out.append(link)
    asm.Document.recompute()
    return out


def chain_moves(comp, wire, spacing, count, fill=False, kind="Distance", links=None, plane=None,
                flip=False, reverse=False, group2=(), linear=False):
    """[(source component, move)] of each chain link after the seed (link = move x source)."""
    path = _Path(wire)
    if path.length < 1e-9:
        return []
    sign = -1.0 if reverse else 1.0
    up = (V(plane) * (-1.0 if flip else 1.0)) if plane is not None else None
    out = []
    linkage = kind in ("Distance Linkage", "Connection Linkage")
    for comp in [comp]:
        pins = (links or {}).get(comp)
        if linkage and pins is not None:
            pitch = (V(pins[1]) - V(pins[0])).Length
            s0 = path.nearest(V(pins[0]))
        else:
            pitch = spacing
            s0 = path.nearest(centroid(comp))
        if pitch <= 1e-9:
            continue
        n = int(path.length / pitch + 1e-6) + (0 if path.closed else 1) if fill else count
        p0, t0 = path.at(s0)
        t0 = t0 * sign
        if linkage and pins is not None:
            t0 = (V(pins[1]) - V(pins[0])).normalize()
        r0 = _frame(t0, up) if up is not None else None
        s = s0
        seeds = [comp] + [g for g in group2] if kind == "Connection Linkage" and group2 else [comp]
        for i in range(1, n):
            if linkage and pins is not None:
                s = _chord_step(path, s, pitch, sign)      # asmpkg368: this link's first pin on the last one's second
                a = path.at(s)[0]
                s2 = _chord_step(path, s, pitch, sign)     # (it was on the seed's own first pin: a copy on the seed)
                if not path.closed and not (-1e-6 <= s2 <= path.length + 1e-6):
                    break                                   # its second pin is off the path: the link does not fit
                b = path.at(s2)[0]
                t = (b - a).normalize()
                p = a
            elif linear:
                s = _chord_step(path, s, spacing, sign)
                p, t = path.at(s)
                t = t * sign
            else:
                s = s0 + sign * spacing * i
                p, t = path.at(s)
                t = t * sign
            if not path.closed and not (-1e-6 <= s <= path.length + 1e-6):
                break
            turn = _frame(t, up).multiply(r0.inverted()) if up is not None else App.Rotation(t0, t)
            src = seeds[i % len(seeds)]
            base = p0 if src is comp else centroid(src) - (centroid(comp) - p0)    # asmpkg368: a Group 2 link sits on the path as the seed does
            move = App.Placement(p - base, App.Rotation()).multiply(App.Placement(V(), turn, base))
            out.append((src, move))
    return out


def _same_face(a, b, tol=1e-4):
    if a.Surface.TypeId != b.Surface.TypeId or abs(a.Area - b.Area) > tol * max(1.0, a.Area):
        return False
    ga, gb = ac.geometry(a), ac.geometry(b)
    if ga is None or gb is None or ga[0] != gb[0]:
        return False
    if ga[0] == "axis":
        return abs(ga[3] - gb[3]) < tol and abs(abs(V(ga[2]).normalize().dot(V(gb[2]).normalize())) - 1) < tol
    return True


def _circle_axis(points, direction, tol=1e-3):
    """(centre, axis) when the points lie on one circle square to direction, else None."""
    if len(points) < 3:
        return None
    d = V(direction).normalize()
    a, b, c = points[0], points[1], points[2]
    ab, ac_ = b - a, c - a
    n = ab.cross(ac_)
    if n.Length < 1e-9 or abs(abs(n.normalize().dot(d)) - 1) > 1e-3:
        return None
    # circumcentre of a, b, c
    den = 2 * (ab.cross(ac_)).Length ** 2
    centre = a + ((ab.cross(ac_)).cross(ab) * (ac_.Length ** 2) + ac_.cross(ab.cross(ac_)) * (ab.Length ** 2)) * (1.0 / den)
    r = (a - centre).Length
    if all(abs((p - centre).Length - r) < tol for p in points) and r > tol:
        return centre, d
    return None


def component_pattern_moves(comp):
    ""


    from . import asmcpattern
    try:
        seed = getattr(comp, asmcpattern.SEED_PROP, None) or comp
        for feat in [o for o in seed.Document.Objects if asmcpattern.is_pattern(o)]:
            if seed not in asmcpattern.seeds(feat):
                continue
            if getattr(feat, asmcpattern.KIND_PROP, "") == "mirror" or getattr(feat, "Suppressed", False):
                continue
            links = [l for l in asmcpattern.instances(feat) if getattr(l, asmcpattern.SEED_PROP, None) is seed
                     and not getattr(l, asmcpattern.MIRROR_PROP, "")]
            def order(l):
                try:
                    return int(str(getattr(l, asmcpattern.INDEX_PROP, "")).strip("()"))
                except ValueError:
                    return 0
            moves = [App.Placement(getattr(l, asmcpattern.MOVE_PROP)) for l in sorted(links, key=order)]
            if moves:
                return moves
    except Exception as _fw_err:
        _fw_log("asmpattern.py:component pattern moves", _fw_err)
    return []


def driving_instances(face_comp, face_name):
    ""


    moves = component_pattern_moves(face_comp)
    if moves:
        return moves
    seed = face_comp.getSubObject(face_name)
    if seed is None or seed.isNull() or seed.ShapeType != "Face":
        return []
    others = []
    for i in range(1, 100000):
        name = "Face%d" % i
        f = face_comp.getSubObject(name)
        if f is None or f.isNull() or f.ShapeType != "Face":
            break
        if name != face_name and _same_face(seed, f):
            others.append(f)
    if not others:
        return []
    c0 = V(seed.CenterOfMass)
    g = ac.geometry(seed)
    direction = V(g[2]) if g[0] in ("axis", "plane") else V(0, 0, 1)
    centres = [c0] + [V(f.CenterOfMass) for f in others]
    ring = _circle_axis(centres, direction)
    out = []
    for f in others:
        c = V(f.CenterOfMass)
        if ring is not None:
            centre, axis = ring
            u, w = (c0 - centre), (c - centre)
            u = u - axis * u.dot(axis)
            w = w - axis * w.dot(axis)
            ang = math.degrees(math.atan2(axis.dot(u.cross(w)), u.dot(w)))
            turn = App.Placement(V(), App.Rotation(axis, ang), centre)
            shift = (c - turn.multVec(c0))
            out.append(App.Placement(shift, App.Rotation()).multiply(turn))
        else:
            out.append(App.Placement(c - c0, App.Rotation()))
    return out


def pattern_driven(asm, comps, face_comp, face_name):
    out = []
    for move in driving_instances(face_comp, face_name):
        for comp in comps:
            placement = move.multiply(comp.Placement)
            link = ac.insert(asm, comp.LinkedObject, placement)
            link.Placement = placement
            ac.fix(asm, link)
            out.append(link)
    asm.Document.recompute()
    return out


def _picked_geometry(asm):
    """[(label, shape in the assembly, sketch or None, component or None)] for the current picks,
    sketches in the assembly or in its parts as well as components' faces and edges."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames:
            if not sub:
                continue
            try:
                shape = sel.Object.getSubObject(sub)
                path = sel.Object.getSubObjectList(sub)
            except Exception:
                continue
            if shape is None or getattr(shape, "isNull", lambda: True)():
                continue
            sketch = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
            ref = ac.reference(asm, sel.Object, sub)
            if ref is not None and ref[0] not in ac.components(asm):
                ref = None
            label = "%s@%s" % (sub.split(".")[-1], (sketch.Label if sketch is not None else
                                                    (ref[0].Label if ref else sel.Object.Label)))
            whole = None
            if sketch is not None:
                try:    # the whole sketch where it shows in the assembly
                    matrix = sel.Object.getSubObject(sub, 2)[1]
                    whole = sketch.Shape.copy()
                    whole.Placement = App.Placement(matrix)
                except Exception:
                    whole = None
            out.append((label, shape, sketch, whole, ref[0] if ref else None, [sel.DocumentName, sel.ObjectName, _plain_sub(sub)]))
    return out


def _plain_sub(sub):
    """sub without its mapped element name ("Sketch.;g1;SKT.Edge1" -> "Sketch.Edge1"), so it
    still names the edge after the sketch is edited."""
    import re
    return re.sub(r"\.?;[^.]*\.", ".", sub)


def driving_shape(src):
    """(shape, sketch, whole sketch) a driving pick's source [doc, object, sub] gives now, or None."""
    try:
        top = App.getDocument(src[0]).getObject(src[1])
        shape = top.getSubObject(src[2])
        path = top.getSubObjectList(src[2])
    except Exception:
        return None
    if shape is None or shape.isNull():
        return None
    sketch = next((o for o in reversed(path) if o.isDerivedFrom("Sketcher::SketchObject")), None)
    whole = None
    if sketch is not None:
        try:
            whole = sketch.Shape.copy()
            whole.Placement = App.Placement(top.getSubObject(src[2], 2)[1])
        except Exception:
            whole = None
    return shape, sketch, whole


def shape_stamp(shape):
    """A short signature of a shape's geometry, to tell when a driving sketch changed."""
    try:
        bb = shape.BoundBox
        return [round(x, 6) for x in (shape.Length, bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)] + \
            [len(shape.Vertexes)] + [round(c, 6) for v in shape.Vertexes[:2] for c in v.Point]
    except Exception:
        return []


class _DrivenPanel(_Panel):
    """Components to Pattern plus a driving pick (a sketch, a curve)."""

    def _route(self):
        for label, shape, sketch, whole, comp, src in _picked_geometry(self.asm):
            self._src = src
            if user_box(self) == "comps" and comp is not None and sketch is None:
                self._add(comp)     # asmpkg364: Components to Pattern clicked: a face or edge adds its component
                continue
            if self.take_driving(label, shape, sketch, whole, comp):
                continue
            if comp is not None:
                self._add(comp)
        for sel in Gui.Selection.getSelectionEx("", 0):
            if sel.Object in ac.components(self.asm) and not sel.SubElementNames:
                self._add(sel.Object)

    def _pick_box(self, name, text, tip):
        from . import asmpm
        box = QtWidgets.QLineEdit(text)
        box.setObjectName(name)
        box.setReadOnly(True)
        box.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
        box.setToolTip(tip)
        click_box(self, name, box)      # asmpkg367: clicked, it takes the next pick (not Components to Pattern)
        return box


class _TakeOver(QtCore.QObject):
    ""


    def __init__(self, widget, option, value):
        super().__init__(widget)
        self.option, self.value = option, value
        for w in [widget] + widget.findChildren(QtWidgets.QWidget):
            w.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QtCore.QEvent.FocusIn and event.reason() not in (
                QtCore.Qt.TabFocusReason, QtCore.Qt.BacktabFocusReason, QtCore.Qt.ShortcutFocusReason):
            return False    # focus the program moved (a PM opening, a list filling): not the user's choice
        if kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.KeyPress, QtCore.QEvent.Wheel,
                    QtCore.QEvent.FocusIn):
            try:
                if self.option.isChecked() != self.value:
                    self.option.setChecked(self.value)
            except RuntimeError:
                pass
        return False


def _takes_over(widget, option, value=True):
    widget._fw_take_over = _TakeOver(widget, option, value)
    return widget


def _task_box(widget):
    box = widget
    while box is not None and not box.inherits("Gui::TaskView::TaskBox"):
        box = box.parentWidget()
    return box or widget


class SketchPatternPanel(_DrivenPanel):
    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.points = []
        box, lay = asmpm._box("Selections", "Sketch Driven Pattern", "ASSEMBLIES_SKETCH_DRIVEN_PATTERN")
        lay.addWidget(QtWidgets.QLabel("Reference sketch:"))
        self.sketch_box = self._pick_box("FW_PatternSketch", "", "Pick a sketch: an instance goes on each of its points")
        lay.addWidget(self.sketch_box)
        lay.addWidget(QtWidgets.QLabel("Reference Point:"))
        self.centroid = QtWidgets.QRadioButton("Centroid")
        self.centroid.setObjectName("FW_PatternCentroid")
        self.centroid.setChecked(True)
        lay.addWidget(self.centroid)
        self.selected = QtWidgets.QRadioButton("Selected point")
        self.selected.setObjectName("FW_PatternSelectedPoint")
        lay.addWidget(self.selected)
        self.point_box = self._pick_box("FW_PatternRefPoint", "", "Pick a vertex of the seed: it goes on each sketch point")
        lay.addWidget(self.point_box)
        self.ref_point = None
        _takes_over(self.point_box, self.selected, True)    # clicking the box picks a point
        seeds = self._components_box("Components to Pattern")
        from . import asmcpattern
        self.skip = asmcpattern.SkipBox(self.instance_labels)
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [box, seeds, self.skip.box]
        Gui.Selection.addObserver(self, 0)

    def instance_labels(self):
        return ["(%d)" % (i + 2) for i in range(max(0, len(self.points) - 1))]

    def values(self):
        return {"points": [list(p) for p in self.points], "sketch": self.sketch_box.text(),
                "src": getattr(self, "src", None),
                "selected": self.selected.isChecked(), "ref_point": list(self.ref_point) if self.ref_point else None}

    def load(self, v):
        self.points = [V(*p) for p in v.get("points", [])]
        self.src = v.get("src")
        self.sketch_box.setText(v.get("sketch", ""))
        if v.get("selected") and v.get("ref_point"):
            self.selected.setChecked(True)
            self.ref_point = V(*v["ref_point"])
            self.point_box.setText("Point (%.2f, %.2f, %.2f)" % tuple(self.ref_point))
        self.skip.refresh()
        self.skip.set(v.get("skip", []))

    def take_driving(self, label, shape, sketch, whole, comp):
        if self.selected.isChecked() and shape.ShapeType == "Vertex" and comp is not None and comp in self.comps:
            self.ref_point = V(shape.Point)
            self.point_box.setText(label)
            return True
        if sketch is None:
            return False
        self.points = sketch_points(whole if whole is not None else shape)
        self.src = getattr(self, "_src", None)
        self.sketch_box.setText("%s (%d points)" % (sketch.Label, len(self.points)))
        self.skip.refresh()
        return True

    def accept(self):
        Gui.Selection.removeObserver(self)
        if self.comps and self.points:
            doc = self.asm.Document
            doc.openTransaction("Sketch Driven Component Pattern")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                ref = self.ref_point if self.selected.isChecked() else None
                values = self.values()
                values["refs"] = {c.Name: list(V(ref) if ref is not None else centroid(c)) for c in self.comps}
                asmcpattern.build(self.asm, "sketch", self.comps,
                                  lambda seed: asmcpattern.numbered(sketch_pattern(self.asm, [seed], self.points, ref)),
                                  values, self.skip.skipped(), label)
            finally:
                doc.commitTransaction()
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True


class CurvePatternPanel(_DrivenPanel):
    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.edge = None
        box, lay = asmpm._box("Direction 1", "Curve Driven Pattern", "ASSEMBLIES_CURVE_DRIVEN_PATTERN")
        row = QtWidgets.QHBoxLayout()
        self.curve_box = self._pick_box("FW_PatternCurve", "", "Pattern Direction: pick an edge or a sketch curve")
        self.reverse = asmpm.reverse_button("FW_PatternReverse")
        row.addWidget(self.reverse)
        row.addWidget(self.curve_box, 1)
        lay.addLayout(row)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("FW_PatternCount")
        self.count.setRange(2, 1000)
        self.count.setValue(4)
        self.spacing = QtWidgets.QDoubleSpinBox()
        self.spacing.setObjectName("FW_PatternSpacing")
        self.spacing.setRange(0.001, 1.0e6)
        self.spacing.setDecimals(2)
        self.spacing.setSuffix("mm")
        self.spacing.setValue(25.0)
        self.equal = QtWidgets.QCheckBox("Equal spacing")
        self.equal.setObjectName("FW_PatternEqual")
        self.equal.setChecked(True)
        _takes_over(self.spacing, self.equal, False)        # typing a spacing turns Equal spacing off
        form = QtWidgets.QFormLayout()
        form.addRow("Instances:", self.count)
        form.addRow("Spacing:", self.spacing)
        lay.addLayout(form)
        lay.addWidget(self.equal)
        lay.addWidget(QtWidgets.QLabel("Curve method:"))
        self.transform = QtWidgets.QRadioButton("Transform curve")
        self.transform.setObjectName("FW_PatternTransformCurve")
        self.offset = QtWidgets.QRadioButton("Offset curve")
        self.offset.setObjectName("FW_PatternOffsetCurve")
        self.transform.setChecked(True)
        group = QtWidgets.QButtonGroup(box)
        for w in (self.transform, self.offset):
            group.addButton(w)
            lay.addWidget(w)
        lay.addWidget(QtWidgets.QLabel("Alignment method:"))
        self.tangent = QtWidgets.QRadioButton("Tangent to curve")
        self.tangent.setObjectName("FW_PatternTangent")
        self.seed = QtWidgets.QRadioButton("Align to seed")
        self.seed.setObjectName("FW_PatternAlignSeed")
        self.tangent.setChecked(True)
        group2 = QtWidgets.QButtonGroup(box)
        for w in (self.tangent, self.seed):
            group2.addButton(w)
            lay.addWidget(w)
        self.face_normal = QtWidgets.QCheckBox("Face normal")
        self.face_normal.setObjectName("FW_PatternFaceNormal")
        self.face_normal.setToolTip("Face normal alignment for pattern direction: pick the face the 3D curve lies on")
        lay.addWidget(self.face_normal)
        self.normal_box = self._pick_box("FW_PatternNormalFace", "", "The face the curve lies on")
        self.normal_face = None
        _takes_over(self.normal_box, self.face_normal, True)
        lay.addWidget(self.normal_box)

        box2, lay2 = asmpm._box("Direction 2")
        self.edge2 = None
        self.active = 0
        row2 = QtWidgets.QHBoxLayout()
        self.curve_box2 = self._pick_box("FW_PatternCurve2", "", "Pattern Direction 2: pick an edge or a sketch curve")
        self.curve_box2.setPlaceholderText("Pattern Direction")
        self.reverse2 = asmpm.reverse_button("FW_PatternReverse2")
        row2.addWidget(self.reverse2)
        row2.addWidget(self.curve_box2, 1)
        lay2.addLayout(row2)
        self.count2 = QtWidgets.QSpinBox()
        self.count2.setObjectName("FW_PatternCount2")
        self.count2.setRange(1, 1000)
        self.count2.setValue(1)
        self.spacing2 = QtWidgets.QDoubleSpinBox()
        self.spacing2.setObjectName("FW_PatternSpacing2")
        self.spacing2.setRange(0.001, 1.0e6)
        self.spacing2.setDecimals(2)
        self.spacing2.setSuffix("mm")
        self.spacing2.setValue(25.0)
        self.equal2 = QtWidgets.QCheckBox("Equal spacing")
        self.equal2.setObjectName("FW_PatternEqual2")
        self.equal2.setChecked(True)
        _takes_over(self.spacing2, self.equal2, False)
        form2 = QtWidgets.QFormLayout()
        form2.addRow("Instances:", self.count2)
        form2.addRow("Spacing:", self.spacing2)
        lay2.addLayout(form2)
        lay2.addWidget(self.equal2)
        self.seed_only = QtWidgets.QCheckBox("Pattern seed only")
        self.seed_only.setObjectName("FW_PatternSeedOnly")
        lay2.addWidget(self.seed_only)
        panel = self

        class _Focus(QtCore.QObject):
            def __init__(self, which):
                super().__init__()
                self.which = which

            def eventFilter(self, obj, ev):
                if not isinstance(ev, QtCore.QEvent):
                    return False
                if ev.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                    panel.active = self.which
                return False
        self._focus = [_Focus(0), _Focus(1)]
        self.curve_box.installEventFilter(self._focus[0])
        self.curve_box2.installEventFilter(self._focus[1])
        seeds = self._components_box("Components to Pattern")
        from . import asmcpattern
        self.skip = asmcpattern.SkipBox(self.instance_labels)
        for w in (self.count, self.count2):
            w.valueChanged.connect(self.skip.refresh)
        self.seed_only.toggled.connect(lambda *_: self.skip.refresh())
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [box, box2, seeds, self.skip.box]
        QtCore.QTimer.singleShot(0, lambda: asmcpattern._fold(box2))
        Gui.Selection.addObserver(self, 0)

    def two(self):
        return self.edge2 is not None and self.count2.value() > 1

    def instance_labels(self):
        if not self.two():
            return ["(%d)" % i for i in range(2, self.count.value() + 1)]
        out = []
        for j in range(1, self.count2.value() + 1):
            for i in range(1, self.count.value() + 1):
                if (i, j) == (1, 1) or (self.seed_only.isChecked() and j > 1 and i > 1):
                    continue
                out.append("(%d,%d)" % (i, j))
        return out

    def generate(self, seed):
        """[(index, link)] for one seed: along Direction 1, then Direction 2 for the seed (and,
        without Pattern seed only, for every Direction 1 instance)."""
        from . import asmcpattern
        normal = self.normal_face if self.face_normal.isChecked() else None
        first = curve_pattern(self.asm, [seed], self.edge, self.count.value(), self.spacing.value(),
                              self.equal.isChecked(), self.tangent.isChecked(), self.reverse.isChecked(),
                              offset=self.offset.isChecked(), normal_face=normal)
        if not self.two():
            return asmcpattern.numbered(first)
        out = [("(%d,1)" % (i + 2), l) for i, l in enumerate(first)]
        second = curve_pattern(self.asm, [seed], self.edge2, self.count2.value(), self.spacing2.value(),
                               self.equal2.isChecked(), self.tangent.isChecked(), self.reverse2.isChecked(),
                               offset=self.offset.isChecked(), normal_face=normal)
        inv = seed.Placement.inverse()
        for j, l2 in enumerate(second):
            out.append(("(1,%d)" % (j + 2), l2))
            if self.seed_only.isChecked():
                continue
            move = l2.Placement.multiply(inv)
            for i, l1 in enumerate(first):
                pl = move.multiply(l1.Placement)
                link = ac.insert(self.asm, seed.LinkedObject, pl)
                link.Placement = pl
                ac.fix(self.asm, link)
                out.append(("(%d,%d)" % (i + 2, j + 2), link))
        self.asm.Document.recompute()
        return out

    def values(self):
        return {"edge": self.edge.exportBrepToString() if self.edge is not None else "", "label": self.curve_box.text(),
                "count": self.count.value(), "spacing": self.spacing.value(), "equal": self.equal.isChecked(),
                "tangent": self.tangent.isChecked(), "reverse": self.reverse.isChecked(),
                "offset": self.offset.isChecked(),
                "normal": self.normal_face.exportBrepToString() if self.face_normal.isChecked() and self.normal_face is not None else "",
                "edge2": self.edge2.exportBrepToString() if self.edge2 is not None else "", "label2": self.curve_box2.text(),
                "count2": self.count2.value(), "spacing2": self.spacing2.value(), "equal2": self.equal2.isChecked(),
                "reverse2": self.reverse2.isChecked(), "seed_only": self.seed_only.isChecked(),
                "src": getattr(self, "src1", None), "src2": getattr(self, "src2", None)}

    def load(self, v):
        import Part
        if v.get("edge"):
            sh = Part.Shape()
            sh.importBrepFromString(v["edge"])
            self.edge = sh.Edges[0] if sh.Edges else None
            self.curve_box.setText(v.get("label", ""))
        self.count.setValue(v.get("count", 4))
        self.spacing.setValue(v.get("spacing", 25.0))
        self.equal.setChecked(v.get("equal", True))
        (self.tangent if v.get("tangent", True) else self.seed).setChecked(True)
        (self.offset if v.get("offset") else self.transform).setChecked(True)
        self.reverse.setChecked(bool(v.get("reverse")))
        if v.get("normal"):
            sh = Part.Shape()
            sh.importBrepFromString(v["normal"])
            self.normal_face = sh.Faces[0] if sh.Faces else None
            self.face_normal.setChecked(self.normal_face is not None)
            self.normal_box.setText("Face")
        if v.get("edge2"):
            sh = Part.Shape()
            sh.importBrepFromString(v["edge2"])
            self.edge2 = sh.Edges[0] if sh.Edges else None
            self.curve_box2.setText(v.get("label2", ""))
        self.count2.setValue(v.get("count2", 1))
        self.spacing2.setValue(v.get("spacing2", 25.0))
        self.equal2.setChecked(v.get("equal2", True))
        self.reverse2.setChecked(bool(v.get("reverse2")))
        self.seed_only.setChecked(bool(v.get("seed_only")))
        self.src1, self.src2 = v.get("src"), v.get("src2")
        self.skip.refresh()
        self.skip.set(v.get("skip", []))

    def take_driving(self, label, shape, sketch, whole, comp):
        if self.face_normal.isChecked() and shape.ShapeType == "Face" and (comp is None or comp not in self.comps):
            self.normal_face = shape
            self.normal_box.setText(label)
            return True
        if shape.ShapeType != "Edge":
            return False
        if comp is not None and comp in self.comps and (self.edge is not None or self.active == 1):
            return False
        if self.active == 1:
            self.edge2 = shape
            self.src2 = getattr(self, "_src", None)
            self.curve_box2.setText(label)
            if self.count2.value() < 2:
                self.count2.setValue(2)
            self.skip.refresh()
            return True
        self.edge = shape
        self.src1 = getattr(self, "_src", None)
        self.curve_box.setText(label)
        return True

    def accept(self):
        Gui.Selection.removeObserver(self)
        if self.comps and self.edge is not None:
            doc = self.asm.Document
            doc.openTransaction("Curve Driven Component Pattern")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                values = self.values()
                values["stamp"] = [shape_stamp(self.edge), shape_stamp(self.edge2) if self.two() else []]
                asmcpattern.build(self.asm, "curve", self.comps, self.generate,
                                  values, self.skip.skipped(), label)
            finally:
                doc.commitTransaction()
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True


class ChainPatternPanel(_DrivenPanel):

    # Linkage), Options; Chain Group 1 holds the Spacing Method, the two unlabelled path link boxes and the Path
    # Alignment Plane; Options holds Synchronize configuration (no Synchronize movement row)
    NO_SYNC_MOVEMENT = True

    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.wire = None
        box, lay = asmpm._box("Pitch Method", "Chain Pattern", "ASSEMBLIES_CHAIN_PATTERN")
        self.kinds = {}
        kg = QtWidgets.QButtonGroup(box)
        for name in ("Distance", "Distance Linkage", "Connection Linkage"):
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("FW_Chain" + name.replace(" ", ""))
            kg.addButton(b)
            lay.addWidget(b)
            self.kinds[name] = b
            b.toggled.connect(lambda *_: self._kind_changed())
        self.kinds["Distance"].setChecked(True)
        pbox, play = asmpm._box("Chain Path")
        row = QtWidgets.QHBoxLayout()
        self.reverse = asmpm.reverse_button("FW_ChainReverse")
        row.addWidget(self.reverse)
        self.path_box = self._pick_box("FW_ChainPath", "", "Pick the path: a sketch (its chain of edges)")
        row.addWidget(self.path_box, 1)
        play.addLayout(row)
        self.fill = QtWidgets.QCheckBox("Fill Path")
        self.fill.setObjectName("FW_ChainFill")
        play.addWidget(self.fill)
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("FW_ChainCount")
        self.count.setRange(2, 10000)
        self.count.setValue(2)
        _takes_over(self.count, self.fill, False)            # typing a count turns Fill Path off
        cform = QtWidgets.QFormLayout()
        cform.addRow("Instances:", self.count)
        play.addLayout(cform)
        self.spacing = QtWidgets.QDoubleSpinBox()
        self.spacing.setObjectName("FW_ChainSpacing")
        self.spacing.setRange(0.001, 1.0e6)
        self.spacing.setDecimals(2)
        self.spacing.setSuffix("mm")
        self.spacing.setValue(50.0)
        self.align = None
        seeds = self._components_box("Chain Group 1")
        lay1 = seeds.layout()
        self.method_label = QtWidgets.QLabel("Spacing Method:")
        lay1.addWidget(self.method_label)
        self.along = QtWidgets.QRadioButton("Distance along path")
        self.along.setObjectName("FW_ChainAlongPath")
        self.linear = QtWidgets.QRadioButton("Linear distance")
        self.linear.setObjectName("FW_ChainLinearDistance")
        self.linear.setChecked(True)
        mg = QtWidgets.QButtonGroup(seeds)
        for b in (self.along, self.linear):
            mg.addButton(b)
            lay1.addWidget(b)
        form = QtWidgets.QFormLayout()
        self._chain_form = form
        form.addRow("Spacing:", self.spacing)
        lay1.addLayout(form)

        self.link_box = self._pick_box("FW_ChainLinks", "", "Path link 1: a round face or circular edge of the link's first pin")
        lay1.addWidget(self.link_box)
        self.link_box2 = self._pick_box("FW_ChainLinks2", "", "Path link 2: a round face or circular edge of the link's second pin")
        lay1.addWidget(self.link_box2)
        lay1.addWidget(QtWidgets.QLabel("Path Alignment Plane"))
        prow = QtWidgets.QHBoxLayout()
        self.flip = asmpm.reverse_button("FW_ChainFlip")
        self.flip.setToolTip("Flip alignment direction")
        prow.addWidget(self.flip)
        self.plane_box = self._pick_box("FW_ChainAlignPlane", "", "A plane or flat face: the links keep its normal as their up")
        prow.addWidget(self.plane_box, 1)
        lay1.addLayout(prow)
        self.pins = []
        self._slots = [None, None]
        group2, lay2g = asmpm._box("Chain Group 2")
        self.group2_list = QtWidgets.QListWidget()
        self.group2_list.setObjectName("FW_ChainGroup2")
        self.group2_list.setStyleSheet(asmpm.PICK_STYLE)
        self.group2_list.setFixedHeight(asmpm._rows(self.group2_list, 2))
        lay2g.addWidget(self.group2_list)
        click_box(self, "group2", self.group2_list)     # asmpkg368: clicked, a pick of any part of a component adds it
        self.group2 = []
        self.group2_box = group2
        opts, olay = asmpm._box("Options")
        self._options_lay = olay        # asmpkg371: the Options rows go in this one Options group
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [box, pbox, seeds, group2, opts]
        self._kind_changed()
        from . import safe_later as _sl; _sl.later(0, self._kind_changed, self, "group2_list")    # asmpkg371: again once the groups have title bars
        Gui.Selection.addObserver(self, 0)

    def kind(self):
        return next(n for n, b in self.kinds.items() if b.isChecked())

    def _kind_changed(self):
        if not hasattr(self, "group2_box"):
            return          # (the type buttons are made before the rest of the PM)
        k = self.kind()
        linkage = k != "Distance"
        for w in (self.spacing, self.method_label, self.along, self.linear):
            w.setVisible(not linkage)           # a linkage's links set the spacing: those rows are not shown
        label = self._chain_form.labelForField(self.spacing) if hasattr(self, "_chain_form") else None
        if label is not None:
            label.setVisible(not linkage)
        for w in (self.link_box, self.link_box2):
            w.setVisible(linkage)
        from . import asmpm
        try:
            asmpm.group_visible(self.group2_box, k == "Connection Linkage")
        except RuntimeError:                                                # Chain Group 2 for Connection Linkage only)
            pass

    def _set_pin(self, slot, point, label):
        ""
        self._slots[slot] = point
        box = (self.link_box, self.link_box2)[slot]
        show_pick(box, label)
        self.pins = [p for p in self._slots if p is not None]
        if len(self.pins) == 2:
            tip = "Pitch %.2fmm" % (self.pins[1] - self.pins[0]).Length
            for b in (self.link_box, self.link_box2):
                b.setToolTip(tip)
        if slot == 0 and self._slots[1] is None:
            self._user_box = "FW_ChainLinks2"
            for w in list(self.__dict__.get("_fw_boxes", [])):
                mark_active(w, w is self.link_box2)

    def values(self):
        return {"kind": self.kind(), "wire": self.wire.exportBrepToString() if self.wire is not None else "",
                "path": self.path_box.text(), "spacing": self.spacing.value(), "count": self.count.value(),
                "fill": self.fill.isChecked(), "reverse": self.reverse.isChecked(), "flip": self.flip.isChecked(),
                "spacing_method": "Linear distance" if self.linear.isChecked() else "Distance along path",
                "align": list(self.align) if self.align is not None else None, "align_label": pick_raw(self.plane_box),
                "pins": [list(p) for p in self.pins], "group2": [c.Name for c in self.group2],
                "pin_labels": [pick_raw(self.link_box), pick_raw(self.link_box2)],
                "src": getattr(self, "src", None), "stamp": shape_stamp(self.wire) if self.wire is not None else []}

    def load(self, v):
        import Part
        self.kinds[v.get("kind", "Distance")].setChecked(True)
        if v.get("wire"):
            sh = Part.Shape()
            sh.importBrepFromString(v["wire"])
            self.wire = sh.Wires[0] if sh.Wires else None
            self.path_box.setText(v.get("path", ""))
        self.src = v.get("src")
        self.spacing.setValue(v.get("spacing", 25.0))
        self.count.setValue(v.get("count", 4))
        self.fill.setChecked(bool(v.get("fill")))
        self.reverse.setChecked(bool(v.get("reverse")))
        self.flip.setChecked(bool(v.get("flip")))
        # a pattern made before the Spacing Method rows spaced its links along the path
        (self.linear if v.get("spacing_method") == "Linear distance" else self.along).setChecked(True)
        if v.get("align"):
            self.align = V(*v["align"])
            show_pick(self.plane_box, v.get("align_label", ""))
        pins = [V(*p) for p in v.get("pins", [])]
        labels = list(v.get("pin_labels") or []) + ["Path link 1", "Path link 2"][len(v.get("pin_labels") or []):]
        for i, p in enumerate(pins[:2]):
            self._set_pin(i, p, labels[i])
        doc = self.asm.Document
        for name in v.get("group2", []):
            c = doc.getObject(name)
            if c is not None and c not in self.group2:
                self.group2.append(c)
                self.group2_list.addItem(c.Label)

    def take_driving(self, label, shape, sketch, whole, comp):
        box = user_box(self)
        if box == "group2" and comp is not None and sketch is None:
            if comp not in self.comps and comp not in self.group2:
                self.group2.append(comp)
                self.group2_list.addItem(comp.Label)
            return True
        if box == "FW_ChainAlignPlane" and sketch is None and shape.ShapeType == "Face" and plane_of(shape) is not None:
            self.align = plane_of(shape)[1]
            show_pick(self.plane_box, label)
            return True
        if self.wire is not None and sketch is None and shape.ShapeType == "Face" and plane_of(shape) is not None \
                and (comp is None or comp not in self.comps):
            self.align = plane_of(shape)[1]
            show_pick(self.plane_box, label)
            return True
        if self.kind() != "Distance" and comp is not None and comp in self.comps:
            ax = axis_of(shape)
            if ax is not None and ac.geometry(shape)[0] == "axis":
                slot = 1 if box == "FW_ChainLinks2" else 0 if box == "FW_ChainLinks" else \
                    (0 if self._slots[0] is None else 1 if self._slots[1] is None else None)
                if slot is not None:
                    self._set_pin(slot, V(ax[0]), label)
                    return True
        if self.kind() == "Connection Linkage" and comp is not None and self.comps and comp not in self.comps \
                and self.wire is not None and comp not in self.group2 and shape.ShapeType != "Edge":
            self.group2.append(comp)
            self.group2_list.addItem(comp.Label)
            return True
        source = whole if sketch is not None and whole is not None else (shape if shape.ShapeType == "Edge" else None)
        if source is None:
            return False
        import Part
        wires = source.Wires if source.Wires else [Part.Wire(source.Edges)] if source.Edges else []
        if not wires:
            return False
        if sketch is None and comp is not None and comp in self.comps:
            return False
        edge = shape.Edges[0] if shape.Edges else None
        mid = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter)) if edge is not None else None
        on = [w for w in wires if mid is not None and w.distToShape(Part.Vertex(mid))[0] < 1e-6]
        self.wire = on[0] if on else max(wires, key=lambda w: w.Length)     # the chain the picked edge is in
        self.src = getattr(self, "_src", None)
        self.path_box.setText("%s (%.2fmm)" % ((sketch.Label if sketch is not None else label), self.wire.Length))
        return True

    def accept(self):
        Gui.Selection.removeObserver(self)
        if self.comps and self.wire is not None:
            doc = self.asm.Document
            doc.openTransaction("Chain Component Pattern")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                k = self.kind()
                links = {c: self.pins for c in self.comps} if k != "Distance" and len(self.pins) == 2 else None
                asmcpattern.build(self.asm, "chain", self.comps,
                                  lambda seed: asmcpattern.numbered(chain_pattern(
                                      self.asm, [seed], self.wire, self.spacing.value(), self.count.value(),
                                      self.fill.isChecked(), k, links, self.align, self.flip.isChecked(),
                                      self.reverse.isChecked(), self.group2, self.linear.isChecked())),
                                  self.values(), (), label)
            finally:
                doc.commitTransaction()
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True


class PatternDrivenPanel(_DrivenPanel):
    def __init__(self, asm, comps):
        from . import asmpm
        self.asm = asm
        self.driving = None
        box, lay = asmpm._box("Driving Feature or Component", "Pattern Driven", "ASSEMBLIES_PATTERN_DRIVEN_PATTERN")
        self.driving_box = self._pick_box("FW_PatternDriving", "",
                                          "Pick a face of the driving pattern's seed: a hole the seed sits in, or a component of a component pattern")
        lay.addWidget(self.driving_box)
        click_box(self, "driving", self.driving_box)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("FW_PatternDrivingCount")
        lay.addWidget(self.count_label)
        self.seed_pos = QtWidgets.QPushButton("Select Seed Position")
        self.seed_pos.setObjectName("FW_PatternSeedPosition")
        self.seed_pos.setCheckable(True)
        self.seed_pos.setToolTip("Pick the face of the driving pattern's instance the seed component sits at")
        self.seed_pos.toggled.connect(lambda on: on and Gui.getMainWindow().statusBar().showMessage(
            "Select the face of the instance the seed component sits at.", 8000))
        lay.addWidget(self.seed_pos, 0, QtCore.Qt.AlignLeft)
        seeds = self._components_box("Components to Pattern")
        from . import asmcpattern
        self.skip = asmcpattern.SkipBox(self.instance_labels)
        self.comps = []
        for comp in comps:
            self._add(comp)
        self.form = [seeds, box, self.skip.box]
        Gui.Selection.addObserver(self, 0)

    def instance_labels(self):
        if self.driving is None:
            return []
        return ["(%d)" % (i + 2) for i in range(len(driving_instances(*self.driving)))]

    def values(self):
        return {"comp": self.driving[0].Name if self.driving else "", "face": self.driving[1] if self.driving else "",
                "label": self.driving_box.text()}

    def load(self, v):
        c = self.asm.Document.getObject(v.get("comp", "")) if v.get("comp") else None
        if c is not None:
            self.driving = (c, v["face"])
            self.driving_box.setText(v.get("label", ""))
            self.count_label.setText("%d instances" % (len(driving_instances(c, v["face"])) + 1))
        self.skip.refresh()
        self.skip.set(v.get("skip", []))

    def take_driving(self, label, shape, sketch, whole, comp):
        if comp is None or shape.ShapeType != "Face" or comp in self.comps:
            return False
        ref_name = label.split("@")[0]
        if self.driving is not None and not self.seed_pos.isChecked() and comp is self.driving[0]:
            return True         # another face of the driving part: Select Seed Position picks it
        found = driving_instances(comp, ref_name)
        if not found:
            return False
        self.driving = (comp, ref_name)
        self.driving_box.setText(label)
        self.count_label.setText("%d instances" % (len(found) + 1))
        self.seed_pos.setChecked(False)
        self.skip.refresh()
        return True

    def accept(self):
        Gui.Selection.removeObserver(self)
        if self.comps and self.driving is not None:
            doc = self.asm.Document
            doc.openTransaction("Pattern Driven Component Pattern")
            try:
                from . import asmcpattern
                label = asmcpattern.replace_old(self)
                asmcpattern.build(self.asm, "driven", self.comps,
                                  lambda seed: asmcpattern.numbered(pattern_driven(self.asm, [seed], *self.driving)),
                                  self.values(), self.skip.skipped(), label)
            finally:
                doc.commitTransaction()
            asmtools._refresh()
        Gui.Control.closeDialog()
        return True


class _PanelCommand:
    PANEL = None
    RES = {}

    def GetResources(self):
        return dict(self.RES)

    def Activated(self):
        from . import asmpm
        asm = asmtools._assembly()
        if not asmpm.close_open():
            return
        panel = self.PANEL(asm, asmtools._picked_components(asm))
        if self.PANEL is not MirrorPanel:
            from . import asmcpattern
            asmcpattern.add_options(panel)     # Synchronize movement of flexible subassembly components
        asmpm._track(panel)
        Gui.Control.showDialog(panel)

    def IsActive(self):
        asm = asmtools._assembly()
        if asm is None or not ac.components(asm):
            return False
        from . import asmui
        return asmui._free()


class CircularComponentPatternCommand(_PanelCommand):
    PANEL = CircularPatternPanel
    RES = {"MenuText": "Circular Component Pattern", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Patterns components around an axis."}


class MirrorComponentsCommand(_PanelCommand):
    PANEL = MirrorPanel
    RES = {"MenuText": "Mirror Components", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Mirrors components about a plane or a flat face."}


class PatternDrivenComponentPatternCommand(_PanelCommand):
    PANEL = PatternDrivenPanel
    RES = {"MenuText": "Pattern Driven Component Pattern", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Patterns components after a pattern in a part (its holes, say)."}


class ChainComponentPatternCommand(_PanelCommand):
    PANEL = ChainPatternPanel
    RES = {"MenuText": "Chain Component Pattern", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Patterns components along a path, as the links of a chain."}


class SketchComponentPatternCommand(_PanelCommand):
    PANEL = SketchPatternPanel
    RES = {"MenuText": "Sketch Driven Component Pattern", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Patterns components at the points of a sketch."}


class CurveComponentPatternCommand(_PanelCommand):
    PANEL = CurvePatternPanel
    RES = {"MenuText": "Curve Driven Component Pattern", "Pixmap": "Assembly_InsertLink",
           "ToolTip": "Patterns components along a curve."}


COMMANDS = (("SWStyle_CircularComponentPattern", CircularComponentPatternCommand),
            ("SWStyle_PatternDrivenComponentPattern", PatternDrivenComponentPatternCommand),
            ("SWStyle_SketchComponentPattern", SketchComponentPatternCommand),
            ("SWStyle_CurveComponentPattern", CurveComponentPatternCommand),
            ("SWStyle_ChainComponentPattern", ChainComponentPatternCommand),
            ("SWStyle_MirrorComponents", MirrorComponentsCommand))


def _face_sig(face):
    return [face.Surface.TypeId, round(face.Area, 6)]


def _find_face(comp, sig, near):
    """The face of comp like the one sig was taken from, nearest the point near (the seed
    component sits in the driving seed hole). FreeCAD renumbers faces when the part changes
    (a Polar Pattern of 8 holes after 6)."""
    best = None
    for i in range(1, 100000):
        name = "Face%d" % i
        f = comp.getSubObject(name)
        if f is None or f.isNull() or f.ShapeType != "Face":
            break
        if f.Surface.TypeId != sig[0] or abs(f.Area - sig[1]) > 1e-4 * max(1.0, sig[1]):
            continue
        d = (V(f.CenterOfMass) - near).Length
        if best is None or d < best[0]:
            best = (d, name)
    return best[1] if best is not None else None


def _seed_centre(asm, feat):
    from . import asmcpattern
    pts = [s.Shape.BoundBox.Center for s in asmcpattern.seeds(feat) if s.Shape.BoundBox.isValid()]
    if not pts:
        return None
    c = V()
    for p in pts:
        c = c + p
    return c * (1.0 / len(pts))


def refollow_driven(asm, feat, v):
    ""


    from . import asmcpattern
    doc = asm.Document
    comp = doc.getObject(v.get("comp", "")) if v.get("comp") else None
    if comp is None or not v.get("face"):
        return None
    face = comp.getSubObject(v["face"])
    ok = face is not None and not face.isNull() and face.ShapeType == "Face"
    sig = v.get("sig") or (_face_sig(face) if ok else None)
    near = _seed_centre(asm, feat)
    if sig is None or near is None:
        return None
    name = _find_face(comp, sig, near)      # the hole the seed sits in, whatever its number now
    if name is None:
        return None
    face = comp.getSubObject(name)
    found = driving_instances(comp, name)
    if not found:
        return None
    nv = dict(v, face=name, sig=_face_sig(face)[:2])
    skip = set(v.get("skip", []))
    changed = nv != v
    insts = asmcpattern.instances(feat)
    keep = []
    for seed in asmcpattern.seeds(feat):
        mine = {getattr(l, asmcpattern.INDEX_PROP, ""): l for l in insts if getattr(l, asmcpattern.SEED_PROP, None) is seed}
        want = {"(%d)" % (i + 2): m for i, m in enumerate(found)}
        for index, link in mine.items():
            if index not in want or index in skip:
                asmcpattern._unfix(asm, link)
                doc.removeObject(link.Name)
                changed = True
        for index, move in want.items():
            if index in skip:
                continue
            link = mine.get(index)
            if link is None:
                link = ac.insert(asm, seed.LinkedObject, move.multiply(seed.Placement))
                link.Placement = move.multiply(seed.Placement)
                asmcpattern._drive(asm, feat, seed, link, index)
                changed = True
            elif not getattr(link, asmcpattern.MOVE_PROP).isSame(move, 1e-9):
                setattr(link, asmcpattern.MOVE_PROP, move)
                changed = True
            keep.append(link)
    if not changed:
        return None
    feat.FwPatternInstances = keep
    return nv


def refollow(feat, v):
    ""


    from . import asmcpattern
    import Part
    kind = getattr(feat, asmcpattern.KIND_PROP, "")
    doc = feat.Document
    if kind == "sketch":
        got = driving_shape(v["src"]) if v.get("src") else None
        if got is None or not v.get("refs"):
            return None
        shape, sketch, whole = got
        pts = sketch_points(whole if whole is not None else shape)
        if len(pts) == len(v.get("points", [])) and all((a - V(*b)).Length < 1e-7 for a, b in zip(pts, v["points"])):
            return None
        moves = {}
        for name, ref in v["refs"].items():
            ref = V(*ref)
            own = [p - ref for p in pts if (p - ref).Length >= 1e-6]
            moves[name] = {"(%d)" % (i + 2): App.Placement(m, App.Rotation()) for i, m in enumerate(own)}
        v = dict(v, points=[list(p) for p in pts])
    elif kind == "curve":
        got = driving_shape(v["src"]) if v.get("src") else None
        if got is None or got[0].ShapeType != "Edge":
            return None
        edge = got[0]
        two = v.get("count2", 1) > 1 and v.get("edge2")
        edge2 = None
        if two:
            got2 = driving_shape(v["src2"]) if v.get("src2") else None
            if got2 is not None and got2[0].ShapeType == "Edge":
                edge2 = got2[0]
            else:
                sh = Part.Shape()
                sh.importBrepFromString(v["edge2"])
                edge2 = sh.Edges[0]
        stamp = [shape_stamp(edge), shape_stamp(edge2) if edge2 is not None else []]
        if stamp == v.get("stamp"):
            return None
        normal = None
        if v.get("normal"):
            sh = Part.Shape()
            sh.importBrepFromString(v["normal"])
            normal = sh.Faces[0] if sh.Faces else None
        moves = {}
        for seed in asmcpattern.seeds(feat):
            m1 = curve_moves(seed, edge, v.get("count", 4), v.get("spacing", 25.0), v.get("equal", True),
                             v.get("tangent", True), v.get("reverse", False), v.get("offset", False), normal)
            if edge2 is None:
                moves[seed.Name] = {"(%d)" % (i + 2): m for i, m in enumerate(m1)}
                continue
            m2 = curve_moves(seed, edge2, v.get("count2", 1), v.get("spacing2", 25.0), v.get("equal2", True),
                             v.get("tangent", True), v.get("reverse2", False), v.get("offset", False), normal)
            own = {"(%d,1)" % (i + 2): m for i, m in enumerate(m1)}
            for j, b in enumerate(m2):
                own["(1,%d)" % (j + 2)] = b
                for i, a in enumerate(m1):
                    own["(%d,%d)" % (i + 2, j + 2)] = b.multiply(a)
            moves[seed.Name] = own
        v = dict(v, stamp=stamp, edge=edge.exportBrepToString())
    elif kind == "chain":
        got = driving_shape(v["src"]) if v.get("src") else None
        if got is None:
            return None
        shape, sketch, whole = got
        source = whole if sketch is not None and whole is not None else (shape if shape.ShapeType == "Edge" else None)
        if source is None:
            return None
        wires = source.Wires if source.Wires else [Part.Wire(source.Edges)] if source.Edges else []
        if not wires:
            return None
        edge = shape.Edges[0] if shape.Edges else None
        mid = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter)) if edge is not None else None
        on = [w for w in wires if mid is not None and w.distToShape(Part.Vertex(mid))[0] < 1e-6]
        wire = on[0] if on else max(wires, key=lambda w: w.Length)
        stamp = shape_stamp(wire)
        if stamp == v.get("stamp"):
            return None
        k = v.get("kind", "Distance")
        pins = [V(*p) for p in v.get("pins", [])]
        group2 = [g for g in (doc.getObject(n) for n in v.get("group2", [])) if g is not None]
        moves = {}
        for seed in asmcpattern.seeds(feat):
            links = {seed: pins} if k != "Distance" and len(pins) == 2 else None
            own = {}
            for i, (src, m) in enumerate(chain_moves(seed, wire, v.get("spacing", 25.0), v.get("count", 4),
                                                     v.get("fill", False), k, links, V(*v["align"]) if v.get("align") else None,
                                                     v.get("flip", False), v.get("reverse", False), group2,
                                                     v.get("spacing_method") == "Linear distance")):
                own["(%d)" % (i + 2)] = m if src is seed else m.multiply(src.Placement).multiply(seed.Placement.inverse())
            moves[seed.Name] = own
        v = dict(v, stamp=stamp, wire=wire.exportBrepToString())
    else:
        return None
    for link in asmcpattern.instances(feat):
        seed = getattr(link, asmcpattern.SEED_PROP, None)
        m = moves.get(getattr(seed, "Name", ""), {}).get(getattr(link, asmcpattern.INDEX_PROP, ""))
        if m is not None:
            setattr(link, asmcpattern.MOVE_PROP, m)
    return v
