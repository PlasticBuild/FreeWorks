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

import json
import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

from . import asmcore as ac


def _show(box, raw):
    ""
    from . import asmpattern
    asmpattern.show_pick(box, raw)


def _raw(box):
    from . import asmpattern
    return asmpattern.pick_raw(box)

V = App.Vector
KIND_PROP = "FwCompPattern"         # linear, circular, driven, sketch, curve, chain, mirror
DATA_PROP = "FwCompPatternData"     # json: the PM's values, to edit it again
OF_PROP = "FwPatternOf"             # on an instance: its pattern's name
SEED_PROP = "FwPatternSeed"
MOVE_PROP = "FwPatternMove"         # the instance's placement = move * seed's placement
MIRROR_PROP = "FwPatternMirror"     # a mirror copy: point, normal, flip
INDEX_PROP = "FwPatternIndex"       # (2), (3,1)...
NAMES = {"linear": "LocalLPattern", "circular": "LocalCirPattern", "driven": "DerivedLPattern",
         "sketch": "LocalSketchPattern", "curve": "LocalCurvePattern", "chain": "LocalChainPattern",
         "mirror": "MirrorComponent"}
TITLES = {"linear": "Linear Component Pattern", "circular": "Circular Component Pattern",
          "driven": "Pattern Driven Component Pattern", "sketch": "Sketch Driven Component Pattern",
          "curve": "Curve Driven Component Pattern", "chain": "Chain Component Pattern",
          "mirror": "Mirror Components"}
AXES = (("X", V(1, 0, 0)), ("Y", V(0, 1, 0)), ("Z", V(0, 0, 1)))


# ---------------------------------------------------------------- the feature
def is_pattern(obj):
    return obj is not None and bool(getattr(obj, KIND_PROP, ""))


def patterns(asm):
    return [o for o in asm.Group if is_pattern(o)]


def instances(feat):
    return [o for o in (getattr(feat, "FwPatternInstances", None) or []) if o is not None]


def seeds(feat):
    return [o for o in (getattr(feat, "FwPatternSeeds", None) or []) if o is not None]


def data(feat):
    try:
        return json.loads(getattr(feat, DATA_PROP, "") or "{}")
    except ValueError:
        return {}


def _name(asm, kind):
    stem = NAMES[kind]
    taken = {o.Label for o in asm.Document.Objects}
    n = 1
    while "%s%d" % (stem, n) in taken:
        n += 1
    return "%s%d" % (stem, n)


def _unfix(asm, comp):
    g = ac.grounded(asm).get(comp)
    if g is not None:
        asm.Document.removeObject(g.Name)


def _drive(asm, feat, seed, link, index, mirror=None):
    """link becomes an instance of feat: driven by its seed, not fixed."""
    _unfix(asm, link)
    for prop, t in ((OF_PROP, "App::PropertyString"), (SEED_PROP, "App::PropertyLink"),
                    (MOVE_PROP, "App::PropertyPlacement"), (MIRROR_PROP, "App::PropertyString"),
                    (INDEX_PROP, "App::PropertyString")):
        if not hasattr(link, prop):
            link.addProperty(t, prop, "FreeCAD", "Component pattern instance")
            link.setEditorMode(prop, 2)
    setattr(link, OF_PROP, feat.Name)
    setattr(link, SEED_PROP, seed)
    setattr(link, INDEX_PROP, index)
    if mirror is not None:
        setattr(link, MIRROR_PROP, json.dumps(mirror))
    else:
        setattr(link, MOVE_PROP, link.Placement.multiply(seed.Placement.inverse()))


def make_feature(asm, kind, entries, values, label=None):
    """entries: [(seed, index, link, mirror spec or None)] in order. The pattern feature, its
    instances driven by their seeds. label: the feature being edited (it is kept, its old
    instances are already gone) or None for a new one."""
    if label is not None and not isinstance(label, str) and is_pattern(label):
        feat = label
    else:
        feat = asm.newObject("App::FeaturePython", NAMES[kind])
        PatternFeature(feat)
        setattr(feat, KIND_PROP, kind)
        feat.Label = _name(asm, kind)
        if App.GuiUp and feat.ViewObject is not None:
            ViewProviderPattern(feat.ViewObject)
    setattr(feat, DATA_PROP, json.dumps(values))
    order = []
    for seed, _i, _l, _m in entries:
        if seed not in order:
            order.append(seed)
    feat.FwPatternSeeds = order
    for seed, index, link, mirror in entries:
        _drive(asm, feat, seed, link, index, mirror)
    feat.FwPatternInstances = [e[2] for e in entries]
    asm.Document.recompute()
    return feat


def build(asm, kind, comps, generate, values, skip=(), label=None, mirror=None):
    """Runs generate(seed) for each seed: [(index, link)] in order. Skipped indexes are taken
    away again; the rest become the pattern's instances. mirror(seed, link): the link's mirror
    spec, for Mirror Components."""
    doc = asm.Document
    entries = []
    skip = set(skip or ())
    for seed in comps:
        for index, link in generate(seed):
            if index in skip:
                _unfix(asm, link)
                doc.removeObject(link.Name)
                continue
            entries.append((seed, index, link, mirror(seed, link) if mirror else None))
    if not entries and label is None:
        return None
    values = dict(values, skip=sorted(skip), seeds=[c.Name for c in comps])
    return make_feature(asm, kind, entries, values, label)


def numbered(links, first=2):
    return [("(%d)" % (i + first), l) for i, l in enumerate(links)]


def follow(asm):
    """After a solve: every pattern instance back where its pattern keeps it."""
    from . import asmpattern
    for feat in patterns(asm):
        if getattr(feat, "Suppressed", False):
            continue
        v = data(feat)
        if v.get("src") and getattr(feat, KIND_PROP, "") in ("curve", "sketch", "chain"):
            try:
                nv = asmpattern.refollow(feat, v)
                if nv is not None:
                    setattr(feat, DATA_PROP, json.dumps(nv))
                    v = nv
            except Exception as error:
                App.Console.PrintLog("FreeCAD: driven pattern: %s\n" % error)
        if getattr(feat, KIND_PROP, "") == "driven":
            try:
                nv = asmpattern.refollow_driven(asm, feat, v)     # the driving pattern changed
                if nv is not None:
                    setattr(feat, DATA_PROP, json.dumps(nv))
                    v = nv
            except Exception as error:
                App.Console.PrintLog("FreeCAD: driven pattern: %s\n" % error)
        sync = bool(v.get("sync"))
        for link in instances(feat):
            seed = getattr(link, SEED_PROP, None)
            if seed is None:
                continue
            try:
                spec = getattr(link, MIRROR_PROP, "")
                if spec:
                    m = json.loads(spec)
                    if m.get("hand"):
                        want = asmpattern.hand_placement(seed.Placement, V(*m["point"]), V(*m["normal"]), m["hand"])
                    else:
                        want = asmpattern.mirrored_placement(seed.Placement, V(*m["point"]), V(*m["normal"]), tuple(m["flip"]),
                                                             m.get("ref"))
                else:
                    want = getattr(link, MOVE_PROP).multiply(seed.Placement)
                if not link.Placement.isSame(want, 1e-9):
                    link.Placement = want
                if sync:
                    sync_flexible(seed, link)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: pattern instance: %s\n" % error)


def sync_flexible(seed, inst):
    """Synchronize movement of flexible subassembly components: a flexible subassembly's
    instance takes its components where the seed has them (each in its own frame)."""
    if not ac.is_flexible(seed) or not ac.is_subassembly(inst):
        return False
    if getattr(inst, "Rigid", True):
        inst.Rigid = False
    mine, theirs = ac.sub_components(seed), ac.sub_components(inst)
    moved = False
    for a, b in zip(mine, theirs):
        if not b.Placement.isSame(a.Placement, 1e-9):
            b.Placement = App.Placement(a.Placement)
            moved = True
    return moved


SYNC_TEXT = "Synchronize movement of flexible subassembly components"


def add_options(panel):
    ""

    if getattr(panel, "sync", None) is not None or not hasattr(panel, "form"):
        return panel
    from . import asmpm
    lay = getattr(panel, "_options_lay", None)     # asmpkg371: a PM with its own Options group gets the box there
    box = None
    if lay is None:
        box, lay = asmpm._box("Options")
    panel.sync = QtWidgets.QCheckBox(SYNC_TEXT)
    panel.sync.setObjectName("FW_PatternSync")
    panel.sync.setToolTip("Instances of a flexible subassembly move their components as the seed's do")
    lay.addWidget(panel.sync)
    if box is not None:
        panel.form = list(panel.form) + [box]
    values0, load0 = panel.values, getattr(panel, "load", None)

    def values():
        v = values0()
        v["sync"] = panel.sync.isChecked()
        return v
    panel.values = values
    if load0 is not None:
        def load(v):
            load0(v)
            panel.sync.setChecked(bool(v.get("sync")))
        panel.load = load
    return panel


def delete(feat):
    ""
    asm = ac.assembly_of(feat.Document)
    doc = feat.Document
    doc.openTransaction("Delete %s" % feat.Label)
    try:
        for link in instances(feat):
            _unfix(asm, link)
            doc.removeObject(link.Name)
        doc.removeObject(feat.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()


def dissolve(feat):
    """Dissolve Pattern: the instances stay as plain components, fixed where they are."""
    asm = ac.assembly_of(feat.Document)
    doc = feat.Document
    doc.openTransaction("Dissolve Pattern")
    try:
        for link in instances(feat):
            for prop in (OF_PROP, SEED_PROP, MOVE_PROP, MIRROR_PROP, INDEX_PROP):
                if hasattr(link, prop):
                    link.removeProperty(prop)
            ac.fix(asm, link)
        feat.FwPatternInstances = []
        doc.removeObject(feat.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()


def edit(feat):
    """Edit Feature: the pattern's PM with its values; OK makes it again under the same name."""
    from . import asmpm, asmpattern
    asm = ac.assembly_of(feat.Document)
    if asm is None or not asmpm.close_open():
        return None
    cls = {"linear": LinearPanel, "circular": asmpattern.CircularPatternPanel, "mirror": asmpattern.MirrorPanel,
           "sketch": asmpattern.SketchPatternPanel, "curve": asmpattern.CurvePatternPanel,
           "chain": asmpattern.ChainPatternPanel, "driven": asmpattern.PatternDrivenPanel}[getattr(feat, KIND_PROP)]
    panel = cls(asm, seeds(feat))
    if getattr(feat, KIND_PROP) != "mirror":
        add_options(panel)
    panel.editing = feat
    if hasattr(panel, "load"):
        panel.load(data(feat))
    asmpm._track(panel)
    Gui.Control.showDialog(panel)
    return panel


def replace_old(panel):
    """On OK while editing: the old instances go; returns the feature, kept for the new ones."""
    feat = getattr(panel, "editing", None)
    if feat is None:
        return None
    doc = feat.Document
    asm = ac.assembly_of(doc)
    for link in instances(feat):
        _unfix(asm, link)
        doc.removeObject(link.Name)
    feat.FwPatternInstances = []
    panel.editing = None
    return feat


class PatternFeature:
    def __init__(self, obj):
        obj.Proxy = self
        if not hasattr(obj, KIND_PROP):
            obj.addProperty("App::PropertyString", KIND_PROP, "FreeCAD", "Component pattern")
            obj.addProperty("App::PropertyString", DATA_PROP, "FreeCAD", "Its PropertyManager's values")
            obj.addProperty("App::PropertyLinkListHidden", "FwPatternSeeds", "FreeCAD", "Seed components")
            obj.addProperty("App::PropertyLinkListHidden", "FwPatternInstances", "FreeCAD", "Instances")
            obj.addProperty("App::PropertyBool", "Suppressed", "FreeCAD", "Suppressed")
            for p in (KIND_PROP, DATA_PROP):
                obj.setEditorMode(p, 2)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderPattern:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            from pivy import coin
            vobj.addDisplayMode(coin.SoGroup(), "Default")
        except Exception as _fw_err:
            _fw_log("asmcpattern.py:354", _fw_err)

    def getIcon(self):
        kind = getattr(getattr(self, "Object", None), KIND_PROP, "linear")
        return {"circular": "PartDesign_PolarPattern", "mirror": "PartDesign_Mirrored"}.get(kind, "PartDesign_LinearPattern")

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        return instances(obj) if obj is not None else []

    def doubleClicked(self, vobj):
        edit(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        menu.addAction("Edit Feature").triggered.connect(lambda: edit(vobj.Object))
        menu.addAction("Dissolve Pattern").triggered.connect(lambda: dissolve(vobj.Object))

    def onDelete(self, vobj, subs):
        feat = vobj.Object
        doc = feat.Document
        asm = ac.assembly_of(doc)
        for link in instances(feat):
            try:
                _unfix(asm, link)
                doc.removeObject(link.Name)
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:387", _fw_err)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


# ---------------------------------------------------------------- Instances to Skip
if Gui is not None:
    class SkipBox:
        ""

        def __init__(self, labels_fn):
            from . import asmpm
            self.labels_fn = labels_fn
            self.box, lay = asmpm._box("Instances to Skip")
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("FW_PatternSkip")
            self.list.setFixedHeight(asmpm._rows(self.list, 4))
            self.list.setToolTip("Check the instances not to make")
            lay.addWidget(self.list)
            self.refresh()

        def refresh(self, *args):
            keep = self.skipped()
            self.list.clear()
            for label in self.labels_fn():
                it = QtWidgets.QListWidgetItem(label)
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if label in keep else QtCore.Qt.Unchecked)
                self.list.addItem(it)

        def skipped(self):
            return [self.list.item(i).text() for i in range(self.list.count())
                    if self.list.item(i).checkState() == QtCore.Qt.Checked]

        def set(self, labels):
            for i in range(self.list.count()):
                it = self.list.item(i)
                it.setCheckState(QtCore.Qt.Checked if it.text() in labels else QtCore.Qt.Unchecked)


# ---------------------------------------------------------------- Linear Component Pattern
def linear_instances(asm, seed, d1, s1, n1, d2=None, s2=0.0, n2=1, seed_only=False):
    """[(index, link)]: (i) along Direction 1, (i,j) with Direction 2 ((1,j) the seed's own
    column; Pattern seed only: Direction 2 copies the seed alone)."""
    out = []
    d1 = V(d1).normalize()
    d2 = V(d2).normalize() if d2 is not None and n2 > 1 else None
    for j in range(1, (n2 if d2 is not None else 1) + 1):
        for i in range(1, n1 + 1):
            if i == 1 and j == 1:
                continue
            if seed_only and j > 1 and i > 1:
                continue
            move = d1 * (s1 * (i - 1))
            if d2 is not None:
                move = move + d2 * (s2 * (j - 1))
            pl = App.Placement(seed.Placement)
            pl.Base = pl.Base + move
            link = ac.insert(asm, seed.LinkedObject, pl)
            link.Placement = pl
            out.append(("(%d)" % i if d2 is None else "(%d,%d)" % (i, j), link))
    asm.Document.recompute()
    return out


def _ref_geometry(shape):
    """(point, normal or None) of a picked reference: a flat face's plane, else a point on it."""
    g = ac.geometry(shape)
    if g is not None and g[0] == "plane":
        return V(g[1]), V(g[2]).normalize()
    try:
        if shape.ShapeType == "Vertex":
            return V(shape.Point), None
        return V(shape.CenterOfMass if hasattr(shape, "CenterOfMass") else shape.BoundBox.Center), None
    except Exception:
        return V(shape.BoundBox.Center), None


def _parse_label(label):
    elem, _at, comp = (label or "").partition("@")
    return elem.strip(), comp.strip()


def substitute(asm, label, d):
    ""


    elem, comp_label = _parse_label(label)
    if not elem or not comp_label:
        return label, "ok"
    comp = next((c for c in ac.components(asm) if c.Label == comp_label), None)
    if comp is None:
        return "", "missing"
    d = V(d).normalize()
    try:
        shape = comp.Shape
    except Exception:
        return "", "missing"
    try:
        got = _direction_of(shape.getElement(elem))
        if got is not None and abs(abs(got.dot(d)) - 1.0) < 1e-6:
            return label, "ok"
    except Exception as _fw_err:
        _fw_log("asmcpattern.py:495", _fw_err)
    for kind, items in (("Edge", shape.Edges), ("Face", shape.Faces)):
        if not elem.startswith(kind):
            continue
        for i, e in enumerate(items, 1):
            try:
                got = _direction_of(e)
            except Exception:
                got = None
            if got is not None and abs(abs(got.dot(d)) - 1.0) < 1e-6:
                return "%s%d@%s" % (kind, i, comp.Label), "repaired"
    return "", "missing"


def substitute_axis(asm, label, point, d):
    ""

    elem, comp_label = _parse_label(label)
    comp = next((c for c in ac.components(asm) if c.Label == comp_label), None) if comp_label else None
    if comp is None:
        return ("", "missing") if comp_label else (label, "ok")
    p0, d = V(point), V(d).normalize()

    def on_line(shape):
        g = ac.geometry(shape)
        if g is None or g[0] not in ("axis", "line"):
            return False
        if abs(abs(V(g[2]).normalize().dot(d)) - 1.0) > 1e-6:
            return False
        off = V(g[1]) - p0
        return (off - d * off.dot(d)).Length < 1e-4
    try:
        if on_line(comp.Shape.getElement(elem)):
            return label, "ok"
    except Exception as _fw_err:
        _fw_log("asmcpattern.py:530", _fw_err)
    for kind, items in (("Face", comp.Shape.Faces), ("Edge", comp.Shape.Edges)):
        for i, e in enumerate(items, 1):
            try:
                if on_line(e):
                    return "%s%d@%s" % (kind, i, comp.Label), "repaired"
            except Exception:
                continue
    return "", "missing"


def repair_references(asm, v):
    """The pattern's direction references checked (and repaired) before its PM shows them."""
    labels = list(v.get("labels") or [])
    if not labels:
        return v
    out = dict(v)
    new, notes = [], []
    for k, label in enumerate(labels):
        d = v.get("d%d" % (k + 1))
        if not label or d is None:
            new.append(label)
            continue
        got, how = substitute(asm, label, d)
        new.append(got)
        if how != "ok":
            notes.append("%s: %s" % (label, "replaced by " + got if how == "repaired" else "missing (the direction is kept)"))
    out["labels"] = new
    if notes:
        App.Console.PrintMessage("FreeCAD: pattern references: %s\n" % "; ".join(notes))
    out["repairs"] = notes
    return out


def _direction_of(shape):
    """A straight edge or round face's axis, or a flat face's normal; None otherwise."""
    g = ac.geometry(shape)
    if g is None:
        return None
    if g[0] in ("axis", "line", "plane"):
        return V(g[2]).normalize()
    return None


class InstancePreview:
    ""




    def __init__(self, asm):
        self.asm = asm
        self.root = None
        self.moves = []
        self.hidden = []

    def _view(self):
        try:
            gd = Gui.getDocument(self.asm.Document.Name)
            return gd.ActiveView if gd is not None else None
        except Exception:
            return None

    def show(self, comps, moves):
        """moves: each instance's offset from the seed in the assembly: a vector (a move) or an
        App.Placement (a move and turn, e.g. round a circular pattern's axis)."""
        from pivy import coin
        self.clear()
        view = self._view()
        if view is None or not comps or not moves:
            self.moves = list(moves) if comps else []
            return
        self.root = coin.SoSeparator()
        self.root.setName("FW_PatternPreview")
        try:
            gp = self.asm.getGlobalPlacement()
        except Exception:
            gp = App.Placement()
        for move in moves:
            sep = coin.SoSeparator()
            t = coin.SoTransform()
            delta = move if isinstance(move, App.Placement) else App.Placement(V(move), App.Rotation())
            pl = delta.multiply(gp)
            t.translation.setValue(tuple(pl.Base))
            q = pl.Rotation.Q
            t.rotation.setValue(q[0], q[1], q[2], q[3])
            sep.addChild(t)
            for comp in comps:
                try:
                    node = comp.ViewObject.RootNode
                except Exception:
                    node = None
                if node is not None:
                    sep.addChild(node)
            self.root.addChild(sep)
        view.getSceneGraph().addChild(self.root)
        self.moves = list(moves)

    def clear(self):
        if self.root is not None:
            view = self._view()
            try:
                if view is not None:
                    view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:635", _fw_err)
        self.root = None
        self.moves = []

    def hide_old(self, links):
        for link in links:
            try:
                if link.ViewObject.Visibility:
                    link.ViewObject.Visibility = False
                    self.hidden.append(link)
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:646", _fw_err)

    def restore_old(self):
        for link in self.hidden:
            try:
                link.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:653", _fw_err)
        self.hidden = []


def linear_moves(v, skipped=()):
    """[(label, offset)] of a Linear Component Pattern's instances from its PM values, less the
    skipped ones (the same instances and labels as linear_instances makes)."""
    d1 = V(*v["d1"]).normalize()
    n2 = int(v.get("n2", 1) or 1)
    d2 = V(*v["d2"]).normalize() if n2 > 1 else None
    out = []
    for j in range(1, (n2 if d2 is not None else 1) + 1):
        for i in range(1, int(v["n1"]) + 1):
            if (i, j) == (1, 1) or (v.get("seed_only") and j > 1 and i > 1):
                continue
            label = "(%d)" % i if d2 is None else "(%d,%d)" % (i, j)
            if label in skipped:
                continue
            move = d1 * (v["s1"] * (i - 1))
            if d2 is not None:
                move = move + d2 * (v["s2"] * (j - 1))
            out.append((label, move))
    return out


if Gui is not None:
    class LinearPanel:
        ""

        def __init__(self, asm, comps):
            from . import asmpm, asmpattern
            self.asm = asm
            self.editing = None
            self.dirs = [None, None]        # (vector, label) picked for Direction 1 and 2
            self.active = 0                 # the direction box a pick goes to
            # picks made before the PM opened are its components (the seed): later picks go to the boxes
            self._seen = set()
            try:
                self._seen = {(sel.Object.Name, sub) for sel in Gui.Selection.getSelectionEx("", 0)
                              for sub in (sel.SubElementNames or ("",))}
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:694", _fw_err)
            boxes = []
            self.fields = []
            for n in (1, 2):
                if n == 1:
                    box, lay = asmpm._box("Direction 1", "Linear Pattern", "ASSEMBLIES_LINEAR_PATTERN")
                else:
                    box, lay = asmpm._box("Direction 2")
                row = QtWidgets.QHBoxLayout()
                pick = QtWidgets.QLineEdit("")
                pick.setObjectName("FW_PatternDirection%d" % n)
                pick.setReadOnly(True)
                pick.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
                pick.setToolTip("Pattern Direction: pick an edge, axis or flat face")
                pick.setPlaceholderText("Pattern Direction")
                pick.installEventFilter(self._focus_filter(n - 1))
                asmpattern.click_box(self, ("dir", n - 1), pick)
                axis = QtWidgets.QComboBox()
                axis.setObjectName("FW_PatternAxis" if n == 1 else "FW_PatternAxis2")
                axis.addItems([a for a, _v in AXES])
                axis.setCurrentIndex(0 if n == 1 else 1)
                axis.setToolTip("Without a pick: the assembly's axis")

                rev = asmpm.reverse_button("FW_PatternReverse%s" % ("" if n == 1 else "2"))
                row.addWidget(rev)
                row.addWidget(pick, 1)
                row.addWidget(axis)

                # names the assembly's axis it uses (X-axis); the axis list itself is not shown
                axis.hide()
                pick.setText("%s-axis" % axis.currentText())
                axis.currentIndexChanged.connect(lambda _i, k=n - 1: self._axis_shown(k))
                lay.addLayout(row)
                spacing = QtWidgets.QDoubleSpinBox()
                spacing.setObjectName("FW_PatternSpacing" if n == 1 else "FW_PatternSpacing2")
                spacing.setRange(0.001, 1.0e6)
                spacing.setDecimals(2)
                spacing.setSuffix("mm")
                spacing.setValue(25.0)
                count = QtWidgets.QSpinBox()
                count.setObjectName("FW_PatternCount" if n == 1 else "FW_PatternCount2")
                count.setRange(1 if n == 2 else 2, 1000)
                count.setValue(2 if n == 1 else 1)

                mode_si = QtWidgets.QRadioButton("Spacing and instances")
                mode_si.setObjectName("FW_PatternSpacingMode%d" % n)
                mode_ur = QtWidgets.QRadioButton("Up to reference")
                mode_ur.setObjectName("FW_PatternUpTo%d" % n)
                mode_si.setChecked(True)
                mgroup = QtWidgets.QButtonGroup(box)
                mgroup.addButton(mode_si)
                mgroup.addButton(mode_ur)
                lay.addWidget(mode_si)
                lay.addWidget(mode_ur)
                ref = QtWidgets.QLineEdit("")
                ref.setObjectName("FW_PatternRef%d" % n)
                ref.setReadOnly(True)
                ref.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
                ref.setPlaceholderText("Reference Geometry")
                ref.setToolTip("Pick the face, plane, edge or vertex the pattern goes up to")
                ref.installEventFilter(self._focus_filter(n - 1))
                asmpattern.click_box(self, ("ref", n - 1), ref)
                offset = QtWidgets.QDoubleSpinBox()
                offset.setObjectName("FW_PatternOffset%d" % n)
                offset.setRange(0.0, 1.0e6)
                offset.setDecimals(2)
                offset.setSuffix("mm")
                off_rev = QtWidgets.QCheckBox("Reverse offset direction")
                off_rev.setObjectName("FW_PatternOffsetReverse%d" % n)
                set_sp = QtWidgets.QRadioButton("Set spacing")
                set_sp.setObjectName("FW_PatternSetSpacing%d" % n)
                set_ct = QtWidgets.QRadioButton("Set number of instances")
                set_ct.setObjectName("FW_PatternSetCount%d" % n)
                set_sp.setChecked(True)
                sgroup = QtWidgets.QButtonGroup(box)
                sgroup.addButton(set_sp)
                sgroup.addButton(set_ct)
                upto = QtWidgets.QWidget()
                ulay = QtWidgets.QVBoxLayout(upto)
                ulay.setContentsMargins(0, 0, 0, 0)
                ulay.addWidget(ref)
                urow = QtWidgets.QFormLayout()
                urow.addRow("Offset distance:", offset)
                ulay.addLayout(urow)
                ulay.addWidget(off_rev)

                seed_bb = QtWidgets.QRadioButton("Bounding box center")
                seed_bb.setObjectName("FW_PatternSeedBox%d" % n)
                seed_sel = QtWidgets.QRadioButton("Selected reference")
                seed_sel.setObjectName("FW_PatternSeedSel%d" % n)
                seed_bb.setChecked(True)
                kgroup = QtWidgets.QButtonGroup(box)
                kgroup.addButton(seed_bb)
                kgroup.addButton(seed_sel)
                seed_ref = QtWidgets.QLineEdit("")
                seed_ref.setObjectName("FW_PatternSeedRef%d" % n)
                seed_ref.setReadOnly(True)
                seed_ref.setStyleSheet(asmpm.PICK_STYLE.replace("QListWidget", "QLineEdit"))
                seed_ref.setPlaceholderText("Seed Reference")
                seed_ref.setToolTip("Pick a face, edge or vertex of the seed the distance is measured from")
                seed_ref.installEventFilter(self._focus_filter(n - 1))
                asmpattern.click_box(self, ("seed", n - 1), seed_ref)
                seed_ref.setVisible(False)
                ulay.addWidget(QtWidgets.QLabel("Seed reference:"))
                ulay.addWidget(seed_bb)
                ulay.addWidget(seed_sel)
                ulay.addWidget(seed_ref)
                ulay.addWidget(set_sp)
                ulay.addWidget(set_ct)
                lay.addWidget(upto)
                upto.setVisible(False)
                form = QtWidgets.QFormLayout()
                form.addRow("Spacing:", spacing)
                form.addRow("Instances:", count)
                lay.addLayout(form)
                f = {"pick": pick, "axis": axis, "reverse": rev, "spacing": spacing, "count": count,
                     "upto": mode_ur, "ref": ref, "offset": offset, "off_rev": off_rev, "set_spacing": set_sp,
                     "set_count": set_ct, "upto_box": upto, "refgeo": None,
                     "seed_sel": seed_sel, "seed_ref": seed_ref, "seedgeo": None}
                seed_sel.toggled.connect(lambda on, ff=f: (ff["seed_ref"].setVisible(on), on and ff["seed_ref"].setFocus(),
                                                           self._upto_shown(ff)))
                mode_ur.toggled.connect(lambda on, ff=f: self._upto_shown(ff))
                set_sp.toggled.connect(lambda on, ff=f: self._upto_shown(ff))
                for w in (offset, spacing, count):
                    w.valueChanged.connect(lambda *_a, ff=f: ff["upto"].isChecked() and self._upto_shown(ff))
                off_rev.toggled.connect(lambda *_a, ff=f: self._upto_shown(ff))
                if n == 2:
                    self.seed_only = QtWidgets.QCheckBox("Pattern seed only")
                    self.seed_only.setObjectName("FW_PatternSeedOnly")
                    lay.addWidget(self.seed_only)
                    self.seed_only.toggled.connect(lambda *_: self.skip.refresh())
                self.fields.append(f)
                boxes.append(box)
            # legacy names the older checks and keys use
            self.axis, self.reverse = self.fields[0]["axis"], self.fields[0]["reverse"]
            self.spacing, self.count = self.fields[0]["spacing"], self.fields[0]["count"]
            from . import asmpattern
            seeds_box = asmpattern._Panel._components_box(self, "Components to Pattern")
            self.skip = SkipBox(self.instance_labels)
            for f in self.fields:
                f["count"].valueChanged.connect(self.skip.refresh)
            self.comps = []
            for comp in comps:
                self._add(comp)
            self.form = boxes + [seeds_box, self.skip.box]
            QtCore.QTimer.singleShot(0, lambda: _fold(boxes[1]))
            Gui.Selection.addObserver(self, 0)

            self.preview = InstancePreview(asm)
            self._preview_due = False
            for f in self.fields:
                for w in (f["spacing"], f["count"], f["offset"]):
                    w.valueChanged.connect(self.update_preview)
                for w in (f["reverse"], f["upto"], f["off_rev"], f["set_spacing"]):
                    w.toggled.connect(self.update_preview)
                f["axis"].currentIndexChanged.connect(self.update_preview)
            self.seed_only.toggled.connect(self.update_preview)
            self.skip.list.itemChanged.connect(self.update_preview)
            self.update_preview()

        def update_preview(self, *args):
            """Shown once the values settle (one redraw for a run of changes)."""
            if self._preview_due:
                return
            self._preview_due = True
            QtCore.QTimer.singleShot(0, self.refresh_preview)

        def refresh_preview(self):
            self._preview_due = False
            if getattr(self, "_closed", False):
                return
            try:
                if self.editing is not None and not self.preview.hidden:
                    self.preview.hide_old(instances(self.editing))
                v = self.values()
                self.preview.show(self.comps, [m for _l, m in linear_moves(v, self.skip.skipped())])
            except Exception as error:
                App.Console.PrintLog("FreeCAD: pattern preview: %s\n" % error)

        def _end_preview(self, keep_old):
            self._closed = True
            try:
                self.preview.clear()
                if not keep_old:
                    self.preview.restore_old()
                else:
                    self.preview.hidden = []
            except Exception as _fw_err:
                _fw_log("asmcpattern.py:874", _fw_err)

        def _focus_filter(self, which):
            panel = self

            class F(QtCore.QObject):
                def eventFilter(self, obj, ev):
                    if not isinstance(ev, QtCore.QEvent):
                        return False
                    if ev.type() == QtCore.QEvent.FocusIn:
                        panel.active = which
                    return False
            f = F()
            setattr(self, "_filter%d" % which, f)
            return f

        def _add(self, comp):
            if comp in self.comps:
                return
            self.comps.append(comp)
            self.list.addItem(comp.Label)
            if hasattr(self, "preview"):
                self.update_preview()

        def instance_labels(self):
            n1 = self.fields[0]["count"].value()
            n2 = self.fields[1]["count"].value()
            if n2 <= 1:
                return ["(%d)" % i for i in range(2, n1 + 1)]
            out = []
            for j in range(1, n2 + 1):
                for i in range(1, n1 + 1):
                    if (i, j) == (1, 1) or (self.seed_only.isChecked() and j > 1 and i > 1):
                        continue
                    out.append("(%d,%d)" % (i, j))
            return out

        def addSelection(self, doc, obj, sub, pnt):
            QtCore.QTimer.singleShot(0, self._route)

        def removeSelection(self, doc, obj, sub):
            self._seen.discard((obj, sub))

        def clearSelection(self, *args):
            self._seen.clear()

        def _route(self):
            for sel in Gui.Selection.getSelectionEx("", 0):
                for sub in sel.SubElementNames:
                    if (sel.Object.Name, sub) in self._seen:
                        continue
                    self._seen.add((sel.Object.Name, sub))
                    from . import asmpattern
                    found = asmpattern.datum(sel.Object, sub)
                    if found is not None:
                        # an axis (its line) or a plane (its normal) from the tree: the direction
                        self.dirs[self.active] = (found[2], found[3])
                        self.fields[self.active]["pick"].setText(found[3])
                        self.update_preview()
                        continue
                    ref = ac.reference(self.asm, sel.Object, sub) if sub else None
                    if ref is None:
                        continue
                    shape = ac.element(*ref)
                    d = _direction_of(shape) if shape is not None else None
                    which = self.active
                    f = self.fields[which]
                    user = asmpattern.user_box(self)
                    if user == "comps":
                        self._add(ref[0])       # asmpkg364: Components to Pattern clicked
                        continue
                    if user == ("dir", which) and d is not None:
                        label = "%s@%s" % (ref[1].split(".")[-1], ref[0].Label)
                        self.dirs[which] = (d, label)
                        _show(f["pick"], label)
                        if hasattr(self, "preview"):
                            self.update_preview()
                        continue
                    if f["upto"].isChecked() and shape is not None and f["seed_sel"].isChecked() and \
                            ref[0] in self.comps and (f["seed_ref"].hasFocus() or f["seedgeo"] is None):
                        f["seedgeo"] = _seed_point(shape)
                        _show(f["seed_ref"], "%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
                        self._upto_shown(f)
                        continue
                    if f["upto"].isChecked() and shape is not None and ref[0] not in self.comps and \
                            (self.dirs[which] is not None or d is None or f["ref"].hasFocus()):
                        f["refgeo"] = _ref_geometry(shape)
                        _show(f["ref"], "%s@%s" % (ref[1].split(".")[-1], ref[0].Label))
                        self._upto_shown(f)
                        continue
                    if d is not None and self.dirs[which] is None:
                        label = "%s@%s" % (ref[1].split(".")[-1], ref[0].Label)
                        self.dirs[which] = (d, label)
                        _show(self.fields[which]["pick"], label)
                        continue
                    self._add(ref[0])
                if sel.Object in ac.components(self.asm):
                    self._add(sel.Object)

        def _axis_shown(self, which):
            f = self.fields[which] if which < len(getattr(self, "fields", [])) else None
            if f is not None and self.dirs[which] is None:
                f["pick"].setText("%s-axis" % f["axis"].currentText())

        def direction(self, which=0):
            f = self.fields[which]
            d = V(self.dirs[which][0]) if self.dirs[which] else V(AXES[f["axis"].currentIndex()][1])
            return d * -1 if f["reverse"].isChecked() else d

        def _upto_shown(self, f):
            """Up to reference: the reference box, offset and Set spacing / Set number of
            instances; the other of Spacing and Instances follows from the distance."""
            on = f["upto"].isChecked()
            f["upto_box"].setVisible(on)
            if not on:
                f["spacing"].setEnabled(True)
                f["count"].setEnabled(True)
                return
            f["spacing"].setEnabled(f["set_spacing"].isChecked())
            f["count"].setEnabled(not f["set_spacing"].isChecked())
            got = self.up_to(self.fields.index(f))
            if got is None:
                return
            sp, n = got
            for w, val in ((f["spacing"], sp), (f["count"], n)):
                if abs(w.value() - val) > 1e-9:
                    w.blockSignals(True)
                    w.setValue(val)
                    w.blockSignals(False)
            self.skip.refresh()

        def up_to(self, which):
            """(spacing, instances) for Up to reference: from the seeds' centre to the reference
            along the direction, less the offset."""
            f = self.fields[which]
            g = f["refgeo"]
            if not f["upto"].isChecked() or g is None or not self.comps:
                return None
            from . import asmpattern
            d = V(self.direction(which)).normalize()
            if f["seed_sel"].isChecked():
                if f["seedgeo"] is None:
                    return None
                c = V(f["seedgeo"])
            else:
                c = _bbox_center(self.comps)
            point, normal = V(g[0]), (V(g[1]) if g[1] is not None else None)
            if normal is not None and abs(d.dot(normal)) > 1e-9:
                dist = (point - c).dot(normal) / d.dot(normal)
            else:
                dist = (point - c).dot(d)
            dist += f["offset"].value() if f["off_rev"].isChecked() else -f["offset"].value()
            if dist <= 1e-9:
                return (f["spacing"].value(), 1 if which == 1 else 2)
            if f["set_spacing"].isChecked():
                sp = max(f["spacing"].value(), 1e-6)
                return (sp, max(1 if which == 1 else 2, int(math.floor(dist / sp + 1e-9)) + 1))
            n = max(2, f["count"].value())
            return (dist / (n - 1), n)

        def values(self):
            f1, f2 = self.fields
            for f in self.fields:
                if f["upto"].isChecked():
                    self._upto_shown(f)
            ups = []
            for f in self.fields:
                g = f["refgeo"]
                ups.append({"on": f["upto"].isChecked(), "label": _raw(f["ref"]),
                            "point": list(g[0]) if g else None, "normal": list(g[1]) if g and g[1] is not None else None,
                            "offset": f["offset"].value(), "rev": f["off_rev"].isChecked(),
                            "set": "spacing" if f["set_spacing"].isChecked() else "count",
                            "seed": "selected" if f["seed_sel"].isChecked() else "box",
                            "seed_point": list(f["seedgeo"]) if f["seedgeo"] is not None else None,
                            "seed_label": _raw(f["seed_ref"])})
            return {"d1": list(self.direction(0)), "s1": f1["spacing"].value(), "n1": f1["count"].value(),
                    "d2": list(self.direction(1)), "s2": f2["spacing"].value(), "n2": f2["count"].value(),
                    "seed_only": self.seed_only.isChecked(),
                    "labels": [self.dirs[0][1] if self.dirs[0] else "", self.dirs[1][1] if self.dirs[1] else ""],
                    "axes": [f1["axis"].currentIndex(), f2["axis"].currentIndex()], "upto": ups}

        def load(self, v):
            v = repair_references(self.asm, v)
            for k, f in enumerate(self.fields):
                n = str(k + 1)
                d = V(*v.get("d" + n, AXES[k][1]))
                f["axis"].setCurrentIndex((v.get("axes") or [0, 1])[k])
                lbl = (v.get("labels") or ["", ""])[k]
                self.dirs[k] = (d, lbl) if lbl else None
                _show(f["pick"], lbl or "%s-axis" % f["axis"].currentText())
                if not lbl:
                    f["reverse"].setChecked(d.dot(AXES[f["axis"].currentIndex()][1]) < 0)
                f["spacing"].setValue(v.get("s" + n, 25.0))
                f["count"].setValue(v.get("n" + n, 2 if k == 0 else 1))
            for f, u in zip(self.fields, v.get("upto") or []):
                f["refgeo"] = (V(*u["point"]), V(*u["normal"]) if u.get("normal") else None) if u.get("point") else None
                _show(f["ref"], u.get("label", ""))
                f["offset"].setValue(u.get("offset", 0.0))
                f["off_rev"].setChecked(bool(u.get("rev")))
                f["seedgeo"] = V(*u["seed_point"]) if u.get("seed_point") else None
                _show(f["seed_ref"], u.get("seed_label", ""))
                f["seed_sel"].setChecked(u.get("seed") == "selected")
                (f["set_spacing"] if u.get("set", "spacing") == "spacing" else f["set_count"]).setChecked(True)
                f["upto"].setChecked(bool(u.get("on")))
                self._upto_shown(f)
            self.seed_only.setChecked(bool(v.get("seed_only")))
            self.skip.refresh()
            self.skip.set(v.get("skip", []))

        def accept(self):
            Gui.Selection.removeObserver(self)
            self._end_preview(keep_old=False)
            if self.comps:
                doc = self.asm.Document
                doc.openTransaction("Linear Component Pattern")
                try:
                    label = replace_old(self)
                    v = self.values()
                    d2 = V(*v["d2"]) if v["n2"] > 1 else None
                    build(self.asm, "linear", self.comps,
                          lambda seed: linear_instances(self.asm, seed, V(*v["d1"]), v["s1"], v["n1"], d2, v["s2"],
                                                        v["n2"], v["seed_only"]),
                          v, self.skip.skipped(), label)
                finally:
                    doc.commitTransaction()
                from . import asmtools
                asmtools._refresh()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            Gui.Selection.removeObserver(self)
            self._end_preview(keep_old=False)
            Gui.Control.closeDialog()
            return True

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _fold(box):
    ""
    try:
        from . import asmpm
        asmpm.fold(box)
    except Exception as _fw_err:
        _fw_log("asmcpattern.py:1096", _fw_err)


def _bbox_center(comps):
    ""
    from . import asmtools
    box = None
    for c in comps:
        try:
            b = asmtools._global_shape(c).BoundBox
        except Exception as _fw_err:
            _fw_log("asmcpattern.py:1108", _fw_err)
            continue
        if box is None:
            box = App.BoundBox(b)
        else:
            box.add(b)
    if box is None:
        from . import asmpattern
        return asmpattern.centroid(comps[0])
    return V(box.Center)


def _seed_point(shape):
    """A picked seed reference as a point: a vertex itself, a circle's centre, else its centre of mass."""
    try:
        if shape.ShapeType == "Vertex":
            return V(shape.Point)
        if shape.ShapeType == "Edge" and hasattr(shape.Curve, "Center"):
            return V(shape.Curve.Center)
        return V(shape.CenterOfMass)
    except Exception:
        return V(shape.BoundBox.Center)
