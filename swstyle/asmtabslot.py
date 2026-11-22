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

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import asmcore as ac
from . import smtabslot as ts

GROUP = "Tab and Slot"
V = App.Vector


def _baked(shape):
    from .smnormalcut import baked
    return baked(shape)


# ================================================================ geometry where the assembly shows it
def frame(comp):
    """Placement taking the component's part (body) coordinates to the assembly's."""
    from . import asmexplode as ax
    pl = ax.gplacement(comp)
    target = comp.getLinkedObject(True) if comp.TypeId == "App::Link" else comp
    if getattr(comp, "LinkTransform", False) and hasattr(target, "Placement"):
        pl = pl.multiply(target.Placement)
    return pl


def body_of(comp):
    target = comp.getLinkedObject(True) if comp is not None else None
    return target if target is not None and target.TypeId == "PartDesign::Body" else None


def _base_local(body):
    """The body's shape before this command's own features, in the body's coordinates."""
    src = _source(body)
    return _baked(src.Shape) if src is not None and not src.Shape.isNull() else None


def _source(obj):
    """A body's last feature before any Tab and Slot (this module's or smtabslot's)."""
    if obj is not None and obj.TypeId == "PartDesign::Body":
        obj = obj.Tip
    while obj is not None and (is_asm_tabslot(obj) or ts.is_tab_and_slot(obj) or ts.is_slots(obj)):
        obj = obj.BaseFeature
    return obj


def global_shape(comp):
    body = body_of(comp)
    local = _base_local(body) if body is not None else None
    if local is None:
        from . import asmtools
        return asmtools._global_shape(comp)
    s = local.copy()
    s.transformShape(frame(comp).toMatrix(), True)
    return s


def to_part(shape, comp):
    s = shape.copy()
    s.transformShape(frame(comp).inverse().toMatrix(), True)
    return s


def layouts(asm, groups, linked):
    """[(group, Layout, tab component, slot component)] in the assembly's coordinates."""
    out = []
    first = groups[0] if groups else None
    doc = asm.Document
    for g in groups:
        if not g.get("Edge") or not g.get("SlotFace"):
            continue
        values = dict(g)
        if linked and first is not None:
            values.update({k: first[k] for k in ts.DEFAULTS})
        tab, slot = doc.getObject(g["Edge"][0]), doc.getObject(g["SlotFace"][0])
        if tab is None or slot is None:
            raise ValueError("A component picked for the tabs or slots is no longer there.")
        tshape, sshape = global_shape(tab), global_shape(slot)
        edge = ts._find_edge(tshape, g["Edge"][2])
        sface = ts._find_face(sshape, g["SlotFace"][2])
        if sface is None:
            raise ValueError("The slot face is no longer there.")
        tface = ts._find_face(tshape, g["TabFace"][2]) if g.get("TabFace") else ts.tab_face(tshape, edge, sface.normalAt(0, 0))
        if tface is None:
            raise ValueError("No tab face on the edge: pick the tab face.")
        start = V(*g["Start"][2][0]) if g.get("Start") else None
        end = V(*g["End"][2][0]) if g.get("End") else None
        out.append((values, ts.Layout(tshape, sshape, edge, sface, tface, values, start, end), tab, slot))
    return out


# ================================================================ the features in the parts
class AsmTool:
    """A part feature: the part fused with its tabs (Mode "tabs") or cut by its slots (Mode "slots")."""

    def __init__(self, obj, mode):
        obj.addProperty("App::PropertyString", "Mode", GROUP, "tabs or slots")
        obj.addProperty("Part::PropertyPartShape", "Tool", GROUP, "The tabs or slots, in this part's coordinates")
        obj.addProperty("App::PropertyString", "Assembly", GROUP, "The assembly it was made in (file, assembly)")
        obj.addProperty("App::PropertyString", "Groups", GROUP, "The Tab and Slot's groups and settings (JSON)")
        obj.addProperty("App::PropertyBool", "LinkGroups", GROUP, "Link Groups Together")
        obj.addProperty("App::PropertyString", "Partner", GROUP, "The other features of this Tab and Slot (file:name)")
        for p in ("Mode", "Tool", "Assembly", "Groups", "Partner"):
            obj.setEditorMode(p, 2)
        obj.Mode = mode
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Tab and Slot: needs a part")
        shape = _baked(base.Shape)
        tool = obj.Tool
        if not tool.isNull() and tool.Solids:
            shape = shape.fuse(tool).removeSplitter() if obj.Mode == "tabs" else shape.cut(tool)
            if len(shape.Solids) == 1:
                shape = shape.Solids[0]
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_asm_tabslot(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "AsmTool"


class ViewProviderAsmTool(ts.ViewProviderTabAndSlot):
    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        edit_from_part(vobj.Object)
        return False

    def doubleClicked(self, vobj):
        edit_from_part(vobj.Object)
        return True

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        body = ts._body_of(obj)
        if body is not None:
            base = obj.BaseFeature
            if body.Tip is obj:
                body.Tip = base
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("asmtabslot.py:181", _fw_err)
        return True


def _say(text):
    try:
        from PySide import QtWidgets
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Tab and Slot", text)
    except Exception:
        App.Console.PrintMessage(text + "\n")


def edit_from_part(obj):
    """Edit Feature on an assembly Tab and Slot: the PropertyManager again, in its assembly."""
    try:
        path, name = json.loads(obj.Assembly or "[]")
    except Exception:
        path, name = "", ""
    doc = next((d for d in App.listDocuments().values() if d.FileName and path and
                d.FileName.replace("\\", "/") == path.replace("\\", "/")), None)
    asm = doc.getObject(name) if doc is not None else None
    if asm is None:
        _say("This Tab and Slot was made in an assembly (%s). Open the assembly to edit it." % (path or "?"))
        return False
    Gui.getDocument(doc.Name)
    try:
        Gui.activateDocument(doc.Name)
    except Exception as _fw_err:
        _fw_log("asmtabslot.py:209", _fw_err)
    App.setActiveDocument(doc.Name)
    return start(asm, existing=obj)


def _features(obj):
    """obj and its partners (the tab feature first)."""
    out = [obj]
    for text in (obj.Partner or "").split("|"):
        if not text:
            continue
        dname, _sep, oname = text.partition(":")
        d = App.listDocuments().get(dname)
        o = d.getObject(oname) if d is not None else None
        if o is not None and o not in out:
            out.append(o)
    return sorted(out, key=lambda o: o.Mode != "tabs")


def _add(body, mode, label):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "TabAndSlot" if mode == "tabs" else "Slots")
    AsmTool(obj, mode)
    if App.GuiUp:
        ViewProviderAsmTool(obj.ViewObject)
    body.addObject(obj)
    obj.Label = label
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("asmtabslot.py:241", _fw_err)
    return obj


def _remove(obj):
    body = ts._body_of(obj)
    doc = obj.Document
    if body is not None:
        base = obj.BaseFeature
        if body.Tip is obj:
            body.Tip = base
        body.removeObject(obj)
        try:
            base.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("asmtabslot.py:256", _fw_err)
    doc.removeObject(obj.Name)


def _next_label(doc):
    from . import naming
    return naming.next_label(doc, "Tab and Slot")


# ================================================================ the PropertyManager in the assembly
class Panel(ts.Panel):
    """smtabslot's PropertyManager, its picks on components and its features in their parts."""

    def __init__(self, asm, existing=None):
        self.asm = asm
        self.made = []          # features this session added (removed on Cancel)
        self.before = {}        # feature: (Tool, Groups, LinkGroups) before this session (put back on Cancel)
        self.features = _features(existing) if existing is not None else []
        if self.features:
            first = self.features[0]
            for f in self.features:
                self.before[f] = (f.Tool.copy(), f.Groups, f.LinkGroups)
        ts.Panel.__init__(self, None, True, asm.Document)
        if self.features:
            try:
                self.groups = json.loads(first.Groups) or [ts.new_group()]
            except Exception:
                self.groups = [ts.new_group()]
            self.linked = bool(first.LinkGroups)
            self.link.setChecked(self.linked)
            self._load()
            self._report()
            self._fill_skip()

    # picks: (assembly doc, assembly, "Component.Face3") -> the component and its element
    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("asmtabslot.py:295", _fw_err)
        doc = App.getDocument(doc_name)
        root = doc.getObject(name) if doc is not None else None
        if root is None or not sub:
            return
        ref = ac.reference(self.asm, root, sub) if root is self.asm else None
        if ref is None:
            return
        comp, element = ref
        element = element.split(".")[-1]
        shape = global_shape(comp)
        try:
            el = shape.getElement(element)
        except Exception:
            return
        if at is None:
            at = el.Point if element.startswith("Vertex") else el.CenterOfMass
        self.pick_error = ""
        grp = self.g()
        active = next((k for k, w in self.lists.items() if w is self.active), "Edge")
        kind = element.rstrip("0123456789")
        if kind == "Edge":
            edge = ts._nearest([e for e in shape.Edges if e.Curve.TypeId == "Part::GeomLine"], at)
            if edge is None:
                self.pick_error = "The tab edge must be a straight edge."
                self._report()
                return
            if body_of(comp) is None:
                self.pick_error = "The tabs go in a part made of a body: %s is not one." % comp.Label
                self._report()
                return
            a, b = ts._line_of(edge)
            grp["Edge"] = [comp.Name, element, [tuple(a), tuple(b)]]
            grp["TabFace"] = None
            self._auto_thickness(grp, comp, shape, edge)
            self.active = self.lists["SlotFace"] if not grp.get("SlotFace") else self.active
        elif kind == "Vertex":
            v = ts._nearest(shape.Vertexes, at)
            if v is None:
                return
            key = active if active in ("Start", "End") else ("Start" if not grp.get("Start") else "End")
            grp[key] = [comp.Name, element, [tuple(v.Point)]]
        elif kind == "Face":
            face = ts._nearest([f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane"], at)
            if face is None:
                self.pick_error = "Pick a flat face."
                self._report()
                return
            from .smnormalcut import inside_point
            entry = [comp.Name, element, [tuple(inside_point(face)), tuple(face.normalAt(0, 0))]]
            if active == "TabFace":
                grp["TabFace"] = entry
            else:
                if body_of(comp) is None:
                    self.pick_error = "The slots go in a part made of a body: %s is not one." % comp.Label
                    self._report()
                    return
                grp["SlotFace"] = entry
                if grp.get("Edge") and (not grp.get("TabFace") or grp["TabFace"][3:] == ["auto"]):
                    tab = self.doc.getObject(grp["Edge"][0])
                    tshape = global_shape(tab)
                    edge = ts._find_edge(tshape, grp["Edge"][2])
                    self._auto_thickness(grp, tab, tshape, edge, face.normalAt(0, 0))
        self._load()
        self._sync()

    def _label(self, name):
        o = self.doc.getObject(name)
        return o.Label if o is not None else name

    def _sync(self):
        doc = self.doc
        if doc.Recomputing:
            from PySide import QtCore
            QtCore.QTimer.singleShot(50, self._sync)
            return
        self.pick_error = self.pick_error if self.pick_error.startswith("The ") else ""
        try:
            lays = layouts(self.asm, self.groups, self.linked)
        except Exception as error:
            self.pick_error = str(error)
            self._report()
            return
        tabs, slots = {}, {}
        for g, lay, tab, slot in lays:
            tabs.setdefault(tab.Name, (tab, []))[1].extend(lay.tabs(g))
            slots.setdefault(slot.Name, (slot, []))[1].extend(lay.slots(g, global_shape(slot)))
        if len(tabs) > 1:
            self.pick_error = "The tabs must all be on one part."
            self._report()
            return
        want = {}                                  # body: (mode, tool in its coordinates)
        for comp, solids in tabs.values():
            want[body_of(comp)] = ("tabs", to_part(Part.Compound(solids), comp) if solids else Part.Shape())
        for comp, solids in slots.values():
            b = body_of(comp)
            if b in want:
                continue                           # slots in the tab part itself: smtabslot's own case
            want[b] = ("slots", to_part(Part.Compound(solids), comp) if solids else Part.Shape())
        have = {ts._body_of(f): f for f in self.features}
        label = next((f.Label.replace("-Slots", "") for f in self.features if f.Mode == "tabs"), None)
        for b, f in list(have.items()):
            if b not in want or f.Mode != want[b][0]:
                self.features.remove(f)
                if f in self.made:
                    self.made.remove(f)
                    _remove(f)
                else:
                    _remove(f)
        tab_body = next((b for b, (m, _t) in want.items() if m == "tabs"), None)
        if label is None and tab_body is not None:
            label = _next_label(tab_body.Document)
        for b, (mode, tool) in want.items():
            f = next((x for x in self.features if ts._body_of(x) is b), None)
            if f is None:
                f = _add(b, mode, label if mode == "tabs" else label + "-Slots")
                self.made.append(f)
                self.features.append(f)
            f.Tool = tool
        self.features.sort(key=lambda o: o.Mode != "tabs")
        partner = "|".join("%s:%s" % (f.Document.Name, f.Name) for f in self.features)
        path = (doc.FileName or doc.Name).replace("\\", "/")
        for f in self.features:
            f.Groups = json.dumps(self.groups)
            f.LinkGroups = self.linked
            f.Partner = partner
            f.Assembly = json.dumps([path, self.asm.Name])
            f.touch()
        for d in {f.Document for f in self.features}:
            d.recompute()
        doc.recompute()
        self._report()
        self._fill_skip()

    def _fill_skip(self):
        from PySide import QtCore, QtWidgets
        values = dict(self.g())
        if self.linked:
            values.update({k: self.groups[0][k] for k in ts.DEFAULTS})
        values["Skip"] = []
        total = 0
        try:
            for _v, lay, _t, _s in layouts(self.asm, [values], False):
                total = lay.total
        except Exception:
            total = 0
        skip = set(int(k) for k in self.g().get("Skip") or [])
        was, self.busy = self.busy, True
        try:
            self.skip.clear()
            for k in range(1, total + 1):
                item = QtWidgets.QListWidgetItem("Instance %d" % k)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if k in skip else QtCore.Qt.Unchecked)
                self.skip.addItem(item)
        finally:
            self.busy = was

    def _report(self):
        text = ""
        bad = next((o for o in getattr(self, "features", []) if "Invalid" in o.State), None)
        if bad is not None:
            text = bad.getStatusString()
        elif self.pick_error:
            text = self.pick_error
        elif not self.g().get("Edge") or not self.g().get("SlotFace"):
            text = ts.MESSAGE
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def accept(self):
        if not self._report():
            return False
        for f in self.features:
            try:
                f.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("asmtabslot.py:473", _fw_err)
        self.doc.commitTransaction()
        ts._close_transaction(False)
        self._close()
        return True

    def reject(self):
        for f in list(self.made):
            try:
                _remove(f)
            except Exception as _fw_err:
                _fw_log("asmtabslot.py:484", _fw_err)
        for f, (tool, groups, linked) in self.before.items():
            try:
                if f.Document is not None and f in f.Document.Objects:
                    f.Tool, f.Groups, f.LinkGroups = tool, groups, linked
                else:
                    pass
            except Exception as _fw_err:
                _fw_log("asmtabslot.py:492", _fw_err)
        docs = {self.doc} | {b.Document for b in [ts._body_of(f) for f in self.before] if b is not None}
        self.doc.abortTransaction()
        ts._close_transaction(True)
        for d in docs:
            try:
                d.recompute()
            except Exception as _fw_err:
                _fw_log("asmtabslot.py:500", _fw_err)
        self._close()
        return True


# ================================================================ the command
def _assembly():
    try:
        return ac.assembly_of(App.ActiveDocument)
    except Exception:
        return None


def can_start():
    asm = _assembly()
    if asm is None:
        return False
    try:
        if Gui.Control.activeDialog():
            return False
    except Exception:
        return False
    return any(body_of(c) is not None for c in ac.components(asm))


def start(asm=None, existing=None):
    asm = asm or _assembly()
    if asm is None:
        return None
    picked = []
    for o in Gui.Selection.getSelectionEx("", 0):
        for sub, p in zip(o.SubElementNames, o.PickedPoints or [None] * len(o.SubElementNames)):
            if sub.split(".")[-1].startswith(("Edge", "Face")):
                picked.append((o.Document.Name, o.Object.Name, sub, App.Vector(p) if p is not None else None))
    asm.Document.openTransaction(ts.TITLE)
    try:
        panel = Panel(asm, existing)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            asm.Document.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in sorted(picked, key=lambda p: not p[2].split(".")[-1].startswith("Edge"))[:2]:
        panel._picked(doc_name, name, sub, at)
    return panel


def install():
    """The Sheet Metal Tab and Slot command, in an assembly, runs this one (wrapped at run time)."""
    if getattr(ts.Command, "_fw_asm", False):
        return
    is_active, activated = ts.Command.IsActive, ts.Command.Activated

    def IsActive(self):
        return can_start() if _assembly() is not None else is_active(self)

    def Activated(self):
        if _assembly() is not None:
            return start()
        return activated(self)

    ts.Command.IsActive, ts.Command.Activated = IsActive, Activated
    ts.Command._fw_asm = True
