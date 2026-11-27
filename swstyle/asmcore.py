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

import FreeCAD as App

V = App.Vector

STANDARD = ("Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric", "Lock", "Distance", "Angle")
JOINT = {"Coincident": "Distance", "Distance": "Distance", "Tangent": "Distance",
         "Parallel": "Parallel", "Perpendicular": "Perpendicular", "Angle": "Angle",
         "Concentric": "Cylindrical", "Lock": "Fixed", "Gear": "Gears", "Hinge": "Revolute",
         "Rack Pinion": "RackPinion", "Screw": "Screw", "Profile Center": "Revolute",
         "Universal Joint": "Perpendicular"}
ADVANCED = ("Profile Center", "Symmetric", "Width", "Path Mate", "Linear/Linear Coupler", "Distance Range",
            "Angle Range")
SLOT_PROP = "FwSlot"         # Slot: the constraint and its value
VIRTUAL = ("Distance Range", "Angle Range", "Slot", "Path Mate", "Linear/Linear Coupler", "Cam", "InPlace")     # rows of their own; FreeCAD solves hidden joints for them
SYMMETRIC_PROP = "FwSymmetric"       # Symmetric: the first entity ("component element") and the sign used
LIMITS = ("Distance Range", "Angle Range")    # limits set on the joint that lets the two move
LIMIT_PROP = "FwLimit"               # Distance/Angle Range: host joint, min, max, zero offsets
LIMITED_PROP = "FwLimitedBy"         # on the host joint: the range mates that set its limits
WIDTH_PROP = "FwWidth"               # Width: the four picks ("component element") and the constraint
MECHANICAL = ("Cam", "Gear", "Hinge", "Rack Pinion", "Screw", "Universal Joint", "Slot")
COUPLED = ("Gear", "Rack Pinion", "Screw")      # they couple motion (only while a component is dragged)
NAMES = {"Gear": "GearMate", "Rack Pinion": "RackPinionMate", "Screw": "ScrewMate",
         "Profile Center": "ProfileCenter", "Distance Range": "LimitDistance",
         "Angle Range": "LimitAngle", "Universal Joint": "UniversalJoint", "Slot": "SlotMate", "Path Mate": "PathMate",
         "Linear/Linear Coupler": "LinearCoupler"}   # tree: GearMate1, Width1, LimitDistance1
FIXED_PREFIX, FLOAT_PREFIX, OVER_PREFIX = "(f) ", "(-) ", "(+) "
MATE_PROP = "FwMateType"
LOCK_PROP = "FwLockRotation"
REVERSE_PROP = "FwReverse"           # Gear: Reverse (the two turn the same way); Rack Pinion, Screw
VALUE_PROP = "FwMechValue"           # Rack Pinion: "diameter"/"travel"; Screw: "revs"/"distance";
                                     # Profile Center: "offset flip lock"
PART_OF_PROP = "FwPartOf"            # a hidden joint FreeCAD needs under a mate (the mate's Name)
ERROR_PROP = "FwMateError"
REDUNDANT_PROP = "FwRedundant"      # a Concentric that holds and agrees with the others but holds a freedom twice
MISALIGNED_PROP = "FwMisalignment"   # a misaligned Concentric: the offset between the axes (mm)
OVER_MESSAGE = ("This mate would over define the assembly. Consider satisfying this mate without "
                "over defining the assembly.")


def _ja():
    import JointObject
    return JointObject


# ----------------------------------------------------------------------------- the assembly
def assembly_of(doc=None):
    """The document's top assembly, else None (asked per tree row: kept until the event loop runs)."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        from . import tickcache, asmgen
        g = asmgen.gen(doc)         # the document's change count: cheaper than len(doc.Objects) per row
        key = ("assembly_of", doc.Name, g if g >= 0 else len(doc.Objects), g >= 0)
    except Exception:
        return _assembly_of(doc)
    found = tickcache.get(key, lambda: _assembly_of(doc))
    if found is not None:
        try:
            found.Name      # deleted since
        except Exception:
            tickcache.clear()
            return _assembly_of(doc)
    return found


def _assembly_of(doc):
    for obj in doc.RootObjects:
        if obj.TypeId == "Assembly::AssemblyObject":
            return obj
    # a drawing view (another document's link) takes the assembly out of RootObjects
    for obj in doc.Objects:
        if obj.TypeId == "Assembly::AssemblyObject" and not any(
                i.Document is doc and i.TypeId in ("Assembly::AssemblyObject", "Assembly::AssemblyLink")
                for i in obj.InList):
            return obj
    return None


def is_assembly(doc=None):
    return assembly_of(doc) is not None


def joint_group(asm):
    for obj in asm.Group:
        if obj.TypeId == "Assembly::JointGroup":
            return obj
    group = asm.newObject("Assembly::JointGroup", "Joints")
    group.Label = "Mates"
    return group


def make_assembly(doc):
    """FreeCAD's assembly in doc, with its Mates folder (FreeCAD's Joints group)."""
    asm = assembly_of(doc)
    if asm is None:
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        asm.Label = doc.Label
        joint_group(asm)
    return asm


PREVIEWS = set()        # (document, name) of the Insert Components preview following the pointer


_COMPS = {}     # (document, assembly) -> (change count, previews, components): kept till the document changes


def components(asm):
    ""


    try:
        from . import asmgen
        g = asmgen.gen(asm.Document)
        key = (asm.Document.Name, asm.Name)
    except Exception:
        g, key = -1, None
    if g >= 0:
        hit = _COMPS.get(key)
        pv = tuple(sorted(PREVIEWS)) if PREVIEWS else ()
        if hit is not None and hit[0] == g and hit[1] == pv:
            return list(hit[2])
    out = _components(asm)
    if g >= 0:
        _COMPS[key] = (g, tuple(sorted(PREVIEWS)) if PREVIEWS else (), list(out))
    return out


_MOVABLE = {}   # (document, assembly) -> (change count, [objects FreeCAD's solver may move])


def _movable(asm):
    """UtilsAssembly.getMovablePartsWithin, kept while the document's change count stays the same
    (a solve saved and restored them several times over; each walk of 300 links took ~7 ms)."""
    import UtilsAssembly
    try:
        from . import asmgen
        g = asmgen.gen(asm.Document)
        key = (asm.Document.Name, asm.Name)
    except Exception:
        g, key = -1, None
    if g >= 0:
        hit = _MOVABLE.get(key)
        if hit is not None and hit[0] == g:
            try:
                if all(o.isValid() for o in hit[1][:1]):
                    return hit[1]
            except Exception as _fw_err:
                _fw_log("asmcore.py:187", _fw_err)
    out = UtilsAssembly.getMovablePartsWithin(asm)
    if g >= 0:
        _MOVABLE[key] = (g, out)
    return out


def _save_placements(asm):
    """As UtilsAssembly.saveAssemblyPartsPlacements: {name: placement} of what the solver moves."""
    return {o.Name: o.Placement for o in _movable(asm)}


def _restore_placements(asm, saved):
    """As UtilsAssembly.restoreAssemblyPartsPlacements, setting only the ones that moved (each set
    placement wakes every observer)."""
    for o in _movable(asm):
        plc = saved.get(o.Name)
        if plc is not None and not o.Placement.isSame(plc, 1e-12):
            o.Placement = plc


def _components(asm):
    out = [o for o in asm.Group if o.TypeId in ("App::Link", "Assembly::AssemblyLink") or
           (o.isDerivedFrom("Part::Feature") and o.TypeId != "Assembly::JointGroup"
            and not o.isDerivedFrom("Part::Part2DObject")         # an assembly sketch is no component
            and getattr(o, "SWType", "") != "SWSketchCenterlines"      # nor its centerlines (sketchcenterlines)
            and getattr(getattr(o, "Proxy", None), "Type", "") != "FreeWorksCenterlines"   # (fwsketch centerlines)
            and not hasattr(o, "FwThreadOf"))]     # nor a fastener's thread marks (asmthread)
    if PREVIEWS:
        dn = asm.Document.Name
        out = [o for o in out if (dn, o.Name) not in PREVIEWS]
    return out


# ----------------------------------------------------------------------------- subassemblies
def is_subassembly(comp):
    """A component that is an assembly (FreeCAD's AssemblyLink)."""
    return getattr(comp, "TypeId", "") == "Assembly::AssemblyLink"


def is_flexible(comp):
    return is_subassembly(comp) and not bool(getattr(comp, "Rigid", True))


def set_flexible(asm, comp, flexible=True):
    ""

    if not is_subassembly(comp) or is_flexible(comp) == flexible:
        return False
    fixed = comp in grounded(asm)
    held = [j.Name for j in joint_group(asm).Group if getattr(j, FLEX_FIX_PROP, "") == comp.Name]
    comp.Rigid = not flexible
    asm.Document.recompute()
    _flexible_refs(asm, comp, flexible)
    if flexible and fixed and comp not in _own_grounds(asm):
        _mark_fixed_flexible(comp, True)
        _hold_flexible(asm, comp)
    elif not flexible and (held or getattr(comp, FIXED_FLEX_PROP, False)):
        _mark_fixed_flexible(comp, False)
        for name in held:
            if asm.Document.getObject(name) is not None:
                asm.Document.removeObject(name)
        if comp not in _own_grounds(asm):
            fix(asm, comp)
    target = getattr(comp, "LinkedObject", None)
    if target is not None and target.Document is asm.Document:
        # a virtual subassembly: its mates' copies and the mates on it sit in this document and
        # take their new placements at a recompute; the solve and the drag after it read them
        for j in mates(asm) + [c for g in (getattr(comp, "Group", []) or []) if g.TypeId == "Assembly::JointGroup"
                               for c in g.Group]:
            try:
                j.touch()
            except Exception as _fw_err:
                _fw_log("asmcore.py:260", _fw_err)
        asm.Document.recompute()
    solve(asm)
    if any(mate_error(j) for j in mates(asm)):
        # the first solve after Rigid changes starts from the subassembly's old placements and
        # can fail a mate that was in error only because the subassembly was rigid (a piston in
        # its bore on a rigid rod-and-piston): once recomputed it is tried again
        errs = [j for j in mates(asm) if mate_error(j) and getattr(j, "Suppressed", False)
                and not getattr(j, "FwUserSuppressed", False) and not is_misaligned(j) and satisfied(j)]
        asm.Document.recompute()
        for j in errs:
            j.Suppressed = False
            setattr(j, ERROR_PROP, False)
        if errs and not solve(asm):
            for j in errs:
                j.Suppressed = True
                setattr(j, ERROR_PROP, True)
            solve(asm)
    return True


FLEX_FIX_PROP = "FwFlexFixOf"       # on the grounded joints that hold a fixed flexible subassembly


FIXED_FLEX_PROP = "FwFixedFlexible"     # on a subassembly: fixed while it solves as flexible


def _mark_fixed_flexible(comp, on):
    try:
        if not hasattr(comp, FIXED_FLEX_PROP):
            if not on:
                return
            comp.addProperty("App::PropertyBool", FIXED_FLEX_PROP, "FreeCAD", "Fixed (solved as flexible)")
            comp.setEditorMode(FIXED_FLEX_PROP, 2)
        setattr(comp, FIXED_FLEX_PROP, bool(on))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: fixed flexible mark: %s\n" % error)


def _keep_flexible_holds(asm):
    """After an open (FreeCAD makes a flexible subassembly's components again, and a hold on one
    is lost): every fixed flexible subassembly held again."""
    live = {getattr(j, FLEX_FIX_PROP, ""): j for j in joint_group(asm).Group
            if getattr(j, FLEX_FIX_PROP, "") and getattr(j, "ObjectToGround", None) is not None}
    for comp in components(asm):
        if getattr(comp, FIXED_FLEX_PROP, False) and is_flexible(comp) and comp.Name not in live:
            for j in [j for j in joint_group(asm).Group if getattr(j, FLEX_FIX_PROP, "") == comp.Name]:
                asm.Document.removeObject(j.Name)
            _hold_flexible(asm, comp)


def _load_parts(asm):
    ""


    try:
        from . import saveas
        if saveas.open_mode(asm.Document) in ("Lightweight", "Large Design Review"):
            return
    except Exception:
        pass
    seen = set()
    for comp in components(asm):
        try:
            from . import asmextref
            d = asmextref._part_of(comp).Document
        except Exception:
            continue
        if d.Name in seen or d is asm.Document or not getattr(d, "Partial", False) or not d.FileName:
            continue
        seen.add(d.Name)
        try:
            if App.GuiUp:
                import FreeCADGui
                FreeCADGui.reload(d.Name)
            else:
                App.openDocument(d.FileName)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s not loaded fully: %s\n" % (d.Label, error))
    if seen and App.GuiUp:
        _front(asm.Document)


def _front(doc):
    ""

    try:
        import FreeCADGui
        from PySide import QtWidgets
        mdi = FreeCADGui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in (mdi.subWindowList() if mdi is not None else []):
            if sub.windowTitle().split(" : ")[0].rstrip("*") == doc.Label:
                mdi.setActiveSubWindow(sub)
                break
        App.setActiveDocument(doc.Name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: %s not brought to the front: %s\n" % (doc.Label, error))


def after_open(doc):
    """A file opened: its fixed flexible subassemblies held again (FreeCAD makes their components
    again on the first recompute, and the holds on them go); in-context references whose part
    changed while it was closed read it again (asmextref.refresh_stale)."""
    opened = _opened_file(doc)
    for asm in [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]:
        _load_parts(asm)
        try:
            from . import asmextref
            asmextref.refresh_stale(asm)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: in-context references on open: %s\n" % error)
        try:
            _refresh_mates(asm)
        except Exception as error:
            App.Console.PrintLog("mates on open: %s\n" % error)
        if not any(getattr(c, FIXED_FLEX_PROP, False) for c in components(asm)):
            continue
        try:
            doc.recompute()
            _keep_flexible_holds(asm)
            doc.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: fixed flexible subassembly on open: %s\n" % error)
    if opened:
        try:
            from . import asmui
            asmui.activate_opened(doc)
        except Exception as error:
            App.Console.PrintLog("assembly active on open: %s\n" % error)


def _opened_file(doc):
    """The document is a file just opened (saved, nothing changed yet), not one a script or command
    made and saved (FreeCAD 1.1 tells Python observers neither apart)."""
    if not App.GuiUp or not doc.FileName:
        return False
    try:
        import FreeCADGui
        return not FreeCADGui.getDocument(doc.Name).Modified
    except Exception:
        return False


def _refresh_mates(asm):
    ""


    changed = False
    for j in joint_group(asm).Group:
        proxy = getattr(j, "Proxy", None)
        if proxy is None or not hasattr(proxy, "findPlacement") or not hasattr(j, "Reference1"):
            continue
        for n, ref in ((0, "Reference1"), (1, "Reference2")):
            if getattr(j, "Detach%d" % (n + 1), False) or not getattr(j, ref, None):
                continue
            try:
                plc = proxy.findPlacement(j, getattr(j, ref), n)
            except Exception:
                continue
            old = getattr(j, "Placement%d" % (n + 1))
            if not plc.isSame(old, 1e-7):
                setattr(j, "Placement%d" % (n + 1), plc)
                changed = True
    if changed:
        asm.solve()
        asm.Document.recompute()
    return changed


def _own_grounds(asm):
    return {j.ObjectToGround: j for j in joint_group(asm).Group
            if getattr(j, "ObjectToGround", None) is not None and not getattr(j, FLEX_FIX_PROP, "")}


def _hold_flexible(asm, comp):
    ""


    src = getattr(comp, "LinkedObject", None)
    mine = sub_components(comp)
    if src is None or not mine:
        return []
    held = list(grounded(src))
    want = [o for o in mine if getattr(o, "LinkedObject", None) in held] or mine[:1]
    out = []
    for o in want:
        try:
            joint = joint_group(asm).newObject("App::FeaturePython", "Fixed")
            _ja().GroundedJoint(joint, o)
            joint.Label = "Fixed (%s)" % comp.Label
            joint.addProperty("App::PropertyString", FLEX_FIX_PROP, "FreeCAD", "Holds this fixed flexible subassembly")
            setattr(joint, FLEX_FIX_PROP, comp.Name)
            joint.setEditorMode(FLEX_FIX_PROP, 2)
            if App.GuiUp:
                _ja().ViewProviderGroundedJoint(joint.ViewObject)
                _quiet(joint, tree=False)
            out.append(joint)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: fixed flexible subassembly: %s\n" % error)
    return out


def sub_components(comp):
    """A subassembly's components (its own links, as this assembly holds them)."""
    return [o for o in getattr(comp, "Group", []) or [] if o.TypeId in ("App::Link", "Assembly::AssemblyLink")
            or (o.isDerivedFrom("Part::Feature") and o.TypeId != "Assembly::JointGroup")]


def source_label(obj):
    """The label a subassembly's component has in the subassembly ("Pin<1>"), not FreeCAD's
    copy in this document ("Pin<1>001"): the same part, in the same order."""
    try:
        target = obj.LinkedObject
        for holder in [p for p in obj.InList if is_subassembly(p)]:
            if target in components(holder.LinkedObject):
                if target.Document is obj.Document:
                    # a virtual subassembly: its components share this document's labels

                    import re
                    return re.sub(r"(<\d+>)\d{3}$", r"\1", target.Label)
                return target.Label          # FreeCAD's copy links the subassembly's own component
        for holder in [p for p in obj.InList if is_subassembly(p)]:
            mine = [o for o in sub_components(holder) if getattr(o, "LinkedObject", None) is target]
            theirs = [c for c in components(holder.LinkedObject) if getattr(c, "LinkedObject", None) is target]
            if obj in mine and theirs:
                return theirs[min(mine.index(obj), len(theirs) - 1)].Label
    except Exception as _fw_err:
        _fw_log("asmcore.py:383", _fw_err)
    return obj.Label


def part_name(obj):
    """The part's name a component is named after: its document's label for a part's body."""
    if obj.TypeId == "App::Link":
        target = obj.getLinkedObject(True)
        if getattr(obj, "LinkCopyOnChange", "Disabled") != "Disabled" and getattr(obj, "LinkCopyOnChangeSource", None) is not None:
            target = obj.LinkCopyOnChangeSource.getLinkedObject(True)   # an instance in its own configuration
    elif is_subassembly(obj) and getattr(obj, "LinkedObject", None) is not None:
        target = obj.LinkedObject           # a subassembly: its assembly document's name
    else:
        target = obj
    doc = target.Document
    if doc is not None and doc is not obj.Document:     # a part from its own file: the file's name
        return doc.Label                                # (whichever window is active)
    return target.Label


def _instance(asm, name):
    taken = {c.Label for c in components(asm)}
    n = 1
    while "%s<%d>" % (name, n) in taken:
        n += 1
    return "%s<%d>" % (name, n)


def part_object(doc):
    """What a part document gives to an assembly: its only body, else its first solid."""
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if bodies:
        tips = [b for b in bodies if not b.Shape.isNull()]
        return (tips or bodies)[0]
    # its own top objects: a part already linked into an assembly has that link in its InList,
    # so FreeCAD's RootObjects no longer lists it
    roots = [o for o in doc.Objects if not [p for p in o.InList if p.Document is doc]]
    parts = [o for o in roots if o.TypeId in ("App::Part", "Assembly::AssemblyObject")]
    if parts:
        return parts[0]
    solids = [o for o in roots if o.isDerivedFrom("Part::Feature") and not o.Shape.isNull()]
    return solids[0] if solids else None


def insert(asm, target, placement=None):
    """Adds a component linking target (a body or part, often in another document). The first
    one is fixed at the origin."""
    try:
        from . import asmgen
        asmgen.hold(asm.Document)       # a batch of inserts: the tree repaints once they stop
    except Exception as _fw_err:
        _fw_log("asmcore.py:434", _fw_err)
    first = not components(asm)
    if getattr(target, "FwAsmCutBody", None) is not None:
        target = target.FwAsmCutBody        # a cut component's copy starts from its own part
    sub = target.TypeId == "Assembly::AssemblyObject"
    link = asm.newObject("Assembly::AssemblyLink" if sub else "App::Link", "Component")
    link.LinkedObject = target
    link.Label = _instance(asm, part_name(link))
    if placement is not None and not first:
        link.Placement = placement
    if sub:
        link.Rigid = True
    if first:
        fix(asm, link)
        asm.Document.recompute()
        return link
    # one more free component changes nothing for the solver: build only the new link, so a run
    # of inserts does not rebuild the whole assembly (and its status bar) once per component
    was = "Touched" in asm.State
    link.recompute()
    try:
        link.purgeTouched()
        if not was:
            asm.purgeTouched()
    except Exception:
        asm.Document.recompute()
    return link


_GROUNDED = {}


def grounded(asm):
    """{component: grounded joint}. Kept while the document is unchanged (each tree row's
    prefix asked it: 300 components read every joint 300 times)."""
    from . import asmgen
    g = asmgen.gen(asm.Document)
    key = (asm.Document.Name, asm.Name)
    kept = _GROUNDED.get(key)
    if kept is not None and kept[0] == g and g >= 0:
        try:
            if all(c.isValid() and j.isValid() for c, j in kept[1].items()):
                return dict(kept[1])
        except Exception as _fw_err:
            _fw_log("asmcore.py:478", _fw_err)
    out = _grounded(asm)
    _GROUNDED[key] = (g, out)
    return dict(out)


def _grounded(asm):
    out = {}
    doc = asm.Document
    for j in joint_group(asm).Group:
        if hasattr(j, "ObjectToGround") and j.ObjectToGround is not None:
            out[j.ObjectToGround] = j
            sub = getattr(j, FLEX_FIX_PROP, "")
            if sub and doc.getObject(sub) is not None:
                out.setdefault(doc.getObject(sub), j)     # a fixed flexible subassembly is fixed too
    return out


def fix(asm, comp):
    if comp in grounded(asm):
        return grounded(asm)[comp]
    group = joint_group(asm)
    joint = group.newObject("App::FeaturePython", "Fixed")
    _ja().GroundedJoint(joint, comp)
    joint.Label = "Fixed (%s)" % comp.Label
    if App.GuiUp:
        _ja().ViewProviderGroundedJoint(joint.ViewObject)
        _quiet(joint, tree=False)
    return joint


def _quiet(joint, tree=True):
    ""


    if not App.GuiUp:
        return
    try:
        vobj = joint.ViewObject
        if not tree:
            vobj.Visibility = False
            vobj.ShowInTree = False
            return
        mode = getattr(vobj.Proxy, "display_mode", None)
        if mode is not None and mode.getNumChildren():
            mode.removeAllChildren()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: joint look: %s\n" % error)


def quiet_all(asm):
    for joint in joint_group(asm).Group:
        _quiet(joint, tree=not hasattr(joint, "ObjectToGround"))
    for comp in asm.Group:      # a flexible subassembly: FreeCAD's copies of its mates show their frames too,
        if comp.TypeId != "Assembly::AssemblyLink" or getattr(comp, "Rigid", True):     # and a drag picked them
            continue
        for g in getattr(comp, "Group", []) or []:
            if g.TypeId == "Assembly::JointGroup":
                for joint in g.Group:
                    _quiet(joint)
    if App.GuiUp:
        for o in asm.Group:
            if o.TypeId == "Assembly::ViewGroup" and o.ViewObject is not None:      # ConfigurationManager only
                try:
                    if o.ViewObject.ShowInTree:
                        o.ViewObject.ShowInTree = False
                except Exception as _fw_err:
                    _fw_log("asmcore.py:538", _fw_err)


class temp_ground:
    ""



    def __init__(self, asm, comps):
        self.asm, self.comps, self.joints = asm, [c for c in comps if c is not None], []

    def __enter__(self):
        have = grounded(self.asm)
        for comp in self.comps:
            if comp in have:
                continue
            try:
                joint = joint_group(self.asm).newObject("App::FeaturePython", "FwHold")
                _ja().GroundedJoint(joint, comp)
                if App.GuiUp:
                    _ja().ViewProviderGroundedJoint(joint.ViewObject)
                    _quiet(joint, tree=False)
                self.joints.append(joint)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: hold %s: %s\n" % (comp.Label, error))
        return self

    def __exit__(self, *exc):
        doc = self.asm.Document
        for joint in self.joints:
            try:
                doc.removeObject(joint.Name)
            except Exception as _fw_err:
                _fw_log("asmcore.py:571", _fw_err)
        self.joints = []
        return False


REF_HOLD = "FwRefHold"
TANGENT_FRAME = "FwTangentFrame"   # asmpkg350: a Tangent to an origin plane sets the round face's frame


def _from_assembly(asm, ref):
    try:
        obj = ref[0]
        if obj is not None and obj.TypeId in ("App::Plane", "App::Line", "App::Point") and not ref[1]:
            # asmpkg350: the assembly's Top Plane object itself is named through its Origin, as a pick in
            # the view names it: FreeCAD's solver takes a plane object as a part of its own (held apart from
            # the Origin, it moved the plane, and later mates on the Origin's other planes failed)
            org = next((p for p in obj.InList if p.isDerivedFrom("App::Origin")), None)
            if org is not None:
                return org, obj.Name + "."
        if ref[0] is asm and isinstance(ref[1], str) and ref[1]:
            got = reference(asm, asm, ref[1])
            if got is not None:
                return got[0], got[1]
    except Exception as _fw_err:
        _fw_log("asmcore.py:from-assembly", _fw_err)
    return ref


def _datum_plane(comp, sub):
    """('plane', point, normal) in the assembly for an origin plane (Top/Front/Right, the assembly's or a
    component's: FreeCAD's App::Plane has no shape, so a pick there gives no element), else None."""
    try:
        sub = sub if isinstance(sub, str) else ""
        # placed as element() places a shape: the component's own placement in, the assembly's out (a
        # component of a flexible subassembly: through the subassembly)
        parent = _kid_parent(comp) if comp.TypeId == "App::Link" and sub else None
        root, path = (parent, "%s.%s" % (comp.Name, sub)) if parent is not None else (comp, sub)
        obj = root.getSubObject(path, 1) if path else comp
        if obj is None or obj.TypeId != "App::Plane":
            return None
        g = App.Placement(root.getSubObject(path, 4)) if path else App.Placement(comp.Placement)
        return ("plane", V(g.Base), g.Rotation.multVec(V(0, 0, 1)))
    except Exception:
        return None


def _ref_geometry(comp, sub):
    g = geometry(element(comp, sub))
    return g if g is not None else _datum_plane(comp, sub)


def _tangent_datum(joint):
    ""




    import UtilsAssembly
    try:
        refs = [(joint.Reference1, 1), (joint.Reference2, 2)]
        plane = next(((r, i) for r, i in refs if _datum_plane(r[0], r[1][0]) is not None), None)
        if plane is None:
            return False
        rnd, k = next((r, i) for r, i in refs if i != plane[1])
        g = geometry(element(rnd[0], rnd[1][0]))
        if g is None or g[0] != "axis" or len(g) < 4 or g[3] <= 0:
            return False
        _, p, n = _datum_plane(plane[0][0], plane[0][1][0])
        a = V(g[2]).normalize()
        d = n - a * n.dot(a)
        if d.Length < 1e-9:             # the axis stands on the plane: lay it down the nearest way
            d = a.cross(V(1, 0, 0)) if abs(a.x) < 0.9 else a.cross(V(0, 1, 0))
        d.normalize()
        if d.dot(n) < 0:
            d = d * -1
        own = UtilsAssembly.getJcsGlobalPlc(UtilsAssembly.findPlacement(rnd, True), rnd)   # without the offset
        on = V(g[1]) + a * a.dot(own.Base - V(g[1]))     # the frame's point on the axis
        side = -1.0 if n.dot(on - p) < 0 else 1.0
        want = App.Placement(on - d * (side * g[3]), App.Rotation(V(0, 0, 1), d))
        JO = _ja()
        saved = getattr(JO, "solveIfAllowed", None)
        if saved is not None:
            JO.solveIfAllowed = lambda *a, **k: None    # an Offset change solves at once: the caller solves
        try:
            setattr(joint, "Offset%d" % k, own.inverse().multiply(want))
            if TANGENT_FRAME not in joint.PropertiesList:
                joint.addProperty("App::PropertyBool", TANGENT_FRAME, "FreeCAD", "Tangent to an origin plane: its own frame")
                joint.setPropertyStatus(TANGENT_FRAME, "Hidden")
            setattr(joint, TANGENT_FRAME, True)
        finally:
            if saved is not None:
                JO.solveIfAllowed = saved
        joint.Proxy.updateJCSPlacements(joint)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tangent to an origin plane: %s\n" % error)
        return False


def hold_reference(asm, obj):
    ""


    try:
        if obj is None or obj in components(asm) or obj in grounded(asm):
            return None
        if obj.TypeId in ("App::Link", "Assembly::AssemblyLink", "Assembly::AssemblyObject"):
            return None
        # asmpkg349: the assembly's own reference geometry too (its Top/Front/Right planes, axes and origin

        # every day, and FreeCAD's solver moved the reference instead of the component (nothing happened)
        if not (obj.isDerivedFrom("Part::Part2DObject") or obj.isDerivedFrom("Part::Feature")
                or obj.isDerivedFrom("App::Origin") or obj.isDerivedFrom("App::DatumElement")
                or obj.isDerivedFrom("Part::Datum") or obj.isDerivedFrom("App::OriginFeature")):
            return None
        joint = joint_group(asm).newObject("App::FeaturePython", REF_HOLD)
        _ja().GroundedJoint(joint, obj)
        joint.Label = REF_HOLD
        if App.GuiUp:
            _ja().ViewProviderGroundedJoint(joint.ViewObject)
            _quiet(joint, tree=False)
        return joint
    except Exception as error:
        App.Console.PrintLog("FreeCAD: hold reference %s: %s\n" % (getattr(obj, "Label", obj), error))
        return None


def float_(asm, comp):
    joint = grounded(asm).get(comp)
    if joint is not None:
        asm.Document.removeObject(joint.Name)


# ----------------------------------------------------------------------------- picks
def reference(asm, root, sub):
    """(component, element path inside it) for a pick in the assembly document, else None."""
    import UtilsAssembly
    try:
        resolved = root.resolveSubElement(sub, True)
        sub = resolved[2] or sub
    except Exception as _fw_err:
        _fw_log("asmcore.py:616", _fw_err)
    try:
        sub = UtilsAssembly.fixBodyExtraFeatureInSub(root.Document.Name, sub)
    except Exception as _fw_err:
        _fw_log("asmcore.py:620", _fw_err)
    comp, new_sub = UtilsAssembly.getComponentReference(asm, root, sub)
    if not comp:
        return None
    return comp, new_sub


def _flexible_refs(asm, comp, flexible):
    """FreeCAD's solver moves the part a mate names: a mate on a flexible subassembly's component
    names that component (FreeCAD's copy of it in the subassembly, as a pick in the view does),
    a mate on a rigid one names the subassembly and the component in it."""
    kids = {g.Name: g for g in (getattr(comp, "Group", []) or []) if g.TypeId == "App::Link"}
    if not kids:
        return
    for j in mates(asm):
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            if not ref or not ref[1]:
                continue
            obj, subs = ref[0], list(ref[1])
            if flexible and obj is comp and subs[0].split(".")[0] in kids:
                kid = kids[subs[0].split(".")[0]]
                new = (kid, [x.split(".", 1)[1] if x.split(".")[0] == kid.Name else x for x in subs])
            elif not flexible and obj in kids.values():
                new = (comp, ["%s.%s" % (obj.Name, x) for x in subs])
            else:
                continue
            try:
                setattr(j, prop, new)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: flexible subassembly, mate %s: %s\n" % (j.Label, error))
    _KID_OF.clear()


_KID_OF = {}        # (document, component) -> the subassembly it is FreeCAD's copy in, or None


def _kid_parent(comp):
    key = (comp.Document.Name, comp.Name)
    if key not in _KID_OF:
        _KID_OF[key] = next((p.Name for p in comp.InList if p.TypeId == "Assembly::AssemblyLink"
                             and comp in (getattr(p, "Group", []) or [])), None)
    name = _KID_OF[key]
    return comp.Document.getObject(name) if name else None


def element(comp, sub):
    """The picked element's shape, placed in the assembly (a component of a flexible
    subassembly: placed through the subassembly)."""
    try:
        parent = _kid_parent(comp) if comp.TypeId == "App::Link" else None
        shape = parent.getSubObject("%s.%s" % (comp.Name, sub)) if parent is not None else comp.getSubObject(sub)
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        return _datum_face(comp, sub)
    return shape


def _datum_face(comp, sub):
    ""


    g = _datum_plane(comp, sub)
    if g is None:
        return None
    try:
        import Part
        face = Part.makePlane(100, 100, V(-50, -50, 0))
        face.Placement = App.Placement(g[1], App.Rotation(V(0, 0, 1), g[2]))
        return face
    except Exception:
        return None


_GEOM = {}      # (shape hash, orientation, type, placement) -> geometry(shape)


def geometry(shape):
    """What a mate sees of an element: ('plane', point, normal), ('axis', point, direction,
    radius), ('line', point, direction), ('point', point), or None. Kept per placed shape: the
    centre of a big face (a plate with a hundred holes) took most of a mate check."""
    if shape is None:
        return None
    try:
        # the hash names the shape's memory, which a later shape can reuse: its box goes in too,
        # or a mate could be checked on another element's geometry (a hinge "not holding")
        bb = shape.BoundBox
        key = (shape.hashCode(), shape.Orientation, shape.ShapeType, tuple(shape.Placement.toMatrix().A),
               round(bb.XMin, 9), round(bb.YMin, 9), round(bb.ZMin, 9), round(bb.XMax, 9), round(bb.YMax, 9), round(bb.ZMax, 9))
    except Exception:
        key = None
    if key is not None:
        hit = _GEOM.get(key)
        if hit is not None:
            return _fresh(hit[0])
    out = _geometry(shape)
    if key is not None:
        if len(_GEOM) > 20000:
            _GEOM.clear()
        _GEOM[key] = (_fresh(out),)
    return out


def _fresh(g):
    """A copy of a geometry answer (its vectors are the caller's to change)."""
    if g is None:
        return None
    return tuple(V(x) if isinstance(x, App.Vector) else x for x in g)


def _geometry(shape):
    if shape is None:
        return None
    kind = shape.ShapeType
    if kind == "Face":
        s = shape.Surface
        t = s.TypeId
        if t == "Part::GeomPlane":
            u, v = s.parameter(shape.CenterOfMass)
            return ("plane", shape.CenterOfMass, shape.normalAt(u, v))
        if t in ("Part::GeomCylinder", "Part::GeomCone"):
            return ("axis", V(s.Center) if t == "Part::GeomCylinder" else V(s.Apex), V(s.Axis),
                    getattr(s, "Radius", 0.0))
        if t == "Part::GeomSphere":
            return ("point", V(s.Center))
        try:
            u, v = s.parameter(shape.CenterOfMass)
            return ("plane", shape.CenterOfMass, shape.normalAt(u, v))
        except Exception:
            return None
    if kind == "Edge":
        c = shape.Curve
        if c.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
            return ("axis", V(c.Center), V(c.Axis), c.Radius)
        if c.TypeId in ("Part::GeomLine", "Part::GeomLineSegment"):
            p = shape.Vertexes[0].Point
            d = shape.Vertexes[-1].Point - p
            return ("line", p, d.normalize() if d.Length > 1e-12 else V(0, 0, 1))
        return None
    if kind == "Vertex":
        return ("point", shape.Point)
    return None


def allowed(s1, s2, refs=None):
    ""

    out = _allowed(s1, s2)
    if s1 is not None and s2 is not None and sorted((s1.ShapeType, s2.ShapeType)) == ["Edge", "Vertex"]:
        out = out + ("Path Mate",)      # a vertex on a path
    g1, g2 = geometry(s1), geometry(s2)
    if g1 is not None and g2 is not None and g1[0] in ("line", "axis") and g2[0] in ("line", "axis"):
        out = out + ("Linear/Linear Coupler",)      # two directions to travel along
    if s1 is not None and s2 is not None:
        from . import asmcam
        if any(asmcam.is_cam_shape(a) and asmcam.follower_shape(b) for a, b in ((s1, s2), (s2, s1))):
            out = out + ("Cam",)        # a cam's curved face and a follower
    if refs is not None and len(refs) == 2:
        try:
            if slot_refs(list(refs)) is not None:
                out = out + ("Slot",)
        except Exception as _fw_err:
            _fw_log("asmcore.py:767", _fw_err)
    return out


def _allowed(s1, s2):
    g1, g2 = geometry(s1), geometry(s2)
    if g1 is None or g2 is None:
        return ("Coincident", "Lock")
    k = sorted((_kind(s1, g1), _kind(s2, g2)))
    table = {
        ("plane", "plane"): ("Coincident", "Parallel", "Perpendicular", "Lock", "Distance", "Angle"),
        ("cylinder", "plane"): ("Tangent", "Parallel", "Perpendicular", "Lock", "Distance"),
        ("cylinder", "cylinder"): ("Concentric", "Parallel", "Perpendicular", "Tangent", "Lock", "Distance",
                                   "Angle"),
        ("circle", "circle"): ("Coincident", "Concentric", "Parallel", "Perpendicular", "Lock", "Distance"),
        ("circle", "cylinder"): ("Concentric", "Lock"),
        ("circle", "plane"): ("Coincident", "Parallel", "Perpendicular", "Lock", "Distance"),
        ("line", "plane"): ("Coincident", "Parallel", "Perpendicular", "Lock", "Distance", "Angle"),
        ("line", "line"): ("Coincident", "Parallel", "Perpendicular", "Lock", "Distance", "Angle"),
        ("cylinder", "line"): ("Coincident", "Concentric", "Parallel", "Perpendicular", "Lock", "Distance"),
        ("plane", "point"): ("Coincident", "Lock", "Distance"),
        ("line", "point"): ("Coincident", "Lock", "Distance"),
        ("cylinder", "point"): ("Coincident", "Concentric", "Lock", "Distance"),
        ("circle", "point"): ("Coincident", "Concentric", "Lock", "Distance"),
        ("point", "point"): ("Coincident", "Lock", "Distance"),
    }
    out = table.get(tuple(k), ("Coincident", "Lock"))
    if k[0] in ("circle", "cylinder") and k[1] in ("circle", "cylinder"):
        out = out + ("Hinge", "Gear", "Screw", "Universal Joint")   # Mechanical Mates: round faces or edges
    elif "line" in k and k[0] in ("circle", "cylinder", "line") and k[1] in ("circle", "cylinder", "line") \
            and k != ["line", "line"]:
        out = out + ("Rack Pinion",)        # the rack's linear edge and the pinion's round face or edge
    if k == ["plane", "plane"]:
        if g1[2].cross(g2[2]).Length < 1e-6:
            out = out + ("Distance Range",)     # parallel flat faces: a distance between them
        out = out + ("Angle Range",)
    p1, p2 = profile(s1), profile(s2)
    if p1 is not None and p2 is not None and p1[0] == p2[0]:
        out = out + ("Profile Center",)     # two circles or two rectangles (edges or flat faces)
    return out


def profile(shape):
    ""


    if shape is None:
        return None
    if shape.ShapeType == "Edge":
        g = geometry(shape)
        return ("circle", g[1], g[2]) if g is not None and g[0] == "axis" else None
    if shape.ShapeType != "Face" or shape.Surface.TypeId != "Part::GeomPlane":
        return None
    g = geometry(shape)
    edges = shape.OuterWire.Edges
    if len(edges) == 1 and edges[0].Curve.TypeId == "Part::GeomCircle":
        return ("circle", V(edges[0].Curve.Center), g[2])
    if len(edges) == 4 and all(e.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment") for e in edges):
        dirs = [(e.Vertexes[-1].Point - e.Vertexes[0].Point) for e in edges]
        if all(d.Length > 1e-9 for d in dirs) and \
                all(abs(dirs[i].normalize().dot(dirs[(i + 1) % 4].normalize())) < 1e-6 for i in range(4)):
            longest = max(dirs, key=lambda d: d.Length)
            return ("rect", shape.CenterOfMass, g[2], V(longest).normalize())
    return None


def _kind(shape, g):
    if g[0] == "axis":
        return "cylinder" if shape.ShapeType == "Face" else "circle"
    return g[0]


def first_choice(s1, s2):
    ""

    options = allowed(s1, s2)
    for kind in ("Concentric", "Tangent", "Coincident"):
        if kind in options:
            if kind == "Concentric" and _kind(s1, geometry(s1)) == "circle" and _kind(s2, geometry(s2)) == "circle":
                continue
            return kind
    return options[0]


# ----------------------------------------------------------------------------- mates
def _next_mate_name(asm, kind):
    taken = {j.Label.split(" (")[0] for j in joint_group(asm).Group}
    taken |= {o.Label for o in asm.Document.Objects if o.Label.startswith(NAMES.get(kind, kind))}
    stem = NAMES.get(kind, kind)
    n = 1
    while "%s%d" % (stem, n) in taken:
        n += 1
    return "%s%d" % (stem, n)


def mates(asm):
    """The assembly's mates (not the fixed components' ground joints)."""
    return [j for j in joint_group(asm).Group if (hasattr(j, "JointType") and hasattr(j, "Reference1")
            and not getattr(j, PART_OF_PROP, "")) or getattr(j, MATE_PROP, "") in VIRTUAL]


def mate_type(joint):
    kind = getattr(joint, MATE_PROP, "")
    if kind:
        return kind
    jt = getattr(joint, "JointType", "")
    return {"Fixed": "Lock", "Cylindrical": "Concentric", "Slider": "Concentric", "Gears": "Gear", "Belt": "Gear", "Revolute": "Hinge",
            "RackPinion": "Rack Pinion",
            "Distance": "Distance" if abs(getattr(joint, "Distance", 0)) > 1e-9 else "Coincident"}.get(jt, jt)


def mate_text(joint):
    """The tree's text for a mate: "Coincident1 (Plate<1>,Pin<1>)"."""
    names = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if ref and ref[0] is not None:
            names.append(ref[0].Label)
    base = joint.Label.split(" (")[0]
    return "%s (%s)" % (base, ",".join(names)) if names else base


def joint_type(kind, lock_rotation=False, reverse=False):
    if kind == "Concentric" and lock_rotation:
        return "Slider"
    if kind == "Gear" and reverse:
        return "Belt"       # FreeCAD's Belt: the two turn the same way
    return JOINT[kind]


def _straight_edges(*refs):
    ""
    try:
        for c, sub in refs:
            e = element(c, sub if isinstance(sub, str) else (sub or [""])[0])
            if e is None or e.ShapeType != "Edge" or e.Curve.TypeId not in ("Part::GeomLine", "Part::GeomLineSegment"):
                return False
        return len(refs) == 2
    except Exception:
        return False


def _coincident_type(kind, want, ref1, ref2):
    # FreeCAD's Distance 0 between two lines only turns them parallel; its Cylindrical joint on two
    # straight edges (each edge's Z along the line) puts one on the other's line, free to slide
    return "Cylindrical" if kind == "Coincident" and want == "Distance" and _straight_edges(ref1, ref2) else want


def _reverse(kind, value):
    return kind in ("Gear", "Rack Pinion", "Screw") and bool(value) and len(value) > 2 and bool(value[2])


def pinion_diameter(s1, s2):
    ""
    for s in (s1, s2):
        g = geometry(s)
        if g is not None and g[0] == "axis" and len(g) > 3 and g[3] > 0:
            return 2.0 * g[3]
    return 10.0


def gear_diameters(s1, s2):
    ""
    out = []
    for s in (s1, s2):
        g = geometry(s)
        out.append(2.0 * g[3] if g is not None and g[0] == "axis" and len(g) > 3 and g[3] > 0 else 1.0)
    return tuple(out)


def _joint_proxy(JO, joint, type_index):
    """FreeCAD's Joint proxy on joint. Its __init__ sets empty references, which calls the assembly's
    undoSolve; that reads the components of the last solve and crashes FreeCAD when one of them was
    deleted since (delete a mated component, then add a mate). Empty references need no undoSolve:
    that call is skipped while the proxy is made."""
    saved = JO.Joint.setJointConnectors

    def connect(self, j, refs):
        if refs:
            return saved(self, j, refs)
        return None
    JO.Joint.setJointConnectors = connect
    try:
        return JO.Joint(joint, type_index)
    finally:
        JO.Joint.setJointConnectors = saved


class _no_creation_solve:
    """FreeCAD's "SolveInJointCreation" off for a moment (add_mate solves right after)."""
    PATH = "User parameter:BaseApp/Preferences/Mod/Assembly"

    def __enter__(self):
        self.p = App.ParamGet(self.PATH)
        self.was = self.p.GetBool("SolveInJointCreation", True)
        self.p.SetBool("SolveInJointCreation", False)

    def __exit__(self, *a):
        self.p.SetBool("SolveInJointCreation", self.was)
        return False


def add_mate(asm, kind, ref1, ref2, value=None, lock_rotation=False, flip=False, name=None, side=None, ball=False,
             offsets=None):
    """Makes the mate; ref = (component, element). value is the distance (mm) or angle (deg).
    side: a Distance's side (+1/-1) taken over from a mate it re-makes; None measures it.
    ball: a Coincident of two points one of which is a straight edge's middle (Select Midpoint):
    FreeCAD's Ball joint, the two joint frames' origins meeting.
    offsets: {1|2: App.Vector} a side's joint frame moved off its vertex, in its part's axes (a Select
    Midpoint edge: the vertex at its start and the way to its middle).
    Returns the joint."""
    import UtilsAssembly
    JO = _ja()
    try:
        from . import asmgen
        asmgen.hold(asm.Document)       # a batch of mates: the tree repaints once they stop
    except Exception as _fw_err:
        _fw_log("asmcore.py:961", _fw_err)
    # asmpkg349: a pick named from the assembly itself ("Origin.XY_Plane.", "Plane1.") names the reference it
    # is on, as a pick in the view does (FreeCAD's solver would take the whole assembly as the part to move)
    ref1, ref2 = (_from_assembly(asm, r) for r in (ref1, ref2))
    for ref in (ref1, ref2):
        hold_reference(asm, ref[0])
    before = _save_placements(asm)
    start = [(c, App.Placement(c.Placement)) for c in components(asm)] if kind == "Lock" else None
    group = joint_group(asm)
    joint = group.newObject("App::FeaturePython", "Mate")
    _joint_proxy(JO, joint, JO.JointTypes.index("Ball" if ball and kind == "Coincident" else _coincident_type(
        kind, joint_type(kind, lock_rotation, _reverse(kind, value)), ref1, ref2)))
    if App.GuiUp:
        JO.ViewProviderJoint(joint.ViewObject)
    joint.addProperty("App::PropertyString", MATE_PROP, "FreeCAD", "Mate type")
    joint.addProperty("App::PropertyBool", LOCK_PROP, "FreeCAD", "Concentric: Lock rotation")
    joint.addProperty("App::PropertyBool", ERROR_PROP, "FreeCAD", "The mate over defines the assembly")
    joint.addProperty("App::PropertyBool", REVERSE_PROP, "FreeCAD", "Gear: Reverse")
    setattr(joint, MATE_PROP, kind)
    setattr(joint, LOCK_PROP, bool(lock_rotation))
    joint.Label = name or _next_mate_name(asm, kind)
    set_value(joint, kind, value)
    with _no_creation_solve():      # solved once below: FreeCAD's own solve here doubled the time
        joint.Proxy.setJointConnectors(joint, [[ref1[0], [ref1[1], ref1[1]]], [ref2[0], [ref2[1], ref2[1]]]])
        for i, off in (offsets or {}).items():
            jref = joint.Reference1 if i == 1 else joint.Reference2
            mine = ref1 if i == 1 else ref2
            k = i if jref[0] == mine[0] else 3 - i      # FreeCAD may put the references the other way
            setattr(joint, "Offset%d" % k, App.Placement(off, App.Rotation()))
        if offsets:
            joint.Proxy.updateJCSPlacements(joint)
        if kind == "Distance":
            set_distance_side(joint, side)  # held on the side the components are on now
            set_value(joint, kind, value)
        elif kind == "Rack Pinion":
            set_value(joint, kind, value)   # the rack first: needs the picks, set just above
        elif kind == "Tangent":
            _tangent_datum(joint)
    if kind == "Concentric" and lock_rotation:
        keep_turn(joint, before)
    if flip:
        joint.Proxy.flipOnePart(joint)
    if kind == "Universal Joint":
        _restore_placements(asm, before)   # FreeCAD's connect may move them
        cross(joint)
    _quiet(joint)
    held = kind == "Concentric" and _held_by_concentric(asm, joint)
    if held and _misaligned(asm, joint, before):
        ok = True       # misaligned: not solved at all (an over defined solve is slow and can crash)
    elif held and misalignment(joint) > MISALIGN_TOL and _parallel(joint):
        ok = False      # off another exact Concentric: over defined for sure, no solve needed
    else:
        ok = solve(asm, before)
        if not ok and kind == "Perpendicular":
            ok = _square_from_parallel(asm, joint, before)
        if kind == "Tangent" and not (ok and satisfied(joint)):
            ok = _lay_tangent(asm, joint, before)
        if not ok and kind in ("Concentric", "Coincident"):
            ok = _presolved(asm, joint, before)
        if not ok and kind == "Concentric":
            ok = _misaligned(asm, joint, before)
            if not ok and _all_hold(asm, inner=True):

                # (a rigid rod-and-piston subassembly on the crank pin and in the bore): FreeCAD's
                # solver gives up on the freedom held twice (and drives the parts off on the next
                # recompute), so the mate is kept out of the solve and checked after each one instead
                _set_redundant(joint, True)
                ok = True
        if not ok and kind == "Coincident" and _line_plane(joint) is not None:
            ok = _line_on_plane(asm, joint, before)
        if kind == "Coincident" and _point_plane(joint) is not None and not _point_plane_holds(joint):
            ok = _point_on_plane(asm, joint, before)
        if ok and kind == "Coincident" and _point_plane(joint) is not None:
            pass        # a point on a plane: its one equation holds wherever it is; no other way round
        elif ok and kind not in MECHANICAL:
            _optimize(asm, joint, before)
            if kind in ("Concentric", "Coincident") and joint.JointType == "Cylindrical":
                _keep_along(asm, joint, before)
        if kind == "Angle":
            ok = _angle_nearest(asm, joint, before, ok)
    if couple(asm, joint) and (ok or kind == "Screw"):   # a free nut: its hidden Concentric is what lets it solve
        ok = solve(asm)
    if kind == "Lock":
        hold_pose(asm, joint, start)
        ok = solve(asm)
    _mark(joint, ok)
    try:
        from . import asmrefopts
        asmrefopts.name_refs(asm, joint)     # Automatically generate names for referenced geometry
    except Exception as _fw_err:
        _fw_log("asmcore.py:1022", _fw_err)
    return joint


def _plane_normal(comp, sub):
    f = element(comp, sub)
    try:
        if f is None or f.ShapeType != "Face" or "Plane" not in f.Surface.TypeId:
            return None
        u0, u1, v0, v1 = f.ParameterRange
        return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    except Exception:
        return None


def _face_angle(joint):
    """The angle (deg) between the two picked faces' normals, or None."""
    import math
    try:
        n1 = _plane_normal(joint.Reference1[0], joint.Reference1[1][0])
        n2 = _plane_normal(joint.Reference2[0], joint.Reference2[1][0])
        if n1 is None or n2 is None:
            return None
        return math.degrees(math.acos(max(-1.0, min(1.0, n1.dot(n2)))))
    except Exception:
        return None


def _turn(plc, before):
    """How far (deg) a placement turned from before."""
    import math
    try:
        return math.degrees((plc.Rotation * before.Rotation.inverse()).Angle)
    except Exception:
        return 0.0


def _angle_frames(joint):
    ""


    import UtilsAssembly
    z = App.Vector(0, 0, 1)
    flips = 0
    try:
        for plc, ref in ((joint.Placement1, joint.Reference1), (joint.Placement2, joint.Reference2)):
            n = _plane_normal(ref[0], ref[1][0])
            if n is None:
                return False
            g = UtilsAssembly.getJcsGlobalPlc(plc, ref)
            if g.Rotation.multVec(z).dot(n) < 0:
                flips += 1
    except Exception:
        return False
    if flips % 2 == 0:
        return False
    JO = _ja()
    saved = getattr(JO, "solveIfAllowed", None)
    if saved is not None:
        JO.solveIfAllowed = lambda *a, **k: None    # solved right after by the caller
    try:
        old = joint.Offset2
        joint.Offset2 = App.Placement(old.Base, old.Rotation.multiply(App.Rotation(App.Vector(1, 0, 0), 180)))
    finally:
        if saved is not None:
            JO.solveIfAllowed = saved
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: angle mate: %s\n" % error)
    return True


def _angle_nearest(asm, joint, before, ok):
    ""



    import math
    import UtilsAssembly
    try:
        want_v = float(App.Units.Quantity(joint.Angle).getValueAs("deg"))
    except Exception:
        want_v = float(getattr(joint, "Angle", 0.0) or 0.0)
    now = {o.Name: o.Placement for o in _movable(asm)}
    _restore_placements(asm, before)
    a0 = _face_angle(joint)
    if a0 is None:
        _restore_placements(asm, now)
        return ok
    want = want_v       # between the faces' normals, both frames facing out (_angle_frames)
    if _angle_frames(joint):
        ok = solve(asm, before)         # FreeCAD measured from a frame facing into its part
        now = {o.Name: o.Placement for o in _movable(asm)}
        _restore_placements(asm, before)
    c1, c2 = joint.Reference1[0], joint.Reference2[0]
    fixed = set(grounded(asm))
    moving = c1 if c1 not in fixed else c2
    if moving in fixed:
        _restore_placements(asm, now)
        return ok
    start = App.Placement(before.get(moving.Name, moving.Placement))

    def good(res):
        a = _face_angle(joint)
        return res and a is not None and abs(a - want) < 1e-3 and satisfied(joint)

    _restore_placements(asm, now)
    best = None
    if good(ok):
        best = (_turn(moving.Placement, start), {o.Name: o.Placement for o in _movable(asm)})
        if best[0] <= abs(want - a0) + 1e-3:
            return True         # already the near way
    # the axes it may turn about: its round mates' axes, then the normal across both faces
    axes = []
    for m in mates(asm):
        if m is joint or getattr(m, "Suppressed", False):
            continue
        for plc, ref in ((m.Placement1, m.Reference1), (m.Placement2, m.Reference2)):
            if ref and ref[0] is moving and mate_type(m) in ("Concentric", "Hinge", "Revolute", "Cylindrical"):
                try:
                    g = UtilsAssembly.getJcsGlobalPlc(plc, ref)
                    axes.append((g.Rotation.multVec(App.Vector(0, 0, 1)), g.Base))
                except Exception:
                    pass
    try:
        n1 = _plane_normal(c1, joint.Reference1[1][0]); n2 = _plane_normal(c2, joint.Reference2[1][0])
        mf = element(moving, (joint.Reference1 if moving is c1 else joint.Reference2)[1][0])
        centre = mf.CenterOfMass
        cross = n1.cross(n2)
        if cross.Length > 1e-6:
            axes.append((cross.normalize(), centre))
        else:
            u = n1.cross(App.Vector(0, 0, 1))
            if u.Length < 1e-6:
                u = n1.cross(App.Vector(1, 0, 0))
            axes.append((u.normalize(), centre))
            axes.append((n1.cross(u).normalize(), centre))
    except Exception:
        pass
    step = abs(want - a0)
    for axis, at in axes:
        for sign in (1.0, -1.0):
            _restore_placements(asm, before)
            moving.Placement = App.Placement(App.Vector(), App.Rotation(axis, sign * step), at).multiply(start)
            res = solve(asm, before)
            if good(res):
                turned = _turn(moving.Placement, start)
                if best is None or turned < best[0] - 1e-6:
                    best = (turned, {o.Name: o.Placement for o in _movable(asm)})
    if best is None:
        _restore_placements(asm, now)
        return ok
    _restore_placements(asm, best[1])
    return True


def keep_turn(joint, before=None):
    ""




    try:
        def frame(which):
            comp = getattr(joint, "Reference%d" % which)[0]
            plc = (before or {}).get(comp.Name, comp.Placement)
            return plc.multiply(getattr(joint, "Placement%d" % which))
        f1, f2 = frame(1), frame(2)
    except Exception:
        return False
    z1, z2 = f1.Rotation.multVec(V(0, 0, 1)), f2.Rotation.multVec(V(0, 0, 1))
    side = z1 if z1.dot(z2) >= 0 else -z1
    line_up = App.Rotation(z2, side)       # the turn lining the second axis up with the first
    want = f2.Rotation.inverted().multiply(line_up.inverted()).multiply(f1.Rotation)
    old = joint.Offset2
    JO = _ja()
    saved = getattr(JO, "solveIfAllowed", None)
    if saved is not None:
        JO.solveIfAllowed = lambda *a, **k: None    # solved right after by the caller
    try:
        joint.Offset2 = App.Placement(old.Base, old.Rotation.multiply(want))
    finally:
        if saved is not None:
            JO.solveIfAllowed = saved
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: lock rotation: %s\n" % error)
    return True


def _least_move(joint, second_moves):
    """The smallest move putting the moving pick on the other: a turn lining up the normals (axes)
    the nearer way, then a slide along the normal (plane on plane) or across the axis (axis on
    axis). None when the picks are not two planes or two axes."""
    try:
        refs = [(r[0], (r[1] or [""])[0]) for r in (joint.Reference1, joint.Reference2)]
        g1, g2 = [geometry(element(c, e)) for c, e in refs]
    except Exception:
        return None
    if g1 is None or g2 is None:
        return None
    gm, gf = (g2, g1) if second_moves else (g1, g2)
    plane = gm[0] == "plane" and gf[0] == "plane"
    axis = gm[0] in ("axis", "line") and gf[0] in ("axis", "line")
    if not (plane or axis):
        return None
    pm, dm = V(gm[1]), V(gm[2])
    pf, df = V(gf[1]), V(gf[2])
    if dm.Length < 1e-12 or df.Length < 1e-12:
        return None
    dm.normalize()
    df.normalize()
    target = df if dm.dot(df) >= 0 else df * -1
    turn = App.Placement(V(), App.Rotation(dm, target), pm)
    d = pf - pm
    shift = target * d.dot(target) if plane else d - target * d.dot(target)
    return App.Placement(shift, App.Rotation()) * turn


def _point_plane(joint):
    """For a Coincident of a point (a vertex, or a Select Midpoint edge: its vertex and an offset)
    and a flat face: (point side 1|2, plane side 1|2), else None."""
    try:
        kinds = []
        for i in (1, 2):
            ref = getattr(joint, "Reference%d" % i)
            elt = ref[1][0].split(".")[-1]
            if elt.startswith("Vertex"):
                kinds.append("point")
            elif elt.startswith("Face") and _plane_normal(ref[0], ref[1][0]) is not None:
                kinds.append("plane")
            else:
                kinds.append(None)
        if kinds == ["point", "plane"]:
            return 1, 2
        if kinds == ["plane", "point"]:
            return 2, 1
    except Exception:
        return None
    return None


def _point_plane_gap(joint):
    """The point's distance off the plane (mm), along the plane's normal, with that normal."""
    import UtilsAssembly
    pt, pl = _point_plane(joint)
    joint.Proxy.updateJCSPlacements(joint)
    p = UtilsAssembly.getJcsGlobalPlc(getattr(joint, "Placement%d" % pt), getattr(joint, "Reference%d" % pt)).Base
    q = UtilsAssembly.getJcsGlobalPlc(getattr(joint, "Placement%d" % pl), getattr(joint, "Reference%d" % pl))
    n = q.Rotation.multVec(App.Vector(0, 0, 1))
    return (p - q.Base).dot(n), n


def _point_plane_holds(joint, tol=1e-5):
    try:
        return abs(_point_plane_gap(joint)[0]) < tol
    except Exception as _fw_err:
        _fw_log("asmcore.py:point plane", _fw_err)
        return True


def _line_plane(joint):
    """(asmpkg355) For a Coincident of a straight edge and a flat face: ((line comp, its point, its direction),
    (plane comp, its point, its normal)) in assembly axes, else None."""
    try:
        got = {}
        for i in (1, 2):
            ref = getattr(joint, "Reference%d" % i)
            g = geometry(element(ref[0], ref[1][0]))
            if g is not None and g[0] in ("line", "plane"):
                got[g[0]] = (ref[0], V(g[1]), V(g[2]).normalize())
        if len(got) == 2:
            return got["line"], got["plane"]
    except Exception as _fw_err:
        _fw_log("asmcore.py:line plane", _fw_err)
    return None


def _line_on_plane(asm, joint, before):
    ""


    try:
        (c_ln, p_ln, d), (c_pl, p_pl, n) = _line_plane(joint)
        fixed = set(grounded(asm))
        def lay(v, against):
            t = v - against * v.dot(against)
            if t.Length < 1e-9:     # square on: any way along the face
                t = against.cross(V(1, 0, 0) if abs(against.x) < 0.9 else V(0, 1, 0))
            return t.normalize()
        if c_ln not in fixed:
            turn = App.Rotation(d, lay(d, n))
            c_ln.Placement = App.Placement(V(), turn, p_ln).multiply(c_ln.Placement)
        elif c_pl not in fixed:
            turn = App.Rotation(n, lay(n, d))
            c_pl.Placement = App.Placement(V(), turn, p_pl).multiply(c_pl.Placement)
        else:
            return False
        joint.Proxy.updateJCSPlacements(joint)
        return bool(solve(asm, before)) and satisfied(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:line on plane", _fw_err)
        return False


def _point_on_plane(asm, joint, before):
    ""


    try:
        pt, pl = _point_plane(joint)
        gap, n = _point_plane_gap(joint)
        fixed = set(grounded(asm))
        c_pt, c_pl = getattr(joint, "Reference%d" % pt)[0], getattr(joint, "Reference%d" % pl)[0]
        if c_pl not in fixed:
            c_pl.Placement = App.Placement(n * gap, App.Rotation()) * c_pl.Placement
        elif c_pt not in fixed:
            c_pt.Placement = App.Placement(n * -gap, App.Rotation()) * c_pt.Placement
        else:
            return False
        joint.Proxy.updateJCSPlacements(joint)
        ok = solve(asm, before)
        return bool(ok) and _point_plane_holds(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:point on plane", _fw_err)
        return False


def _presolved(asm, joint, before):
    """FreeCAD's solver can run off when the free component starts far from where the new mate puts it
    (a pin mated into a bracket that was only just mated itself). FreeCAD's own joint task first moves
    the free component onto the mate: do that, the nearer way round, and solve again. True when solved;
    on failure the components go back to before."""
    import UtilsAssembly
    try:
        (c1, _e1), (c2, _e2) = [(r[0], r[1]) for r in (joint.Reference1, joint.Reference2)]
        fixed = set(grounded(asm))
        joint.Suppressed = True
        try:
            free1 = c1 not in fixed and not asm.isPartConnected(c1)
            free2 = c2 not in fixed and not asm.isPartConnected(c2)
        finally:
            joint.Suppressed = False
        z = App.Vector(0, 0, 1)
        if free1 or free2:
            if free2:
                moving, m_plc, m_ref, f_plc, f_ref = c2, joint.Placement2, joint.Reference2, joint.Placement1, joint.Reference1
            else:
                moving, m_plc, m_ref, f_plc, f_ref = c1, joint.Placement1, joint.Reference1, joint.Placement2, joint.Reference2
            move = _least_move(joint, moving is c2)
            if move is not None:

                # its normal, an axis across itself, and a turn only lines up the normals (axes);
                # matching FreeCAD's whole joint frames spun the part round as well (a rod put on
                # a crank web came out upside down)
                moving.Placement = move * moving.Placement
                if solve(asm, before):
                    return True
                _restore_placements(asm, before)
            mg = UtilsAssembly.getJcsGlobalPlc(m_plc, m_ref)
            fg = UtilsAssembly.getJcsGlobalPlc(f_plc, f_ref)
            if mg.Rotation.multVec(z).dot(fg.Rotation.multVec(z)) < 0:
                mg = UtilsAssembly.flipPlacement(mg)
            moving.Placement = fg * mg.inverse() * moving.Placement
            return solve(asm, before)
        if mate_type(joint) == "Concentric":
            # both held by other mates (a rod on a crank web, then onto the crank pin): slide one
            # across onto the axis, first the first pick, as its other mates let it
            for comp, second in ((c1, False), (c2, True)):
                if comp in fixed:
                    continue
                move = _least_move(joint, second)
                if move is None:
                    break
                comp.Placement = move * comp.Placement
                if solve(asm, before):
                    return True
                _restore_placements(asm, before)
            return False
        if mate_type(joint) != "Coincident":
            return False
        # both held by other mates: two parallel planes, slide one component (first the first pick)
        # along their normal onto the other; its other mates let it (a pin along its hole)
        g1 = UtilsAssembly.getJcsGlobalPlc(joint.Placement1, joint.Reference1)
        g2 = UtilsAssembly.getJcsGlobalPlc(joint.Placement2, joint.Reference2)
        n = g2.Rotation.multVec(z)
        if g1.Rotation.multVec(z).cross(n).Length > 1e-6:
            return False
        gap = (g2.Base - g1.Base).dot(n)
        for comp, step in ((c1, gap), (c2, -gap)):
            if comp in fixed:
                continue
            comp.Placement = App.Placement(comp.Placement.Base + n * step, comp.Placement.Rotation)
            if solve(asm, before):
                return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: pre-solve: %s\n" % error)
    _restore_placements(asm, before)
    return False


def _parallel(joint):
    g1, g2 = _axes(joint)
    return bool(g1 and g2 and g1[0] == "axis" and g2[0] == "axis" and g1[2].cross(g2[2]).Length < 1e-3)


# a Concentric this far off (mm) or less is on its axis: FreeCAD's solver stops a few
# hundred-thousandths short, and a piston mated on its pin first sat 0.000026 off its bore, was
# taken for a misaligned mate and left out of the solve (it swung off the bore in a motion study)
MISALIGN_TOL = 1e-4


def _flexible_subs(asm):
    return [c for c in components(asm) if is_flexible(c)]


def _all_hold(asm, inner=False):
    """Every mate that takes part holds where the components are (inner: also the mates inside
    the flexible subassemblies, FreeCAD's copies)."""
    js = [j for j in mates(asm) if not getattr(j, "Suppressed", False) and not mate_error(j)]
    if inner:
        for sub in _flexible_subs(asm):
            for g in (getattr(sub, "Group", []) or []):
                if g.TypeId == "Assembly::JointGroup":
                    js += [j for j in g.Group if hasattr(j, "Reference1") and hasattr(j, "JointType")
                           and not getattr(j, "Suppressed", False)]
    try:
        return bool(js) and all(satisfied(j) for j in js)
    except Exception:
        return False


def _ref_comp_names(joint, names):
    """The names of the components a mate's two references are on."""
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if not ref:
            continue
        obj = ref[0]
        hit = obj.Name if obj is not None and obj.Name in names else None
        if hit is None:
            subs = ref[1] if len(ref) > 1 else []
            sub = subs[0] if isinstance(subs, (list, tuple)) and subs else (subs if isinstance(subs, str) else "")
            hit = next((part for part in (sub or "").split(".") if part in names), None)
        if hit is not None:
            out.append(hit)
    return out


def unspin(asm, exclude=()):
    """Components held only by Concentric mates on one axis (a gudgeon pin) are free to spin on it,
    and drags spin them. Each is turned back on its axis to sit square with its first mate's other
    side, when that leaves every mate as it was. Returns True when one turned."""
    import math
    fixed = {c.Name for c in grounded(asm)} | set(exclude)
    names = {c.Name for c in components(asm)}
    ms = [j for j in mates(asm) if not getattr(j, "Suppressed", False)]
    turned = False
    for comp in components(asm):
        if comp.Name in fixed:
            continue
        own = [j for j in ms if comp.Name in _ref_comp_names(j, names)]
        if not own or any(getattr(j, "JointType", "") not in ("Cylindrical", "Revolute") for j in own):
            continue
        axes = [_axes(j) for j in own]
        if any(not g1 or not g2 or g1[0] != "axis" or g2[0] != "axis" for g1, g2 in axes):
            continue
        a = axes[0][0][2]
        if any(g[2].cross(a).Length > 1e-6 for g1, g2 in axes for g in (g1, g2)):
            continue
        j = own[0]
        side1 = j.Reference1[0].Name == comp.Name
        other = j.Reference2[0] if side1 else j.Reference1[0]
        mine = comp.Placement * (j.Placement1 if side1 else j.Placement2)
        theirs = other.Placement * (j.Placement2 if side1 else j.Placement1)
        rel = mine.Rotation.inverted().multiply(theirs.Rotation)
        v = rel.multVec(App.Vector(1, 0, 0))
        ang = math.degrees(math.atan2(v.y, v.x))
        if abs(ang) < 90:
            continue
        held = [m for m in ms if satisfied(m)]
        was = App.Placement(comp.Placement)
        z = mine.Rotation.multVec(App.Vector(0, 0, 1))
        spin = App.Placement(App.Vector(), App.Rotation(z, ang), mine.Base)
        comp.Placement = spin.multiply(was)
        if all(satisfied(m) for m in held):
            turned = True
        else:
            comp.Placement = was
    return turned


def _axis_dir(joint):
    g1, _g2 = _axes(joint)
    return g1[2] if g1 and g1[0] in ("axis", "line") else None


def _held_by_concentric(asm, joint):
    ""



    refs = [r[0] for r in (joint.Reference1, joint.Reference2) if r and r[0] is not None]
    fixed = set(grounded(asm))
    mine = _axis_dir(joint)
    for other in mates(asm):
        if other is joint or getattr(other, "Suppressed", False) or mate_type(other) != "Concentric":
            continue
        theirs = _axis_dir(other)
        if mine is not None and theirs is not None and mine.cross(theirs).Length > 1e-6:
            continue
        comps = {r[0] for r in (other.Reference1, other.Reference2) if r and r[0] is not None}
        if all(c in comps or c in fixed for c in refs):
            return True
    return False


def _size(comp):
    try:   # an AssemblyLink (subassembly) has no Shape
        import Part
        bb = Part.getShape(comp, "", needSubElement=False, transform=False).BoundBox
        return bb.DiagonalLength / 2.0 if bb.isValid() else 10.0
    except Exception:
        return 10.0


def _movement(asm, before, info=None):
    """How far the components went from before: millimetres plus turns weighed by their size.
    info (a dict) gets "turned": whether any component turned."""
    total = 0.0
    for comp in components(asm):
        old = before.get(comp.Name)
        if old is None:
            continue
        new = comp.Placement
        if new.isSame(old, 1e-12):
            continue        # not moved: nothing to add (and no need to measure it)
        try:   # an AssemblyLink (subassembly) has no Shape
            import Part
            bb = Part.getShape(comp, "", needSubElement=False, transform=False).BoundBox
            size = bb.DiagonalLength / 2.0 if bb.isValid() else 10.0
        except Exception:
            size = 10.0
        turn = (old.Rotation.inverted() * new.Rotation).Angle
        if info is not None and turn > 1e-9:
            info["turned"] = True
        total += (new.Base - old.Base).Length + size * turn
    return total


def _optimize(asm, joint, before):
    """Optimize component placement when adding mates: of the two alignments the one that moves
    the components least (the mate is solved now; it is tried the other way round too)."""
    from . import asmoptions
    if not asmoptions.optimize_placement():
        return
    import UtilsAssembly
    first = _save_placements(asm)
    info = {}
    moved = _movement(asm, before, info)
    if moved < 1e-6:
        return
    if not info.get("turned"):
        # nothing turned: the other alignment turns one of the mate's components half a turn
        # (the two meet the other way round), which moves it at least pi times its size; when the
        # components only slid less than that, this way is already the least movement
        try:
            comps = [r[0] for r in (joint.Reference1, joint.Reference2) if r and r[0] is not None]
            least = min(_size(c) for c in comps) if comps else 0.0
        except Exception:
            least = 0.0
        if least > 0 and moved <= math.pi * least - 1e-6:
            return
    best, keep = moved, first
    _restore_placements(asm, before)
    try:
        joint.Proxy.flipOnePart(joint)
        other = solve(asm, before)
    except Exception:
        other = False
    if other:
        m = _movement(asm, before)
        if m < best - 1e-6:
            best, keep = m, _save_placements(asm)

    # nearer way and slid onto the other pick; FreeCAD's whole-frame match (either way round)
    # could also turn it end for end (a yoke inserted ears down came back upright)
    fixed = set(grounded(asm))
    for second in (True, False):
        try:
            comp = (joint.Reference2 if second else joint.Reference1)[0]
            if comp is None or comp in fixed or _held_by_other(asm, joint, comp):
                continue
            _restore_placements(asm, before)
            move = _least_move(joint, second)
            if move is None:
                break
            comp.Placement = move * comp.Placement
            if solve(asm, before):
                m = _movement(asm, before)
                if m < best - 1e-6:
                    best, keep = m, _save_placements(asm)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: least move: %s\n" % error)
    _restore_placements(asm, keep)


def _held_by_other(asm, joint, comp):
    ""


    try:
        for j in joint_group(asm).Group:
            if j is joint or not hasattr(j, "JointType") or getattr(j, "Suppressed", False):
                continue
            for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)):
                if r and r[0] is comp:
                    return True
    except Exception:
        return True
    return False


def _keep_along(asm, joint, before):
    ""


    try:
        fixed = set(grounded(asm))
        moved = [c for c in components(asm) if c.Name in before and c not in fixed
                 and not c.Placement.isSame(before[c.Name], 1e-9)]
        if len(moved) != 1:
            return
        comp = moved[0]
        other = [r for r in (joint.Reference1, joint.Reference2) if _part_of(asm, r) is not comp]
        if len(other) != 1:
            return
        g = geometry(element(other[0][0], other[0][1][0]))
        if g is None or g[0] not in ("axis", "line"):
            return
        axis = V(g[2])
        if axis.Length < 1e-12:
            return
        axis.normalize()
        now = App.Placement(comp.Placement)
        c_now = comp.Shape.BoundBox.Center
        c_was = before[comp.Name].multVec(now.inverse().multVec(c_now))
        along = (c_now - c_was).dot(axis)
        if abs(along) < 1e-6:
            return
        after = _save_placements(asm)
        comp.Placement = App.Placement(now.Base - axis * along, now.Rotation)
        if not (solve(asm) and satisfied(joint)):
            _restore_placements(asm, after)
    except Exception as _fw_err:
        _fw_log("asmcore.py:keep along", _fw_err)


def _axes(joint):
    try:
        (c1, e1), (c2, e2) = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
        return geometry(element(c1, e1)), geometry(element(c2, e2))
    except Exception:
        return None, None


def misalignment(joint):
    """The offset between a Concentric mate's two axes (mm)."""
    g1, g2 = _axes(joint)
    if not g1 or not g2 or g1[0] not in ("axis", "line") or g2[0] not in ("axis", "line"):
        return 0.0
    return (g2[1] - g1[1]).cross(g1[2]).Length


def is_misaligned(joint):
    return bool(getattr(joint, MISALIGNED_PROP, 0.0))


def is_redundant(joint):
    return bool(getattr(joint, REDUNDANT_PROP, False))


def _set_redundant(joint, on):
    if on and not hasattr(joint, REDUNDANT_PROP):
        joint.addProperty("App::PropertyBool", REDUNDANT_PROP, "FreeCAD",
                          "Holds and agrees with the other mates; left out of the solve (it holds a freedom twice)")
    if hasattr(joint, REDUNDANT_PROP) and getattr(joint, REDUNDANT_PROP) != bool(on):
        setattr(joint, REDUNDANT_PROP, bool(on))


def _square_from_parallel(asm, joint, before):
    ""



    try:
        fixed = set(grounded(asm))
        parts = [_part_of(asm, joint.Reference2), _part_of(asm, joint.Reference1)]
        movers = [c for c in parts if c is not None and c not in fixed and hasattr(c, "Placement")]
    except Exception as _fw_err:
        _fw_log("asmcore.py:square", _fw_err)
        return False
    if not movers:
        return False
    comp = movers[0]
    for axis in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
        _restore_placements(asm, before)
        try:
            centre = comp.Shape.BoundBox.Center
        except Exception:
            centre = comp.Placement.Base
        tip = App.Placement(V(), App.Rotation(axis, 5.0), centre)
        comp.Placement = tip.multiply(comp.Placement)
        if solve(asm) and satisfied(joint):
            return True
    _restore_placements(asm, before)
    solve(asm, before)
    return False


def _lay_tangent(asm, joint, before):
    ""



    try:
        refs = [joint.Reference1, joint.Reference2]
        geo = [_ref_geometry(r[0], r[1][0]) for r in refs]
        k = next(i for i, g in enumerate(geo) if g is not None and g[0] == "axis" and len(g) > 3 and g[3] > 0)
        plane = geo[1 - k]
        if plane is None or plane[0] != "plane":
            return False
        comp = _part_of(asm, refs[k])
        if comp is None or comp in set(grounded(asm)) or not hasattr(comp, "Placement"):
            return False
        a, n = V(geo[k][2]).normalize(), V(plane[2]).normalize()
        flat = a - n * a.dot(n)
        if flat.Length < 1e-9:      # standing on it: lay it down towards where its frame points
            flat = n.cross(V(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(V(0, 1, 0))
        flat.normalize()
        try:
            centre = comp.Shape.BoundBox.Center
        except Exception:
            centre = comp.Placement.Base
        _restore_placements(asm, before)
        comp.Placement = App.Placement(V(), App.Rotation(a, flat), centre).multiply(comp.Placement)
        _tangent_datum(joint)       # an origin plane: the frame again from the laid-down pin
        if solve(asm) and satisfied(joint):
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tangent lay down: %s\n" % error)
    _restore_placements(asm, before)
    _tangent_datum(joint)
    solve(asm, before)
    return False


def _misaligned(asm, joint, before):
    """Allow creation of misaligned mates: a Concentric that over defines only because its axis is
    off another one is kept, the offset shown (at most the smaller radius). The components stay
    where the other mates put them; the misaligned mate is left out of FreeCAD's solve (a
    Parallel joint fighting the exact Concentric crashed the solver on Windows)."""
    from . import asmoptions
    if not asmoptions.misaligned():
        return False
    import UtilsAssembly
    _restore_placements(asm, before)
    g1, g2 = _axes(joint)
    if not g1 or not g2 or g1[0] != "axis" or g2[0] != "axis":
        return False
    if g1[2].cross(g2[2]).Length > 1e-3:
        return False                                  # not parallel: a real over definition
    off = misalignment(joint)
    limit = min(r for r in (g1[3], g2[3]) if r) if (g1[3] or g2[3]) else 1.0
    if off < MISALIGN_TOL or off > limit + 1e-6:
        return False
    if not hasattr(joint, MISALIGNED_PROP):
        joint.addProperty("App::PropertyFloat", MISALIGNED_PROP, "FreeCAD", "Misaligned Concentric: axis offset (mm)")
    setattr(joint, MISALIGNED_PROP, off)
    return True


def hold_pose(asm, joint, before=None):
    """before: [(component, placement)] as they stood before the mate."""
    _hold_pose(asm, joint, before)


def _part_of(asm, ref):
    """The component a joint reference points into (FreeCAD keeps the assembly as the object
    and the component in the sub-element path)."""
    obj, subs = ref[0], ref[1]
    if obj in components(asm):
        return obj
    found = reference(asm, obj, subs[0]) if subs else None
    return found[0] if found else obj


def _hold_pose(asm, joint, before):
    ""


    def back():
        for comp, plc in before or []:
            comp.Placement = plc    # where they were before FreeCAD's connect and solve moved them
    try:
        back()
        a, b = _part_of(asm, joint.Reference1), _part_of(asm, joint.Reference2)
        o1 = joint.Offset1
        want = b.Placement.multiply(joint.Placement2).inverse().multiply(a.Placement.multiply(joint.Placement1).multiply(o1))
        JO = _ja()
        saved = getattr(JO, "solveIfAllowed", None)
        if saved is not None:
            JO.solveIfAllowed = lambda *a_, **k_: None     # solved by the caller right after (a whole
        try:                                               # FreeCAD solve here: 6 s at 300 mates)
            joint.Offset2 = want
        finally:
            if saved is not None:
                JO.solveIfAllowed = saved
        try:
            joint.Proxy.updateJCSPlacements(joint)
        except Exception as _fw_err:
            _fw_log("asmcore.py:lock jcs", _fw_err)
        back()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: lock: %s\n" % error)


DIST_SIDE_PROP = "FwDistanceSide"    # Distance: +1/-1, FreeCAD's signed distance on the side the parts were


def distance_side(joint):
    ""


    side = getattr(joint, DIST_SIDE_PROP, 0)
    return -1 if side < 0 else 1


def _facing_side(joint, z1):
    ""



    try:
        s1 = element(joint.Reference1[0], joint.Reference1[1][0])
        s2 = element(joint.Reference2[0], joint.Reference2[1][0])
        if s1 is None or s2 is None or s1.ShapeType != "Face" or s2.ShapeType != "Face":
            return None
        if s1.Surface.TypeId != "Part::GeomPlane" or s2.Surface.TypeId != "Part::GeomPlane":
            return None
        n1 = s1.normalAt(*s1.Surface.parameter(s1.CenterOfMass))
        n2 = s2.normalAt(*s2.Surface.parameter(s2.CenterOfMass))
        if n1.dot(n2) > -1 + 1e-6:
            return None
        # the second face on the outside of the first: along n1, which z1 runs with or against
        return 1 if z1.dot(n1) > 0 else -1
    except Exception as _fw_err:
        _fw_log("asmcore.py:_facing_side", _fw_err)
        return None


def _measured_side(joint):
    try:
        g1 = joint.Reference1[0].Placement.multiply(joint.Placement1)
        g2 = joint.Reference2[0].Placement.multiply(joint.Placement2)
        z1 = g1.Rotation.multVec(V(0, 0, 1))
        d = (g2.Base - g1.Base).dot(z1)
    except Exception:
        return 1
    facing = _facing_side(joint, z1)
    if facing is not None:
        return facing
    return -1 if d < -1e-6 else 1


def set_distance_side(joint, side=None):
    side = _measured_side(joint) if side is None else (-1 if side < 0 else 1)
    if DIST_SIDE_PROP not in joint.PropertiesList:
        joint.addProperty("App::PropertyInteger", DIST_SIDE_PROP, "FreeCAD", "Distance: the side it holds on")
        try:
            joint.setPropertyStatus(DIST_SIDE_PROP, "Hidden")
        except Exception as _fw_err:
            _fw_log("asmcore.py:1430", _fw_err)
    setattr(joint, DIST_SIDE_PROP, side)
    return side


def distance_value(joint):
    ""
    v = getattr(joint, "Distance", 0.0)
    return float(getattr(v, "Value", v)) * distance_side(joint)


def set_value(joint, kind, value):
    if kind == "Distance":
        joint.Distance = float(value or 0.0) * distance_side(joint)
    elif kind in ("Coincident", "Tangent"):
        joint.Distance = 0.0
    elif kind == "Angle":
        joint.Angle = float(value or 0.0)
    elif kind == "Gear":
        d1, d2 = (value[0], value[1]) if value else (1.0, 1.0)
        joint.Distance = max(1e-7, float(d1)) / 2.0      # FreeCAD's gears take the radii
        joint.Distance2 = max(1e-7, float(d2)) / 2.0
    elif kind == "Universal Joint":
        if joint.Reference1 and joint.Reference2:
            cross(joint)
    elif kind == "Profile Center":
        offset, flip_, lock = value if value else (0.0, False, False)
        joint.Offset1 = App.Placement(V(0, 0, -float(offset) if flip_ else float(offset)), App.Rotation())
        joint.Offset2 = App.Placement()
        if not hasattr(joint, VALUE_PROP):
            joint.addProperty("App::PropertyString", VALUE_PROP, "FreeCAD", "Profile Center: the values given")
        setattr(joint, VALUE_PROP, "%r %d %d" % (float(offset), bool(flip_), bool(lock)))
    elif kind in ("Rack Pinion", "Screw"):
        mode, number = (value[0], float(value[1])) if value else \
            (("diameter", 10.0) if kind == "Rack Pinion" else ("distance", 1.0))
        number = max(1e-7, number)
        if kind == "Rack Pinion":       # FreeCAD's rack and pinion takes the pitch radius
            rack_first(joint)
            size = number / 2.0 if mode == "diameter" else number / (2.0 * math.pi)
        else:                           # FreeCAD's screw takes the travel per turn
            size = 1.0 / number if mode == "revs" else number
        joint.Distance = -size if _reverse(kind, value) else size
        if not hasattr(joint, VALUE_PROP):
            joint.addProperty("App::PropertyString", VALUE_PROP, "FreeCAD", "Rack Pinion / Screw: the value given")
        setattr(joint, VALUE_PROP, "%s %r" % (mode, number))
    if hasattr(joint, REVERSE_PROP):
        setattr(joint, REVERSE_PROP, _reverse(kind, value))


def change_mate(asm, joint, kind, value=None, lock_rotation=False, editing=False):
    """Edits a mate in place: another type, distance or angle. editing: an existing mate opened
    again (System Options > Assemblies > Change mate alignments on edit decides a flip)."""
    import UtilsAssembly
    before = _save_placements(asm)   # FreeCAD's own calls below may move parts
    _unsuppress(joint)
    if getattr(joint, ERROR_PROP, False):
        setattr(joint, ERROR_PROP, False)   # checked again below: an old error must not hide a new one
    want = joint_type(kind, lock_rotation, _reverse(kind, value))
    try:
        want = _coincident_type(kind, want, (joint.Reference1[0], joint.Reference1[1][0]),
                                (joint.Reference2[0], joint.Reference2[1][0]))
    except Exception as _fw_err:
        _fw_log("asmcore.py:coincident lines", _fw_err)
    if not hasattr(joint, REVERSE_PROP):
        joint.addProperty("App::PropertyBool", REVERSE_PROP, "FreeCAD", "Gear: Reverse")
    if joint.JointType != want:
        joint.Proxy.setJointType(joint, want)
        if want == "Slider":
            keep_turn(joint, before)
    if kind == "Distance" and (mate_type(joint) != "Distance" or DIST_SIDE_PROP not in joint.PropertiesList):
        set_distance_side(joint, 1 if DIST_SIDE_PROP not in joint.PropertiesList and mate_type(joint) == "Distance" else None)
    was_tangent = mate_type(joint) == "Tangent"
    setattr(joint, MATE_PROP, kind)
    setattr(joint, LOCK_PROP, bool(lock_rotation))
    if kind == "Tangent":
        _tangent_datum(joint)       # asmpkg350: a round face on an origin plane
    elif was_tangent and any(_datum_plane(r[0], r[1][0]) is not None for r in (joint.Reference1, joint.Reference2)):
        JO = _ja()
        saved = getattr(JO, "solveIfAllowed", None)
        if saved is not None:
            JO.solveIfAllowed = lambda *a, **k: None    # solved below
        try:
            joint.Offset1 = joint.Offset2 = App.Placement()     # the Tangent's own frame off again
            if getattr(joint, TANGENT_FRAME, False):
                setattr(joint, TANGENT_FRAME, False)
        finally:
            if saved is not None:
                JO.solveIfAllowed = saved
        joint.Proxy.updateJCSPlacements(joint)
    base = joint.Label.split(" (")[0]
    old = "".join(ch for ch in base if not ch.isdigit())
    if old != NAMES.get(kind, kind):
        joint.Label = _next_mate_name(asm, kind)
    set_value(joint, kind, value)
    if getattr(joint, MISALIGNED_PROP, 0.0):
        setattr(joint, MISALIGNED_PROP, 0.0)
        joint.Suppressed = False
    ok = solve(asm, before)
    if not ok and kind in ("Perpendicular", "Parallel", "Coincident"):
        ok = _square_from_parallel(asm, joint, before)     # another type from where the old one put them
    if kind == "Tangent" and not (ok and satisfied(joint)):
        ok = _lay_tangent(asm, joint, before)
    if not ok and kind == "Concentric":
        ok = _misaligned(asm, joint, before)
    elif ok and not editing and kind not in MECHANICAL:
        _optimize(asm, joint, before)
    if couple(asm, joint) and (ok or kind == "Screw"):   # a free nut: its hidden Concentric is what lets it solve
        ok = solve(asm)
    if not ok and editing and kind not in MECHANICAL:
        ok = _flip_on_edit(asm, joint, before)
    if ok and kind == "Angle":
        _mark(joint, ok)
        return keep_angle_sense(asm, joint)
    return _mark(joint, ok)


def _flip_on_edit(asm, joint, before):
    from . import asmoptions
    policy = asmoptions.align_on_edit()
    if policy == "Never":
        return False
    import UtilsAssembly
    _restore_placements(asm, before)
    try:
        joint.Proxy.flipOnePart(joint)
        ok = solve(asm, before)
    except Exception:
        ok = False
    if not ok or (policy == "Prompt" and App.GuiUp and not asmoptions.ask_flip()):
        try:
            joint.Proxy.flipOnePart(joint)      # the flip did not help: the mate keeps its alignment
        except Exception as _fw_err:
            _fw_log("asmcore.py:1535", _fw_err)
        _restore_placements(asm, before)
        return False
    return True


def _align_dot(joint):
    try:
        (c1, e1), (c2, e2) = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
        d1, d2 = _direction(geometry(element(c1, e1))), _direction(geometry(element(c2, e2)))
        return None if d1 is None or d2 is None else d1.dot(d2)
    except Exception:
        return None


def _signs(asm, joint):
    """Each other mate's alignment (the sign between its two picks' directions)."""
    out = {}
    for m in mates(asm):
        if m is not joint and not getattr(m, "Suppressed", False):
            d = _align_dot(m)
            if d is not None and abs(d) > 1e-6:
                out[m.Name] = d > 0
    return out


def _kept(asm, joint, signs):
    ""

    if not all(satisfied(m) for m in mates(asm) if not getattr(m, "Suppressed", False)):
        return False
    for m in mates(asm):
        if m.Name in signs:
            d = _align_dot(m)
            if d is not None and abs(d) > 1e-6 and (d > 0) != signs[m.Name]:
                return False
    return True


def flip(asm, joint):
    ""


    import UtilsAssembly
    before = _save_placements(asm)
    _unsuppress(joint)
    d0 = _align_dot(joint)
    signs = _signs(asm, joint)
    joint.Proxy.flipOnePart(joint)
    ok = solve(asm, before)
    d1 = _align_dot(joint)
    if d0 is None or abs(d0) < 1e-6 or (ok and d1 is not None and d1 * d0 < 0 and _kept(asm, joint, signs)):
        return _mark(joint, ok)
    _restore_placements(asm, before)
    c1, c2 = joint.Reference1[0], joint.Reference2[0]
    fixed = set(grounded(asm))
    best = None
    for moving, ref in ((c1, joint.Reference1), (c2, joint.Reference2)):
        if moving in fixed:
            continue
        try:
            f = element(moving, ref[1][0])
            n = _direction(geometry(f))
            at = f.CenterOfMass if hasattr(f, "CenterOfMass") else f.Point
        except Exception:
            continue
        if n is None:
            continue
        n = V(n).normalize()
        axes = []
        for a in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
            a = a - n * a.dot(n)        # in the face's plane (across the axis)
            if a.Length > 1e-6 and not any(abs(abs(a.normalize().dot(b)) - 1) < 1e-6 for b in axes):
                axes.append(V(a).normalize())
        start = App.Placement(before.get(moving.Name, moving.Placement))
        for a in axes:
            _restore_placements(asm, before)
            moving.Placement = App.Placement(V(), App.Rotation(a, 180), at).multiply(start)
            if solve(asm, before) and (_align_dot(joint) or 0) * d0 < 0 and _kept(asm, joint, signs):
                moved = (moving.Placement.Base - start.Base).Length
                if best is None or moved < best[0] - 1e-9:
                    best = (moved, {o.Name: o.Placement for o in _movable(asm)})
        if best is not None:
            break       # the first pick's component turns, as FreeCAD's flip does
    if best is None:
        _restore_placements(asm, before)
        return _mark(joint, solve(asm, before))
    _restore_placements(asm, best[1])
    return _mark(joint, True)


# ----------------------------------------------------------------------------- Angle: flip, reference direction
ANGLE_FLIP_PROP = "FwAngleFlip"       # Angle: Flip dimension (the angle measured the other way round)
ANGLE_REF_PROP = "FwAngleRef"         # Angle: Reference Direction ("component\tsub-element")


def _prop(joint, name, kind, doc):
    if name not in joint.PropertiesList:
        joint.addProperty(kind, name, "FreeCAD", doc)


def angle_ref(asm, joint):
    """(component, element) of the Angle mate's Reference Direction, or None."""
    text = getattr(joint, ANGLE_REF_PROP, "") or ""
    if "\t" not in text:
        return None
    name, sub = text.split("\t", 1)
    comp = asm.Document.getObject(name)
    return (comp, sub) if comp is not None else None


def set_angle_ref(asm, joint, ref):
    """Sets (or with None clears) the Reference Direction; the angle then keeps its sense to it."""
    _prop(joint, ANGLE_REF_PROP, "App::PropertyString", "Angle: Reference Direction")
    setattr(joint, ANGLE_REF_PROP, "%s\t%s" % (ref[0].Name, ref[1]) if ref else "")
    if ref:
        return keep_angle_sense(asm, joint)
    return True


def _direction(g):
    return V(g[2]) if g is not None and len(g) > 2 else None


def angle_frame(asm, joint):
    """(z1, z2, axis, point) of an Angle mate now: the two directions, the turning axis (the
    Reference Direction when there is one) and a point of the moving component's element."""
    try:
        (c1, e1), (c2, e2) = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    except Exception:
        return None
    s2 = element(c2, e2)
    z1, z2 = _direction(geometry(element(c1, e1))), _direction(geometry(s2))
    if z1 is None or z2 is None:
        return None
    axis = None
    ref = angle_ref(asm, joint)
    if ref is not None:
        axis = _direction(geometry(element(*ref)))
        if axis is not None and axis.Length > 1e-12:
            axis = V(axis).normalize()
            z1 = z1 - axis * z1.dot(axis)         # the angle seen along the reference direction
            z2 = z2 - axis * z2.dot(axis)
            if z1.Length < 1e-9 or z2.Length < 1e-9:
                axis = None
    if axis is None:
        axis = z1.cross(z2)
        if axis.Length < 1e-9:
            return None
    z1, z2 = V(z1).normalize(), V(z2).normalize()
    return z1, z2, V(axis).normalize(), V(s2.CenterOfMass)


def signed_angle(asm, joint):
    """The Angle mate's angle in degrees, + or - by its turning axis (Reference Direction)."""
    f = angle_frame(asm, joint)
    if f is None:
        return None
    z1, z2, axis, _p = f
    return math.degrees(math.atan2(axis.dot(z1.cross(z2)), z1.dot(z2)))


def _mover(asm, joint):
    fixed = grounded(asm)
    a, b = _part_of(asm, joint.Reference1), _part_of(asm, joint.Reference2)
    return b if b not in fixed else (a if a not in fixed else None)


def _mirror_angle(asm, joint):
    """Turns the moving component to the angle's other side (same size, measured the other way)."""
    f = angle_frame(asm, joint)
    comp = _mover(asm, joint)
    if f is None or comp is None:
        return False
    z1, z2, axis, point = f
    theta = math.degrees(math.atan2(axis.dot(z1.cross(z2)), z1.dot(z2)))
    if abs(theta) < 1e-6 or abs(abs(theta) - 180.0) < 1e-6:
        return False
    if comp is _part_of(asm, joint.Reference1):
        theta = -theta          # the first component moves: it turns the other way
        try:
            point = V(element(joint.Reference1[0], joint.Reference1[1][0]).CenterOfMass)
        except Exception as _fw_err:
            _fw_log("asmcore.py:1641", _fw_err)
    turn = App.Placement(V(), App.Rotation(axis, -2.0 * theta), point)
    comp.Placement = turn.multiply(comp.Placement)
    return True


def keep_angle_sense(asm, joint):
    """With a Reference Direction the angle keeps its sense: + about it, - with Flip dimension."""
    if angle_ref(asm, joint) is None:
        return True
    a = signed_angle(asm, joint)
    if a is None:
        return True
    want_negative = bool(getattr(joint, ANGLE_FLIP_PROP, False))
    if (a < -1e-6) == want_negative or abs(a) < 1e-6 or abs(abs(a) - 180.0) < 1e-6:
        return True
    import UtilsAssembly
    before = _save_placements(asm)
    if not _mirror_angle(asm, joint):
        return True
    return _mark(joint, solve(asm, before))


def set_angle_flip(asm, joint, flipped):
    """Angle: Flip dimension. The component goes to the angle's other side."""
    _prop(joint, ANGLE_FLIP_PROP, "App::PropertyBool", "Angle: Flip dimension")
    if bool(getattr(joint, ANGLE_FLIP_PROP)) == bool(flipped):
        return True
    setattr(joint, ANGLE_FLIP_PROP, bool(flipped))
    import UtilsAssembly
    before = _save_placements(asm)
    _unsuppress(joint)
    _mirror_angle(asm, joint)
    return _mark(joint, solve(asm, before))


def _exploded_now(joint):
    try:
        from . import asmexplode
        name = joint.Document.Name
        for (dname, vname) in list(asmexplode.EXPLODED):
            if dname == name:
                view = joint.Document.getObject(vname)
                if view is not None and asmexplode.is_exploded(view):
                    return True
    except Exception:
        return False
    return False


def satisfied(joint, tol=1e-3):
    """True when the mate holds where the components now are. FreeCAD's solver can report
    success for mates that contradict each other (two Coincident mates on parallel faces 10 mm
    apart), so each mate is checked again on the real geometry."""
    if _exploded_now(joint):
        return True
    kind = mate_type(joint)
    if kind == "Path Mate":
        from . import asmpath
        return asmpath.holds(joint, tol)
    if kind == "Linear/Linear Coupler":
        from . import asmcoupler
        return asmcoupler.holds(joint, tol)
    if kind == "Cam":
        from . import asmcam
        return asmcam.holds(joint, tol)
    if kind == "InPlace":
        from . import asmnewpart
        return asmnewpart.holds(joint, tol)
    try:
        (c1, e1), (c2, e2) = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    except Exception:
        return True
    s1, s2 = element(c1, e1), element(c2, e2)
    g1, g2 = geometry(s1), geometry(s2)
    if kind == "Hinge":
        return _hinge_holds(joint, tol)
    if kind in LIMITS:
        return limit_holds(joint, tol)
    if kind == "Symmetric":
        return symmetric_holds(joint, tol)
    if kind == "Profile Center":
        return _frames_meet(joint, tol)
    if kind == "Width":
        r = _width_range(joint)
        if r is not None:
            return r[4] - tol * 10 <= r[3] <= r[5] + tol * 10 and _round_holds(joint, tol)
        data = width_values(joint)
        if data is not None and round_tab(data[1]):
            return _round_holds(joint, tol)
        return _planes_meet(joint, tol)
    if kind == "Universal Joint":
        return _arms_square(joint, tol) and _through_point(joint, tol)
    if kind == "Slot":
        return slot_holds(joint, tol)
    if kind == "Screw":
        kind = "Concentric"
    if g1 is None or g2 is None or kind in ("Lock",) + MECHANICAL:
        return True     # a mechanical mate couples motion only: nothing to hold where they are
    t1, t2 = g1[0], g2[0]
    value = abs(float(getattr(joint, "Distance", 0) or 0))
    if kind in ("Coincident", "Tangent", "Distance"):
        target = 0.0 if kind != "Distance" else value
        if t1 == "plane" and t2 == "plane":
            if g1[2].cross(g2[2]).Length > tol:
                return False
            return abs(abs(g1[2].dot(g2[1] - g1[1])) - target) < tol * 10
        if "plane" in (t1, t2):
            p, o = (g1, g2) if t1 == "plane" else (g2, g1)
            gap = abs(p[2].dot(o[1] - p[1]))
            if o[0] == "point":
                return abs(gap - target) < tol * 10
            edge = (s2 if p is g1 else s1).ShapeType == "Edge"
            if o[0] == "axis" and edge:     # a circular edge lies in the plane: its axis is the normal
                return abs(abs(p[2].dot(o[2])) - 1.0) < tol and abs(gap - target) < tol * 10
            if abs(p[2].dot(o[2])) > tol:
                return False
            if kind == "Tangent" and o[0] == "axis":
                return abs(gap - o[3]) < tol * 10
            return kind == "Distance" or abs(gap - target) < tol * 10
        return True
    if kind == "Concentric":
        if t1 == "point" or t2 == "point":
            return True
        if is_misaligned(joint):
            return g1[2].cross(g2[2]).Length < tol
        return g1[2].cross(g2[2]).Length < tol and (g2[1] - g1[1]).cross(g1[2]).Length < tol * 10
    if kind == "Parallel":
        if "plane" in (t1, t2) and t1 != t2:
            return abs(g1[2].dot(g2[2])) < tol
        return g1[2].cross(g2[2]).Length < tol
    if kind == "Perpendicular":
        if "plane" in (t1, t2) and t1 != t2:
            return g1[2].cross(g2[2]).Length < tol
        return abs(g1[2].dot(g2[2])) < tol
    if kind == "Angle":
        import math as _m
        want = _m.radians(float(getattr(joint.Angle, "Value", joint.Angle)))
        got = _m.acos(max(-1.0, min(1.0, g1[2].dot(g2[2]))))
        return min(abs(got - want), abs(_m.pi - got - want)) < 1e-3
    return True


def _mark(joint, ok):
    ""

    if hasattr(joint, ERROR_PROP) and getattr(joint, ERROR_PROP) != (not ok):
        setattr(joint, ERROR_PROP, not ok)
    if not ok:
        _set_redundant(joint, False)
    off = (not ok) or is_misaligned(joint) or is_redundant(joint)   # misaligned / redundant: out of the solve
    if hasattr(joint, "Suppressed") and joint.Suppressed != off:
        joint.Suppressed = off
    return ok


def _unsuppress(joint):
    if getattr(joint, "Suppressed", False) and mate_error(joint):
        joint.Suppressed = False


def mate_error(joint):
    return bool(getattr(joint, ERROR_PROP, False))


def _mesh_turn(comp, axis, deg, centre):
    comp.Placement = App.Placement(V(), App.Rotation(axis, deg), centre).multiply(comp.Placement)


def follow_cross(asm, moved):
    ""



    out = []
    if moved is None:
        return out
    held = grounded(asm)
    for j in mates(asm):
        if getattr(j, "Suppressed", False) or mate_type(j) != "Universal Joint":
            continue
        r1, r2 = getattr(j, "Reference1", None), getattr(j, "Reference2", None)
        if not r1 or not r2 or moved not in (r1[0], r2[0]):
            continue
        ms, os_ = (1, 2) if moved is r1[0] else (2, 1)
        other = (r2 if ms == 1 else r1)[0]
        if other is moved or other in held:
            continue
        try:
            ax = _axis_now(other, (r2 if ms == 1 else r1)[1][0])
            if ax is None:
                continue
            centre, v = ax
            arm_m = _frame(moved, j, ms).Rotation.multVec(V(0, 0, 1))
            arm_o = _frame(other, j, os_).Rotation.multVec(V(0, 0, 1))
            arm_o = arm_o - v * arm_o.dot(v)
            if arm_o.Length < 1e-9:
                continue
            arm_o.normalize()
            c, s_ = arm_o.dot(arm_m), v.cross(arm_o).dot(arm_m)
            if abs(c) < 1e-9 or abs(c) < 1e-9 * abs(s_):
                continue            # already square
            phi = math.atan2(-c, s_)
            if phi > math.pi / 2:
                phi -= math.pi
            elif phi < -math.pi / 2:
                phi += math.pi
            _mesh_turn(other, v, math.degrees(phi), centre)
            out.append(other)
        except Exception as _fw_err:
            _fw_log("asmcore.py:follow_cross", _fw_err)
    return out


def follow_mesh(asm, moved, before):
    ""




    if moved is None or before is None:
        return []
    out = []
    held = grounded(asm)
    for j in mates(asm):
        if getattr(j, "Suppressed", False) or mate_type(j) not in ("Gear", "Rack Pinion"):
            continue
        r1, r2 = getattr(j, "Reference1", None), getattr(j, "Reference2", None)
        if not r1 or not r2 or moved not in (r1[0], r2[0]):
            continue
        other = r2[0] if moved is r1[0] else r1[0]
        if other is moved or other in held or other in out:
            continue
        ms, os_ = ("1", "2") if moved is r1[0] else ("2", "1")
        try:
            fb = before.multiply(getattr(j, "Placement" + ms))
            fn = moved.Placement.multiply(getattr(j, "Placement" + ms))
            fo = other.Placement.multiply(getattr(j, "Placement" + os_))
            if mate_type(j) == "Gear":
                axis = fb.Rotation.multVec(V(0, 0, 1))
                d = fn.Rotation.multiply(fb.Rotation.inverted())
                if d.Angle < 1e-9 or abs(d.Axis.dot(axis)) < 0.99:
                    continue
                deg = math.degrees(d.Angle) * (1 if d.Axis.dot(axis) > 0 else -1)
                rm = float(j.Distance if ms == "1" else j.Distance2)
                ro = float(j.Distance2 if ms == "1" else j.Distance)
                same = getattr(j, "JointType", "") == "Belt"        # Reverse: both turn the same way
                _mesh_turn(other, axis, deg * rm / ro * (1 if same else -1), fo.Base)
            else:
                r = abs(float(j.Distance))
                sign = -1.0 if float(j.Distance) < 0 else 1.0
                if ms == "2":           # the pinion turned: the rack slides along with its pitch circle
                    axis = fb.Rotation.multVec(V(0, 0, 1))
                    d = fn.Rotation.multiply(fb.Rotation.inverted())
                    if d.Angle < 1e-9 or abs(d.Axis.dot(axis)) < 0.99:
                        continue
                    ang = d.Angle * (1 if d.Axis.dot(axis) > 0 else -1)
                    t = fo.Rotation.multVec(V(0, 0, 1))     # the rack slides along its edge (the mate frame's Z)
                    if (axis.cross(fo.Base - fb.Base)).dot(t) < 0:
                        t = -t
                    other.Placement = App.Placement(other.Placement.Base + t * (r * ang * sign), other.Placement.Rotation)
                else:                   # the rack slid: the pinion turns
                    axis = fo.Rotation.multVec(V(0, 0, 1))
                    t = fb.Rotation.multVec(V(0, 0, 1))     # the rack's edge
                    if (axis.cross(fb.Base - fo.Base)).dot(t) < 0:
                        t = -t
                    if r < 1e-9:
                        continue
                    ang = (fn.Base - fb.Base).dot(t) / r * sign
                    if abs(ang) < 1e-12:
                        continue
                    _mesh_turn(other, axis, math.degrees(ang), fo.Base)
            out.append(other)
        except Exception as _fw_err:
            _fw_log("asmcore.py:follow_mesh", _fw_err)
    return out


def solve(asm, before=None):
    ""


    import UtilsAssembly
    if before is None:
        before = _save_placements(asm)
    for joint in mates(asm):
        if getattr(joint, MATE_PROP, "") == "Angle Range":
            _angle_range_clamp(asm, joint)      # asmpkg351: turned past a Limit Angle: back to its end first
    try:
        from . import asmpersist
        asmpersist.install()
        asmpersist.keep(asm)        # mates keep their faces when a part renumbers them
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mate references: %s\n" % error)
    sync_parts(asm)
    sync_flexible(asm)
    sync_limits(asm)
    for joint in mates(asm):
        if getattr(joint, MATE_PROP, "") == "Distance Range":
            _range_clamp(asm, joint)    # a free range: a move past its end stops there
        elif getattr(joint, MATE_PROP, "") == "Hinge":
            _hinge_clamp(asm, joint)    # a Hinge turned past its limit stops there
        elif getattr(joint, TANGENT_FRAME, False) and getattr(joint, MATE_PROP, "") == "Tangent":
            _tangent_datum(joint)       # from where the round part is now: it stays free to roll
    sync_symmetric(asm)
    from . import asmpath
    asmpath.sync(asm)
    comps = components(asm) if not grounded(asm) else []
    if _retry_errors(asm, before, comps):
        return True
    try:
        result = _solve_now(asm, comps)
        if result != 0 and _virtual_flexible(asm):
            # a flexible virtual subassembly: its mates' copies share this document and are
            # placed at a recompute; from there the same solve goes through
            _restore_placements(asm, before)
            asm.Document.recompute()
            result = _solve_now(asm, comps)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: assembly not solved: %s\n" % error)
        result = -1
    return _solved(asm, before, result)


def _virtual_flexible(asm):
    return any(is_flexible(c) and getattr(c.LinkedObject, "Document", None) is asm.Document
               for c in components(asm))


_RETRIED = {}       # assembly -> the mates as they were when its errored mates last failed again


def _retried_key(asm, errs):
    rows = []
    for j in mates(asm):
        rows.append((j.Name, j in errs, bool(getattr(j, "Suppressed", False)), str(getattr(j, "JointType", "")),
                     str(getattr(j, "Distance", "")), str(getattr(j, "Distance2", "")),
                     str(getattr(j, "Angle", "")), str(getattr(j, "Reference1", "")), str(getattr(j, "Reference2", ""))))
    for c in components(asm):       # Solve as Flexible / Rigid changes what the mates can do
        if is_subassembly(c):
            rows.append(("flexible", c.Name, bool(is_flexible(c))))
    return tuple(rows)


def _retry_errors(asm, before, comps):
    ""


    errs = [j for j in mates(asm) if (mate_error(j) or is_redundant(j)) and getattr(j, "Suppressed", False)
            and not getattr(j, "FwUserSuppressed", False) and not is_misaligned(j)]
    tag = (asm.Document.Name, asm.Name)
    if not errs:
        _RETRIED.pop(tag, None)
        return False
    key = _retried_key(asm, errs)
    if _RETRIED.get(tag) == key:
        return False
    import UtilsAssembly
    for j in errs:
        j.Suppressed = False
    try:
        result = _solve_now(asm, comps)
    except Exception:
        result = -1
    ok = _solved(asm, before, result) and all(satisfied(j) for j in errs)
    if ok:
        for j in errs:
            setattr(j, ERROR_PROP, False)
            _set_redundant(j, False)
        _RETRIED.pop(tag, None)
        return True
    for j in errs:
        j.Suppressed = True
    _restore_placements(asm, before)
    _RETRIED[tag] = _retried_key(asm, errs)
    return False


_SOLVED = {}        # (document, assembly) -> what every mate input was right after its last good solve
SOLVE_STATS = {"solved": 0, "skipped": 0}


def _solve_key(asm, depth=0):
    """Every input of FreeCAD's solve: where each movable component is, every property of every
    mate (and grounding), each part's shape, and the same for each subassembly (a flexible
    one's mates and parts are solved with it). None when it cannot be told, so the solve runs."""
    try:
        if depth > 6:
            return None
        rows = []
        for o in _movable(asm):
            p = o.Placement     # rounded: a solve's own noise (1e-12) is no change
            rows.append((o.Name, tuple(round(x, 7) for x in p.Base), tuple(round(x, 9) for x in p.Rotation.Q)))
        group = joint_group(asm)
        for j in (group.Group if group is not None else []):
            for name in j.PropertiesList:
                if name in ("Label2", "Visibility", "ExpressionEngine"):
                    continue
                v = getattr(j, name, None)
                if isinstance(v, App.Placement):
                    v = (tuple(round(x, 7) for x in v.Base), tuple(round(x, 9) for x in v.Rotation.Q))
                elif isinstance(v, float):
                    v = round(v, 9)
                rows.append((j.Name, name, str(v)))
        shapes = {}
        for c in components(asm):
            rows.append((c.Name, bool(getattr(c, "Suppressed", False)), bool(getattr(c, "Visibility", True))))
            if c.TypeId == "Assembly::AssemblyObject" or (
                    is_subassembly(c) and getattr(getattr(c, "LinkedObject", None), "Document", None) is asm.Document):
                return None     # a virtual subassembly: its copies are placed by recomputes, the solve always runs
            if c.TypeId == "Assembly::AssemblyLink":
                p = c.Placement
                rows.append((c.Name, bool(getattr(c, "Rigid", True)), tuple(p.Base), tuple(p.Rotation.Q)))
                for o in getattr(c, "Group", []) or []:
                    q = getattr(o, "Placement", None)
                    if q is not None:
                        rows.append((c.Name, o.Name, tuple(q.Base), tuple(q.Rotation.Q)))
                inner = getattr(c, "LinkedObject", None)
                if inner is None or inner is asm:
                    return None
                key = _SUB_KEYS.get(id(inner))
                if key is None:
                    key = _SUB_KEYS[id(inner)] = _solve_key(inner, depth + 1)
                if key is None:
                    return None
                rows.append((c.Name, hash(key)))
                continue
            t = getattr(c, "LinkedObject", None) if c.TypeId == "App::Link" else c
            if t is None:
                continue
            if id(t) not in shapes:
                try:
                    shapes[id(t)] = (t.Name, t.Document.Name, t.Shape.hashCode(), str(t.Shape.BoundBox))
                except Exception:
                    shapes[id(t)] = (t.Name, None)
            rows.append(shapes[id(t)])
        return tuple(rows)
    except Exception:
        return None
    finally:
        if depth == 0:
            _SUB_KEYS.clear()


_SUB_KEYS = {}      # one key per subassembly document while a key is made


def _solve_now(asm, comps):
    """FreeCAD's solve, skipped when no input changed since the last good solve (the solver
    then puts every component back where it is: a whole solve of a 300-part assembly, 3 s, for
    nothing). A drag, a mate edit, a part change or a component moved makes it run."""
    tag = (asm.Document.Name, asm.Name, getattr(asm, "ID", 0), getattr(asm.Document, "Uid", ""))   # never a deleted namesake
    key = _solve_key(asm)
    if key is not None and _SOLVED.get(tag) == key:
        SOLVE_STATS["skipped"] += 1
        return 0
    SOLVE_STATS["solved"] += 1
    result = None
    if not comps and key is not None and _SOLVED.get(tag) is not None:
        result = _solve_cluster(asm, set(_SOLVED[tag]).symmetric_difference(key))
    if result is None:
        result = _solve_now_real(asm, comps)
    if result == 0 and key is not None:
        _SOLVED[tag] = _solve_key(asm)
    else:
        _SOLVED.pop(tag, None)
    return result


CLUSTER_MIN = 40     # mates in an assembly before only the part of it that changed is solved
SOLVE_STATS["cluster"] = 0


CLUSTER_WHY = []       # why the last whole solves were whole (checks read it)


def _why(k):
    CLUSTER_WHY.append(k)
    del CLUSTER_WHY[:-20]
    return None


def _solve_cluster(asm, changed):
    ""





    try:
        group = joint_group(asm)
        if group is None:
            return _why(1)
        live = [j for j in group.Group if hasattr(j, "JointType") and hasattr(j, "Reference1")
                and not getattr(j, "Suppressed", False)]
        if len(live) < CLUSTER_MIN:
            return _why(2)
        comps = {c.Name: c for c in components(asm)}
        joints = {j.Name: j for j in group.Group}
        names = {r[0] for r in changed if r}
        if not names or any(n not in comps and n not in joints for n in names):
            return _why(3)     # a part's shape, a subassembly: the whole solve
        fixed = {c.Name for c in grounded(asm)}
        ends = {}
        for j in live:
            if getattr(j, MATE_PROP, "") in VIRTUAL or getattr(j, PART_OF_PROP, ""):
                return _why(4)     # ranges, slots, couplers: their own follow-up wants every mate
            two = []
            for ref in (j.Reference1, j.Reference2):
                c = _part_of(asm, ref) if ref else None
                if c is None or c.Name not in comps:
                    return _why(5)
                two.append(c.Name)
            ends[j.Name] = two
        by_comp = {}
        for name, two in ends.items():
            for c in two:
                by_comp.setdefault(c, []).append(name)
        seen_c, seen_j = set(), set()
        todo = [n for n in names if n in comps]
        for n in names:
            if n in ends:
                seen_j.add(n)
                todo.extend(ends[n])
            elif n in joints and n not in comps:
                return _why(6)     # a mate switched off or a ground joint changed: the whole solve
        while todo:
            c = todo.pop()
            if c in seen_c:
                continue
            seen_c.add(c)
            if c in fixed:
                continue        # a fixed component does not pass a change on
            for name in by_comp.get(c, ()):
                if name not in seen_j:
                    seen_j.add(name)
                    todo.extend(ends[name])
        if not seen_j or len(seen_j) * 2 > len(live):
            return _why((7, len(seen_j), len(live), sorted(names)[:6], len(names)))
        out = [j for j in live if j.Name not in seen_j]
        touched = {j.Name: "Touched" in j.State for j in out}
        asm_touched = "Touched" in asm.State
        from . import asmgen
        token = object()
        asmgen.OVERLAY_HOLD.append(token)      # the mate rows' icons: the same before and after
        try:
            for j in out:
                j.Suppressed = True
            try:
                result = asm.solve()
            finally:
                for j in out:
                    j.Suppressed = False
                    if not touched[j.Name]:
                        j.purgeTouched()
                if not asm_touched and "Touched" in asm.State:
                    asm.purgeTouched()
        finally:
            if token in asmgen.OVERLAY_HOLD:
                asmgen.OVERLAY_HOLD.remove(token)
        SOLVE_STATS["cluster"] += 1
        return result
    except Exception as _fw_err:
        _fw_log("asmcore.py:cluster", _fw_err)
        return _why(repr(_fw_err))


class quiet_edit:
    ""




    def __init__(self, asm):
        self.asm, self.out, self.token = asm, [], None

    def __enter__(self):
        try:
            group = joint_group(self.asm)
            live = [j for j in (group.Group if group is not None else []) if hasattr(j, "JointType")
                    and hasattr(j, "Reference1") and not getattr(j, "Suppressed", False)]
            if len(live) < CLUSTER_MIN:
                return self
            if any(mate_error(j) for j in live) or not all(satisfied(j) for j in live if getattr(j, MATE_PROP, "") not in VIRTUAL):
                return self      # something to solve: FreeCAD's own solve runs
            from . import asmgen
            self.token = object()
            asmgen.OVERLAY_HOLD.append(self.token)
            self.touched = {j.Name: "Touched" in j.State for j in live}
            self.asm_touched = "Touched" in self.asm.State
            self.out = live
            for j in live:
                j.Suppressed = True
        except Exception as _fw_err:
            _fw_log("asmcore.py:quiet edit", _fw_err)
            self.__exit__()
        return self

    def __exit__(self, *exc):
        try:
            for j in self.out:
                j.Suppressed = False
                if not self.touched.get(j.Name, True):
                    j.purgeTouched()
            if self.out and not self.asm_touched and "Touched" in self.asm.State:
                self.asm.purgeTouched()
        except Exception as _fw_err:
            _fw_log("asmcore.py:quiet edit exit", _fw_err)
        finally:
            self.out = []
            if self.token is not None:
                from . import asmgen
                if self.token in asmgen.OVERLAY_HOLD:
                    asmgen.OVERLAY_HOLD.remove(self.token)
                self.token = None
        return False


def _solve_now_real(asm, comps):
    if comps:

        # needs one component held, so the first is held for this solve
        with temp_ground(asm, comps[:1]):
            return asm.solve()
    result = asm.solve()
    if result != 0:
        result = _solve_nudged(asm, result)
    return result


def _solve_nudged(asm, result):
    ""


    fixed = set(grounded(asm))
    free = [c for c in components(asm) if c not in fixed]
    if not free:
        return result
    saved = _save_placements(asm)
    try:
        for i, c in enumerate(free):
            axis = (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1))[i % 3]
            c.Placement = App.Placement(c.Placement.Base, App.Rotation(axis, 1e-4) * c.Placement.Rotation)
        again = asm.solve()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: nudged solve: %s\n" % error)
        again = result
    if again != 0:
        _restore_placements(asm, saved)
        return result
    return again


def _solved(asm, before, result):
    import UtilsAssembly
    from . import asmpath
    screws = []
    if result == 0:
        asmpath.place(asm)      # Path Mate: back on the path, turned along it
        from . import asmcoupler
        asmcoupler.couple(asm)  # Linear/Linear Coupler: the one that moved drives the other
        screws = screw_follow(asm)  # Screw: a turn drives the travel (FreeCAD couples only in a drag)
        from . import asmcam
        asmcam.follow(asm)      # Cam: each follower back on its cam
        width_free_clamp(asm)   # Width Free: the tab kept inside the groove
        from . import asmnewpart
        asmnewpart.follow(asm)  # InPlace: a new part kept on the face it was made on
        from . import asmcpattern
        asmcpattern.follow(asm)  # component patterns: instances follow their seeds
        try:
            from . import asmfeature
            asmfeature.follow(asm)   # weld beads and belts follow the components they are on
        except Exception as error:
            App.Console.PrintLog("FreeCAD: weld beads / belts after a solve: %s\n" % error)
    if result == -1 and _all_hold(asm, inner=True):
        # FreeCAD's solver can give up on mates that hold the same freedom twice though they
        # agree (a rigid rod-and-piston subassembly on the crank pin and in the bore), or throw
        # at its very end on a flexible subassembly (an index out of range) after placing every

        result = 0
    if result == 0 and not all(satisfied(j) for j in mates(asm)
                                if (not getattr(j, "Suppressed", False) and not mate_error(j)) or is_redundant(j)):
        result = -2
    if result != 0:
        _restore_placements(asm, before)
        return False
    for joint, state in screws:
        _screw_store(joint, state)
    return True


# ----------------------------------------------------------------------------- Rack Pinion, Screw
def parts(asm):
    """The hidden joints FreeCAD needs under Rack Pinion and Screw mates."""
    return [j for j in joint_group(asm).Group if getattr(j, PART_OF_PROP, "")]


def _part_for(asm, joint):
    return [j for j in parts(asm) if getattr(j, PART_OF_PROP) == joint.Name]


def couple(asm, joint):
    ""





    kind = mate_type(joint)
    for old in _part_for(asm, joint):
        asm.Document.removeObject(old.Name)
    if kind == "Rack Pinion":
        refs = rack_first(joint)
        if not refs:
            return False
        rack, edge = refs[0]
        fixed = [c for c in grounded(asm) if c is not rack and c is not refs[1][0]]
        if rack in grounded(asm) or not fixed:
            return False
        anchor = fixed[0]
        import UtilsAssembly
        before = _save_placements(asm)
        part = _hidden(asm, joint, "Slider", [[rack, [edge, edge]], [anchor, ["", ""]]])
        _restore_placements(asm, before)   # FreeCAD's connect moved the rack
        # the anchor's frame where the rack's is now: it slides from here along the edge
        part.Offset2 = anchor.Placement.inverse().multiply(rack.Placement.multiply(part.Placement1))
        try:
            part.Proxy.updateJCSPlacements(part)
        except Exception as _fw_err:
            _fw_log("asmcore.py:2046", _fw_err)
        return True
    if kind == "Profile Center":
        return _profile_finish(asm, joint)

    if kind == "Screw":
        import UtilsAssembly
        before = _save_placements(asm)
        refs = [[r[0], [r[1][0], r[1][0]]] for r in (joint.Reference1, joint.Reference2)]
        made = not all(_on_axis(asm, joint, r[0], r[1][0]) for r in refs)
        if made:    # (a second hold on an axis other mates already give stalls FreeCAD's drag)
            _hidden(asm, joint, "Cylindrical", refs)
            _restore_placements(asm, before)
        _here(joint)
        return made
    return False


SCREW_STATE_PROP = "FwScrewState"     # Screw: the turn and travel last seen (radians, mm)


def _screw_now(joint):
    """(turn, travel, axis, first frame, second frame) of a Screw mate as its components are
    now: the second frame's turn about the first frame's z and its travel along it."""
    c1, c2 = joint.Reference1[0], joint.Reference2[0]
    g1 = c1.Placement.multiply(joint.Placement1)
    g2 = c2.Placement.multiply(joint.Placement2)
    z = g1.Rotation.multVec(V(0, 0, 1))
    x2 = g1.Rotation.inverted().multVec(g2.Rotation.multVec(V(1, 0, 0)))
    return math.atan2(x2.y, x2.x), (g2.Base - g1.Base).dot(z), z, g1, g2


def _screw_store(joint, state=None):
    try:
        if state is None:
            state = _screw_now(joint)[:2]
        if not hasattr(joint, SCREW_STATE_PROP):
            joint.addProperty("App::PropertyString", SCREW_STATE_PROP, "FreeCAD", "Screw: turn and travel last seen")
            joint.setPropertyStatus(SCREW_STATE_PROP, "Hidden")
        text = "%r %r" % (float(state[0]), float(state[1]))
        if getattr(joint, SCREW_STATE_PROP) != text:
            setattr(joint, SCREW_STATE_PROP, text)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: screw state: %s\n" % error)


def screw_follow(asm):
    ""




    keep = []
    fixed = set(grounded(asm))
    for joint in mates(asm):
        if mate_type(joint) != "Screw" or getattr(joint, "Suppressed", False):
            continue
        try:
            pitch = float(getattr(joint, "Distance", 0.0))
            th, t, z, g1, g2 = _screw_now(joint)
            text = getattr(joint, SCREW_STATE_PROP, "") or ""
            if not text or abs(pitch) < 1e-12:
                keep.append((joint, (th, t)))
                continue
            th0, t0 = [float(v) for v in text.split()]
            dth = math.atan2(math.sin(th - th0), math.cos(th - th0))
            dt = t - t0
            c1, c2 = joint.Reference1[0], joint.Reference2[0]
            if abs(dth) > 1e-7:
                miss = pitch * dth / (2 * math.pi) - dt
                if abs(miss) > 1e-9:
                    comp, step = (c2, miss) if c2 not in fixed else (c1, -miss)
                    if comp in fixed:
                        continue
                    comp.Placement = App.Placement(comp.Placement.Base + z * step, comp.Placement.Rotation)
            elif abs(dt) > 1e-9:
                turn = math.degrees(2 * math.pi * dt / pitch)
                comp, turn, at = (c1, -turn, g1.Base) if c1 not in fixed else (c2, turn, g2.Base)
                if comp in fixed:
                    continue
                comp.Placement = App.Placement(V(), App.Rotation(z, turn), at).multiply(comp.Placement)
            keep.append((joint, _screw_now(joint)[:2]))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: screw: %s\n" % error)
    return keep


def _profile_values(joint):
    try:
        offset, flip_, lock = (getattr(joint, VALUE_PROP, "") or "").split()
        return float(offset), bool(int(flip_)), bool(int(lock))
    except ValueError:
        return 0.0, False, False


def _profile_finish(asm, joint):
    """After the solve on FreeCAD's Revolute (centres on one axis, profiles on each other):
    rectangles turn to the nearest square-on lie of their edges and hold it; with Lock rotation
    the turn is held as it is. Both are FreeCAD's Fixed from where the components now are."""
    import UtilsAssembly
    refs = [(joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])]
    p1, p2 = [profile(element(c, e)) for c, e in refs]
    lock = _profile_values(joint)[2]
    if p1 is None or p2 is None or getattr(joint, "Suppressed", False):
        return False
    rect = p1[0] == "rect"
    if not rect and not lock:
        return False
    if rect:
        n = p1[2]
        a, b = p1[3], p2[3]
        b = b - n * b.dot(n)
        if b.Length > 1e-9:
            angle = math.degrees(math.atan2(n.dot(b.cross(a)), b.dot(a)))   # turn b onto a about n
            angle = angle - 90.0 * round(angle / 90.0)                    # to the nearest square-on lie
            fixed = grounded(asm)
            comp, sign = (refs[1][0], 1.0) if refs[1][0] not in fixed else (refs[0][0], -1.0)
            if abs(angle) > 1e-9 and comp not in fixed:
                turn = App.Placement(V(), App.Rotation(n, sign * angle), p1[1])
                comp.Placement = turn.multiply(comp.Placement)
    before = _save_placements(asm)
    if joint.JointType != "Fixed":
        joint.Proxy.setJointType(joint, "Fixed")
        _restore_placements(asm, before)
    _here(joint)
    return True


# ----------------------------------------------------------------------------- Distance / Angle Range
def _faces(joint_or_refs):
    refs = joint_or_refs
    if not isinstance(refs, (list, tuple)):
        refs = [(r[0], r[1][0]) for r in (joint_or_refs.Reference1, joint_or_refs.Reference2)]
    return [geometry(element(c, e)) for c, e in refs]


def picked_value(kind, refs):
    ""

    g1, g2 = _faces(refs)
    if kind == "Distance Range":
        return g1[2].dot(g2[1] - g1[1])
    c = max(-1.0, min(1.0, g1[2].dot(g2[2])))
    return math.degrees(math.acos(c))


def _host_value(kind, host):
    """FreeCAD's own length or angle of the host joint, from its two frames as they are now."""
    f1 = host.Reference1[0].Placement.multiply(host.Placement1)
    f2 = host.Reference2[0].Placement.multiply(host.Placement2)
    z1 = f1.Rotation.multVec(V(0, 0, 1))
    if kind == "Distance Range":
        return z1.dot(f2.Base - f1.Base)
    x1, x2 = f1.Rotation.multVec(V(1, 0, 0)), f2.Rotation.multVec(V(1, 0, 0))
    return math.degrees(math.atan2(z1.dot(x1.cross(x2)), x1.dot(x2)))


def limit_host(asm, kind, refs, skip=None):
    """The joint letting the two picked components move the way the range measures: a Slider
    or Cylindrical along the faces' normal (distance), a Revolute or Cylindrical across them
    (angle). None when there is none: FreeCAD limits only such a joint."""
    (c1, e1), (c2, e2) = refs
    g1, g2 = _faces(refs)
    if g1 is None or g2 is None or g1[0] != "plane" or g2[0] != "plane":
        return None
    types = ("Slider", "Cylindrical") if kind == "Distance Range" else ("Revolute", "Cylindrical")
    for j in mates(asm):
        if j is skip or getattr(j, MATE_PROP, "") in LIMITS or getattr(j, "JointType", "") not in types \
                or getattr(j, "Suppressed", False):
            continue
        comps = {j.Reference1[0], j.Reference2[0]}
        if comps != {c1, c2}:

            # pin that is locked to the base (the Concentric is lever-pin, the range lever-base)
            a1, a2 = _rigid_set(asm, c1), _rigid_set(asm, c2)
            r1, r2 = j.Reference1[0], j.Reference2[0]
            if a1 & a2 or not ((r1 in a1 and r2 in a2) or (r1 in a2 and r2 in a1)):
                continue
        f1 = j.Reference1[0].Placement.multiply(j.Placement1)
        z = f1.Rotation.multVec(V(0, 0, 1))
        if kind == "Distance Range" and g1[2].cross(z).Length < 1e-6 and g1[2].cross(g2[2]).Length < 1e-6:
            return j
        if kind == "Angle Range" and abs(g1[2].dot(z)) < 1e-6 and abs(g2[2].dot(z)) < 1e-6:
            return j
    return None


def _rigid_set(asm, comp):
    """asmpkg351: the components held rigidly with comp: grounded ones together, and those joined by Lock
    (FreeCAD's Fixed joint), through any number of them."""
    fixed = set(grounded(asm))
    links = []
    for j in mates(asm):
        if getattr(j, "JointType", "") == "Fixed" and not getattr(j, "Suppressed", False) \
                and getattr(j, MATE_PROP, "") not in LIMITS:
            try:
                links.append((j.Reference1[0], j.Reference2[0]))
            except Exception:
                pass
    out = {comp} | (fixed if comp in fixed else set())
    grew = True
    while grew:
        grew = False
        for a, b in links:
            if (a in out) != (b in out):
                out |= {a, b}
                if (a in fixed) or (b in fixed):
                    out |= fixed
                grew = True
    return out


def _rate(kind, host, refs):
    """How the picked value changes per unit of the host's own value (+1 or -1), found by
    moving the host's second component a little along or about the host's axis."""
    f1 = host.Reference1[0].Placement.multiply(host.Placement1)
    z = f1.Rotation.multVec(V(0, 0, 1))
    comp, sign = host.Reference2[0], 1.0
    picked = {refs[0][0], refs[1][0]}
    if comp not in picked and host.Reference1[0] in picked:
        comp, sign = host.Reference1[0], -1.0    # asmpkg351: the host's other end is a pin: move the picked one
    keep = App.Placement(comp.Placement)
    before = picked_value(kind, refs)
    step = 1e-3 if kind == "Distance Range" else 1e-2
    move = App.Placement(z * step, App.Rotation()) if kind == "Distance Range" else \
        App.Placement(V(), App.Rotation(z, step), f1.Base)
    try:
        comp.Placement = move.multiply(keep)
        after = picked_value(kind, refs)
    finally:
        comp.Placement = keep
    return sign if after - before >= 0 else -sign


def make_limit(asm, kind, refs, low, high, joint=None):
    ""

    host = limit_host(asm, kind, refs)
    if host is None and kind == "Distance Range" and _free_range_ok(refs):
        return _make_free_range(asm, refs, low, high, joint)
    if host is None:
        what = "a Concentric with Lock rotation (or a Concentric)" if kind == "Distance Range" else \
            "a Concentric or Hinge"
        return None, "Mate the two components with %s first: FreeCAD limits only the joint that lets them move." % what
    now = picked_value(kind, refs)
    if kind == "Distance Range":
        now = abs(now)
    rate = _rate(kind, host, refs)
    if kind == "Distance Range" and picked_value(kind, refs) < 0:
        rate = -rate
    base = _host_value(kind, host)
    a, b = base + (float(low) - now) * rate, base + (float(high) - now) * rate
    if joint is None:
        joint = joint_group(asm).newObject("App::FeaturePython", "Limit")
        for prop, t, doc in ((MATE_PROP, "App::PropertyString", "Mate type"),
                             (ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             (LIMIT_PROP, "App::PropertyStringList", "Host joint, min, max"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "First pick"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Second pick")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, MATE_PROP, kind)
        joint.Label = _next_mate_name(asm, kind)
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
    joint.Reference1 = (refs[0][0], [refs[0][1]])
    joint.Reference2 = (refs[1][0], [refs[1][1]])
    setattr(joint, LIMIT_PROP, [host.Name, repr(float(low)), repr(float(high)), repr(min(a, b)), repr(max(a, b))])
    ok = solve(asm)
    return joint, (None if _mark(joint, ok) else OVER_MESSAGE)


def _free_range_ok(refs):
    g1, g2 = _faces(refs)
    return g1 is not None and g2 is not None and g1[0] == "plane" and g2[0] == "plane" \
        and g1[2].cross(g2[2]).Length < 1e-6 and refs[0][0] is not refs[1][0]


def _new_limit(asm, kind, joint):
    if joint is None:
        joint = joint_group(asm).newObject("App::FeaturePython", "Limit")
        for prop, t, doc in ((MATE_PROP, "App::PropertyString", "Mate type"),
                             (ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             (LIMIT_PROP, "App::PropertyStringList", "Host joint, min, max"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "First pick"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Second pick")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, MATE_PROP, kind)
        joint.Label = _next_mate_name(asm, kind)
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
    return joint


def _make_free_range(asm, refs, low, high, joint):
    ""


    joint = _new_limit(asm, "Distance Range", joint)
    joint.Reference1 = (refs[0][0], [refs[0][1]])
    joint.Reference2 = (refs[1][0], [refs[1][1]])
    lo, hi = sorted((float(low), float(high)))
    setattr(joint, LIMIT_PROP, ["", repr(lo), repr(hi), repr(lo), repr(hi)])
    _range_clamp(asm, joint)
    ok = solve(asm)
    return joint, (None if _mark(joint, ok) else OVER_MESSAGE)


def _range_clamp(asm, joint):
    """A free Distance range out of its range: the moving component goes along the faces'
    normal to the nearer end. True when something moved."""
    data = limit_values(joint)
    if data is None or data[0] is not None or getattr(joint, "Suppressed", False):
        return False
    refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    g1, _g2 = _faces(refs)
    v = picked_value("Distance Range", refs)
    if v is None or g1 is None:
        return False
    sign = 1.0 if v >= 0 else -1.0
    a = abs(v)
    # pkg309: the range keeps the side it was made on (or first held on), so a fast drag stops at the
    # Minimum instead of jumping through to the other side of the face
    side = _range_side(joint, sign if a >= data[1] - 1e-6 else None)
    if side is None:
        side = sign
    want = data[1] if a < data[1] or sign != side else data[2] if a > data[2] else a
    if abs(side * want - v) < 1e-9:
        return False
    d = g1[2] * (side * want - v)
    fixed = set(grounded(asm))
    comp, other = refs[1][0], refs[0][0]
    if comp in fixed:
        comp, other, d = refs[0][0], refs[1][0], -d
    if comp in fixed:
        return False
    for c in _carried(asm, comp, other):
        c.Placement = App.Placement(c.Placement.Base + d, c.Placement.Rotation)
    return True


RANGE_SIDE_PROP = "FwRangeSide"


def _range_side(joint, now=None):
    """pkg309: +1 or -1, the side of the faces a free Distance range is kept on; stored on the mate
    the first time it is held in range (now), so it lasts through save and reopen."""
    try:
        if RANGE_SIDE_PROP in joint.PropertiesList:
            return 1.0 if float(getattr(joint, RANGE_SIDE_PROP)) >= 0 else -1.0
        if now is None:
            return None
        joint.addProperty("App::PropertyFloat", RANGE_SIDE_PROP, "FreeWorks",
                          "The side of the faces this Distance range keeps", 4)
        setattr(joint, RANGE_SIDE_PROP, float(now))
        return float(now)
    except Exception as _fw_err:
        _fw_log("asmcore.py:range side", _fw_err)
        return now


def _carried(asm, comp, other):
    ""



    fixed = set(grounded(asm))
    by = {}
    for j in list(mates(asm)) + list(parts(asm)):
        if getattr(j, "Suppressed", False):
            continue
        rs = []
        for prop in ("Reference1", "Reference2"):
            r = getattr(j, prop, None)
            if r and r[0] is not None:
                rs.append(r[0])
        for r in rs:
            by.setdefault(r, set()).update(x for x in rs if x is not r)
    out, todo = [comp], [comp]
    while todo:
        c = todo.pop()
        for n in by.get(c, ()):
            if n in out or n in fixed or n is other:
                continue
            out.append(n)
            todo.append(n)
    return out


def _free_move(asm, joint, target):
    """A free Distance range's value: the second component goes along the first face's normal."""
    refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    g1, _g2 = _faces(refs)
    now = picked_value("Distance Range", refs)
    if g1 is None or now is None:
        return False
    d = g1[2] * (float(target) - now)
    fixed = set(grounded(asm))
    comp, other = refs[1][0], refs[0][0]
    if comp in fixed:
        comp, other, d = refs[0][0], refs[1][0], -d
    if comp in fixed:
        return False
    if d.Length > 1e-9:
        for c in _carried(asm, comp, other):      # pkg309: what is mated to it goes along
            c.Placement = App.Placement(c.Placement.Base + d, c.Placement.Rotation)
    return solve(asm)


def range_clamp(asm):
    """After a drag: free Distance ranges back inside their ends (the assembly solves again)."""
    moved = False
    for joint in mates(asm):
        if getattr(joint, MATE_PROP, "") == "Distance Range":
            moved = _range_clamp(asm, joint) or moved
        elif getattr(joint, MATE_PROP, "") == "Hinge":
            moved = _hinge_clamp(asm, joint) or moved
    if moved:
        solve(asm)
    return moved


def limit_move(asm, joint, kind, target):
    ""


    data = limit_values(joint)
    if data is not None and data[0] is None and kind == "Distance Range":
        return _free_move(asm, joint, target)
    if data is None or data[0] is None:
        return False
    host = data[0]
    refs = [(joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])]
    now = picked_value(kind, refs)
    if now is None:
        return False
    d = (float(target) - now) * _rate(kind, host, refs)
    if abs(d) < 1e-9:
        return True
    f1 = host.Reference1[0].Placement.multiply(host.Placement1)
    z = f1.Rotation.multVec(V(0, 0, 1))
    comp = host.Reference2[0]
    picked = {refs[0][0], refs[1][0]}
    if comp in set(grounded(asm)) or (comp not in picked and host.Reference1[0] in picked):
        comp, d = host.Reference1[0], -d    # asmpkg351: not a pin the host's other end is held to
    move = App.Placement(z * d, App.Rotation()) if kind == "Distance Range" else \
        App.Placement(V(), App.Rotation(z, d), f1.Base)
    comp.Placement = move.multiply(comp.Placement)
    solve(asm)
    return True


def limit_values(joint):
    """(host, low, high, host min, host max) of a range mate."""
    data = list(getattr(joint, LIMIT_PROP, []) or [])
    if len(data) < 5:
        return None
    host = joint.Document.getObject(data[0]) if data[0] else None
    return (host, float(data[1]), float(data[2]), float(data[3]), float(data[4]))


def sync_limits(asm):
    """Range mates set their host joints' limits; a host whose range mates are gone or
    suppressed gets its limits taken off again (only those a range mate set)."""
    wanted = {}
    for joint in mates(asm):
        kind = getattr(joint, MATE_PROP, "")
        if kind not in LIMITS or getattr(joint, "Suppressed", False):
            continue
        data = limit_values(joint)
        if data is None or data[0] is None:
            continue
        wanted.setdefault(data[0].Name, []).append((kind, joint.Name, data[3], data[4]))
    for host in joint_group(asm).Group:
        set_by = list(getattr(host, LIMITED_PROP, []) or [])
        want = wanted.get(host.Name, [])
        if not want and not set_by:
            continue
        if not hasattr(host, LIMITED_PROP):
            host.addProperty("App::PropertyStringList", LIMITED_PROP, "FreeCAD", "Range mates limiting this joint")
            host.setPropertyStatus(LIMITED_PROP, "Hidden")
        kinds = {k for k, _n, _a, _b in want}
        for kind, (enable_min, enable_max, lo, hi) in (
                ("Distance Range", ("EnableLengthMin", "EnableLengthMax", "LengthMin", "LengthMax")),
                ("Angle Range", ("EnableAngleMin", "EnableAngleMax", "AngleMin", "AngleMax"))):
            if not hasattr(host, enable_min):
                continue
            mine = [w for w in want if w[0] == kind]
            if mine:
                setattr(host, lo, max(w[2] for w in mine))
                setattr(host, hi, min(w[3] for w in mine))
                setattr(host, enable_min, True)
                setattr(host, enable_max, True)
            elif any(name.startswith(kind) for name in set_by):
                setattr(host, enable_min, False)
                setattr(host, enable_max, False)
        setattr(host, LIMITED_PROP, ["%s %s" % (k, n) for k, n, _a, _b in want])


def limit_holds(joint, tol=1e-3):
    data = limit_values(joint)
    if data is None:
        return True
    refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    kind = getattr(joint, MATE_PROP)
    try:
        v = picked_value(kind, refs)
    except Exception:
        return True
    v = abs(v) if kind == "Distance Range" else v
    slack = tol * 10 if kind == "Distance Range" else 0.05
    return data[1] - slack <= v <= data[2] + slack


# ----------------------------------------------------------------------------- Symmetric
def symmetric_ok(plane, entities):
    """A flat face for the symmetry plane; two flat faces parallel to it, on two other
    components (one of them may carry the plane)."""
    if plane is None or len(entities) != 2 or entities[0][0] is entities[1][0]:
        return False
    gs = [geometry(element(c, e)) for c, e in [plane] + list(entities)]
    if any(g is None or g[0] != "plane" for g in gs):
        return False
    return all(g[2].cross(gs[0][2]).Length < 1e-6 for g in gs[1:])


def _side(plane, ref):
    """Signed distance of the picked flat face from the symmetry plane."""
    p, g = geometry(element(*plane)), geometry(element(*ref))
    return p[2].dot(g[1] - p[1])


def make_symmetric(asm, plane, entities, joint=None):
    ""



    import UtilsAssembly
    JO = _ja()
    before = _save_placements(asm)
    if joint is None:
        joint = joint_group(asm).newObject("App::FeaturePython", "Mate")
        _joint_proxy(JO, joint, JO.JointTypes.index("Distance"))
        if App.GuiUp:
            JO.ViewProviderJoint(joint.ViewObject)
        for prop, kind, doc in ((MATE_PROP, "App::PropertyString", "Mate type"),
                                (LOCK_PROP, "App::PropertyBool", "Concentric: Lock rotation"),
                                (ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                                (SYMMETRIC_PROP, "App::PropertyStringList", "Symmetric: first entity, sign")):
            joint.addProperty(kind, prop, "FreeCAD", doc)
        setattr(joint, MATE_PROP, "Symmetric")
        joint.Label = _next_mate_name(asm, "Symmetric")
    first, second = entities
    if second[0] is plane[0]:
        first, second = second, first       # the held entity is the one off the plane's component
    setattr(joint, SYMMETRIC_PROP, ["%s %s" % (first[0].Name, first[1]), "1"])
    joint.Proxy.setJointConnectors(joint, [[plane[0], [plane[1]] * 2], [second[0], [second[1]] * 2]])
    _restore_placements(asm, before)
    _quiet(joint)
    ok = False
    for sign in ("1", "-1"):        # FreeCAD's Distance may count along either frame's z
        setattr(joint, SYMMETRIC_PROP, [getattr(joint, SYMMETRIC_PROP)[0], sign])
        r = solve(asm, before)
        if r and symmetric_holds(joint):
            ok = True
            break
        _restore_placements(asm, before)
    return joint, _mark(joint, ok)


def symmetric_first(joint):
    data = list(getattr(joint, SYMMETRIC_PROP, []) or [])
    if not data:
        return None, 1.0
    name, elem = data[0].split(" ", 1)
    return (joint.Document.getObject(name), elem), float(data[1]) if len(data) > 1 else 1.0


def sync_symmetric(asm):
    """Each Symmetric mate's distance from the first entity's side of the plane, now."""
    for joint in mates(asm):
        if getattr(joint, MATE_PROP, "") != "Symmetric" or getattr(joint, "Suppressed", False):
            continue
        first, sign = symmetric_first(joint)
        if first is None or first[0] is None:
            continue
        plane = (joint.Reference1[0], joint.Reference1[1][0])
        try:
            want = -_side(plane, first) * sign
            g = geometry(element(joint.Reference2[0], joint.Reference2[1][0]))
            if g is not None and g[0] == "axis" and abs(want) > g[3]:
                want -= g[3] if want > 0 else -g[3]   # FreeCAD's Distance measures to a cylinder's surface
        except Exception:
            continue
        if abs(float(joint.Distance) - want) > 1e-9:
            joint.Distance = want


def symmetric_holds(joint, tol=1e-3):
    first, _sign = symmetric_first(joint)
    if first is None or first[0] is None:
        return True
    plane = (joint.Reference1[0], joint.Reference1[1][0])
    second = (joint.Reference2[0], joint.Reference2[1][0])
    try:
        return abs(_side(plane, first) + _side(plane, second)) < tol * 10
    except Exception:
        return True


def width_ok(width, tab):
    ""


    if len(width) != 2 or len(tab) != 2 or width[0][0] is not width[1][0] or tab[0][0] is not tab[1][0] \
            or width[0][0] is tab[0][0]:
        return False
    gs = [geometry(element(c, e)) for c, e in width + tab]
    if any(g is None for g in gs):
        return False
    n = gs[0][2]
    if round_tab(tab):
        return all(g[0] == "plane" and g[2].cross(n).Length < 1e-6 for g in gs[:2]) \
            and gs[2][0] == "axis" and abs(V(gs[2][2]).normalize().dot(V(n).normalize())) < 1e-6
    if any(g[0] != "plane" for g in gs):
        return False
    return all(g[2].cross(n).Length < 1e-6 for g in gs)


def round_tab(tab):
    """A Width tab that is one cylindrical face (stored twice)."""
    try:
        return len(tab) == 2 and tab[0][0] is tab[1][0] and tab[0][1] == tab[1][1] \
            and geometry(element(*tab[0]))[0] == "axis"
    except Exception:
        return False


def width_offsets(width, tab, mode="centered", value=50.0, flip=False):
    """(along the first width face's normal: from it to where the tab's middle goes,
    along the first tab face's normal: from it to the tab's middle). Points in the components'
    own placement as they are now."""
    a, b, c, d = [geometry(element(comp, e)) for comp, e in width + tab]
    n = a[2]
    gap = n.dot(b[1] - a[1])            # signed: the second width face from the first
    thick = 2.0 * c[3] if c[0] == "axis" else abs(c[2].dot(d[1] - c[1]))
    if mode == "dimension":
        s = float(value) + thick / 2.0
        s = gap - s if flip else s
    elif mode == "percent":
        travel = abs(gap) - thick
        s = thick / 2.0 + travel * float(value) / 100.0
        s = abs(gap) - s if flip else s
    else:
        s = abs(gap) / 2.0
    s = s if gap >= 0 else -s
    if c[0] == "axis":
        return s, 0.0
    return s, c[2].dot(d[1] - c[1]) / 2.0


def _round_width(asm, joint, width, tab, mode, value, flip, before):
    """Width with a cylindrical tab: the axis on the mid-plane (or where the constraint puts it).
    Free: FreeCAD's Perpendicular (the axis along the width faces) and the clamp; otherwise
    FreeCAD's Distance from the first width face to the cylinder, which counts to its surface."""
    import UtilsAssembly
    want = "Perpendicular" if mode == "free" else "Distance"
    if joint.JointType != want:
        joint.Proxy.setJointType(joint, want)
    joint.Proxy.setJointConnectors(joint, [[width[0][0], [width[0][1]] * 2], [tab[0][0], [tab[0][1]] * 2]])
    _restore_placements(asm, before)
    joint.Offset1 = joint.Offset2 = App.Placement()
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2463", _fw_err)
    _quiet(joint)
    if mode == "free":
        ok = solve(asm, before)
        return joint, _mark(joint, ok)
    t, _z = width_offsets(width, tab, mode, value, flip)
    r = geometry(element(*tab[0]))[3]
    ok = False
    for d in (t - r if t >= 0 else t + r, -(t - r) if t >= 0 else -(t + r)):
        joint.Distance = d if abs(d) > 1e-7 else 1e-7     # FreeCAD's solver fails at exactly 0
        ok = solve(asm, before) and _round_holds(joint)
        if ok:
            break
        _restore_placements(asm, before)
    return joint, _mark(joint, ok)


def _round_holds(joint, tol=1e-3):
    """Width with a cylindrical tab: the axis along the width faces, where the constraint puts it."""
    data = width_values(joint)
    if data is None or not round_tab(data[1]):
        return True
    width, tab, mode, value, flip = data
    a = geometry(element(*width[0]))
    g = geometry(element(*tab[0]))
    n = V(a[2]).normalize()
    if abs(V(g[2]).normalize().dot(n)) > tol:
        return False
    if mode == "free":
        return True
    t, _z = width_offsets(width, tab, mode, value, flip)
    return abs(n.dot(g[1] - a[1]) - t) < tol * 10


def make_width(asm, width, tab, mode="centered", value=50.0, flip=False, joint=None):
    ""


    import UtilsAssembly
    JO = _ja()
    before = _save_placements(asm)
    if joint is None:
        joint = joint_group(asm).newObject("App::FeaturePython", "Mate")
        _joint_proxy(JO, joint, JO.JointTypes.index("Distance"))
        if App.GuiUp:
            JO.ViewProviderJoint(joint.ViewObject)
        for prop, kind, doc in ((MATE_PROP, "App::PropertyString", "Mate type"),
                                (LOCK_PROP, "App::PropertyBool", "Concentric: Lock rotation"),
                                (ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                                (WIDTH_PROP, "App::PropertyStringList", "Width: picks and constraint")):
            joint.addProperty(kind, prop, "FreeCAD", doc)
        setattr(joint, MATE_PROP, "Width")
        joint.Label = _next_mate_name(asm, "Width")
    else:
        _unsuppress(joint)
        if not hasattr(joint, WIDTH_PROP):
            joint.addProperty("App::PropertyStringList", WIDTH_PROP, "FreeCAD", "Width: picks and constraint")
        setattr(joint, MATE_PROP, "Width")
    setattr(joint, WIDTH_PROP, ["%s %s" % (c.Name, e) for c, e in width + tab] + [mode, repr(float(value)), str(int(bool(flip)))])
    if round_tab(tab):
        return _round_width(asm, joint, width, tab, mode, value, flip, before)
    want = "Parallel" if mode == "free" else "Distance"
    if joint.JointType != want:
        joint.Proxy.setJointType(joint, want)
    if mode == "free":
        # Free: the tab's faces parallel to the groove's (FreeCAD's Parallel), kept between the

        joint.Proxy.setJointConnectors(joint, [[width[0][0], [width[0][1]] * 2], [tab[0][0], [tab[0][1]] * 2]])
        _restore_placements(asm, before)
        joint.Offset1 = joint.Offset2 = App.Placement()
        try:
            joint.Proxy.updateJCSPlacements(joint)
        except Exception as _fw_err:
            _fw_log("asmcore.py:2536", _fw_err)
        _quiet(joint)
        ok = solve(asm, before)
        if not ok:
            joint.Proxy.flipOnePart(joint)
            ok = solve(asm, before)
        return joint, _mark(joint, ok)
    joint.Distance = 0.0
    joint.Proxy.setJointConnectors(joint, [[width[0][0], [width[0][1]] * 2], [tab[0][0], [tab[0][1]] * 2]])
    _restore_placements(asm, before)
    s1, s2 = width_offsets(width, tab, mode, value, flip)
    # along each frame's own z (FreeCAD's frame on a face may face either way)
    joint.Offset1 = joint.Offset2 = App.Placement()
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2552", _fw_err)
    n1 = geometry(element(*width[0]))[2]
    n2 = geometry(element(*tab[0]))[2]
    z1 = width[0][0].Placement.multiply(joint.Placement1).Rotation.multVec(V(0, 0, 1))
    z2 = tab[0][0].Placement.multiply(joint.Placement2).Rotation.multVec(V(0, 0, 1))
    joint.Offset1 = App.Placement(V(0, 0, s1 * (1 if z1.dot(n1) > 0 else -1)), App.Rotation())
    joint.Offset2 = App.Placement(V(0, 0, s2 * (1 if z2.dot(n2) > 0 else -1)), App.Rotation())
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2562", _fw_err)
    _quiet(joint)
    ok = solve(asm, before)
    if not ok:
        joint.Proxy.flipOnePart(joint)
        ok = solve(asm, before)
    return joint, _mark(joint, ok)


def width_values(joint):
    """(width picks, tab picks, mode, value, flip) of a Width mate."""
    data = list(getattr(joint, WIDTH_PROP, []) or [])
    if len(data) < 7:
        return None
    doc = joint.Document
    picks = []
    for item in data[:4]:
        name, elem = item.split(" ", 1)
        picks.append((doc.getObject(name), elem))
    return picks[:2], picks[2:4], data[4], float(data[5]), bool(int(data[6]))


def _width_range(joint):
    """Width Free: (tab component, normal, where the tab's middle is, lowest, highest) along the
    first width face's normal, or None."""
    data = width_values(joint)
    if data is None or data[2] != "free":
        return None
    width, tab = data[0], data[1]
    a, b, c, d = [geometry(element(comp, e)) for comp, e in width + tab]
    n = V(a[2]).normalize()
    gap = n.dot(b[1] - a[1])
    if c[0] == "axis":          # a cylindrical tab: its axis between the faces, a radius off each
        thick = 2.0 * c[3]
        mid = n.dot(c[1] - a[1])
    else:
        thick = abs(n.dot(d[1] - c[1]))
        mid = n.dot((c[1] + d[1]) * 0.5 - a[1])
    lo, hi = sorted((thick / 2.0 * (1 if gap >= 0 else -1), gap - thick / 2.0 * (1 if gap >= 0 else -1)))
    return tab[0][0], width[0][0], n, mid, lo, hi


def width_free_clamp(asm):
    """Width Free: a tab pushed past the groove's faces is put back against the face it went
    past. True when something moved."""
    fixed = set(grounded(asm))
    moved = False
    for joint in mates(asm):
        if mate_type(joint) != "Width" or getattr(joint, "Suppressed", False):
            continue
        try:
            r = _width_range(joint)
        except Exception:
            r = None
        if r is None:
            continue
        tab, groove, n, mid, lo, hi = r
        want = min(max(mid, lo), hi)
        if abs(want - mid) < 1e-9:
            continue
        if tab not in fixed:
            tab.Placement = App.Placement(tab.Placement.Base + n * (want - mid), tab.Placement.Rotation)
        elif groove not in fixed:
            groove.Placement = App.Placement(groove.Placement.Base - n * (want - mid), groove.Placement.Rotation)
        else:
            continue
        moved = True
    return moved


def _planes_meet(joint, tol=1e-3):
    """The two frames' planes on each other (Width: mid-plane on mid-plane)."""
    try:
        f1 = joint.Reference1[0].Placement.multiply(joint.Placement1)
        f2 = joint.Reference2[0].Placement.multiply(joint.Placement2)
    except Exception:
        return True
    z1, z2 = f1.Rotation.multVec(V(0, 0, 1)), f2.Rotation.multVec(V(0, 0, 1))
    return z1.cross(z2).Length < tol and abs(z1.dot(f2.Base - f1.Base)) < tol * 10


def _frames_meet(joint, tol=1e-3):
    """The two frames' origins on each other and their z axes in line (Profile Center)."""
    try:
        f1 = joint.Reference1[0].Placement.multiply(joint.Placement1)
        f2 = joint.Reference2[0].Placement.multiply(joint.Placement2)
    except Exception:
        return True
    z1, z2 = f1.Rotation.multVec(V(0, 0, 1)), f2.Rotation.multVec(V(0, 0, 1))
    return (f1.Base - f2.Base).Length < tol * 10 and z1.cross(z2).Length < tol


def _axis_now(comp, elem):
    g = geometry(element(comp, elem))
    return (g[1], V(g[2]).normalize()) if g is not None and g[0] == "axis" else None


def _frame(comp, joint, which):
    return comp.Placement.multiply(getattr(joint, "Placement%d" % which))


def cross(joint):
    ""






    a = _axis_now(joint.Reference1[0], joint.Reference1[1][0])
    b = _axis_now(joint.Reference2[0], joint.Reference2[1][0])
    if a is None or b is None:
        return False
    u, v = a[1], b[1]
    arm1 = u.cross(v)
    if arm1.Length < 1e-6:          # shafts in line: any arm square to them
        arm1 = u.cross(V(1, 0, 0)) if abs(u.x) < 0.9 else u.cross(V(0, 1, 0))
    arm1.normalize()
    arm2 = v.cross(arm1).normalize()
    joint.Offset1 = joint.Offset2 = App.Placement()
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2685", _fw_err)
    for which, comp, arm in ((1, joint.Reference1[0], arm1), (2, joint.Reference2[0], arm2)):
        local = _frame(comp, joint, which).Rotation.inverted().multVec(arm)
        setattr(joint, "Offset%d" % which, App.Placement(V(), App.Rotation(V(0, 0, 1), local)))
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2692", _fw_err)
    return True


JOINT_POINT_PROP = "FwJointPoint"


def joint_point(joint):
    """The Universal Joint's joint point (a vector), None when not defined."""
    ref = getattr(joint, JOINT_POINT_PROP, None)
    if not ref or ref[0] is None or not ref[1]:
        return None
    s = element(ref[0], ref[1][0])
    if s is None:
        return None
    if s.ShapeType == "Vertex":
        return V(s.Point)
    g = geometry(s)
    return V(g[1]) if g is not None else V(s.CenterOfMass)


def set_joint_point(asm, joint, ref):
    """Define joint point: the two shafts' axes are put through the point (each free shaft moves
    square to its axis), then the assembly solves. ref None takes the point off."""
    if not hasattr(joint, JOINT_POINT_PROP):
        joint.addProperty("App::PropertyXLinkSubHidden", JOINT_POINT_PROP, "FreeCAD", "Joint point")
    if ref is None:
        setattr(joint, JOINT_POINT_PROP, None)
        return _mark(joint, solve(asm))
    setattr(joint, JOINT_POINT_PROP, (ref[0], [ref[1]]))
    p = joint_point(joint)
    fixed = set(grounded(asm))
    for r in (joint.Reference1, joint.Reference2):
        comp = r[0]
        a = _axis_now(comp, r[1][0])
        if a is None or comp in fixed or comp is ref[0]:
            continue
        d = p - a[0]
        d = d - a[1] * d.dot(a[1])
        if d.Length > 1e-9:
            comp.Placement = App.Placement(comp.Placement.Base + d, comp.Placement.Rotation)
    cross(joint)
    ok = solve(asm)
    return _mark(joint, ok and _through_point(joint))


def _through_point(joint, tol=1e-3):
    p = joint_point(joint)
    if p is None:
        return True
    for r in (joint.Reference1, joint.Reference2):
        a = _axis_now(r[0], r[1][0])
        if a is None:
            return False
        d = p - a[0]
        if (d - a[1] * d.dot(a[1])).Length > tol * 10:
            return False
    return True


def _arms_square(joint, tol=1e-3):
    try:
        z1 = _frame(joint.Reference1[0], joint, 1).Rotation.multVec(V(0, 0, 1))
        z2 = _frame(joint.Reference2[0], joint, 2).Rotation.multVec(V(0, 0, 1))
    except Exception:
        return True
    return abs(z1.dot(z2)) < tol * 10


def _here(joint):
    """FreeCAD's solve holds a screw's turn and travel from where its two frames meet: the
    second frame is put on the first as the components are now, so they start from here."""
    c1, c2 = joint.Reference1[0], joint.Reference2[0]
    joint.Offset2 = App.Placement()
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2769", _fw_err)
    raw2 = joint.Placement2
    first = c1.Placement.multiply(joint.Placement1)
    joint.Offset2 = raw2.inverse().multiply(c2.Placement.inverse()).multiply(first)
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2776", _fw_err)
    _screw_store(joint)


def _on_axis(asm, joint, comp, elem):
    """True when comp is already held on the axis of its picked round face or edge: fixed, or
    by a Concentric or Hinge of its own on that axis."""
    if comp in grounded(asm):
        return True
    g = geometry(element(comp, elem))
    if g is None or g[0] != "axis":
        return False
    for other in mates(asm):
        if other is joint or getattr(other, "Suppressed", False) or mate_type(other) not in ("Concentric", "Hinge"):
            continue
        for ref in (other.Reference1, other.Reference2):
            if ref[0] is comp:
                h = geometry(element(comp, ref[1][0]))
                if h is not None and h[0] == "axis" and h[2].cross(g[2]).Length < 1e-6 \
                        and (h[1] - g[1]).cross(g[2]).Length < 1e-6:
                    return True
    return False


def rezero(asm):
    """Before a drag: each Screw mate counts its turn and travel from where it is now (FreeCAD's
    solve at the drag start would otherwise pull it back to where its frames meet)."""
    for joint in mates(asm):
        if mate_type(joint) == "Screw" and not getattr(joint, "Suppressed", False):
            _here(joint)


def rack_first(joint):
    ""
    r1, r2 = getattr(joint, "Reference1", None), getattr(joint, "Reference2", None)
    if not r1 or not r2 or r1[0] is None or r2[0] is None or not r1[1] or not r2[1]:
        return []           # no picks yet (add_mate sets the value again once they are in)
    refs = [(r1[0], r1[1][0]), (r2[0], r2[1][0])]
    g = geometry(element(*refs[0]))
    if g is None or g[0] != "line":
        refs.reverse()
        joint.Proxy.setJointConnectors(joint, [[c, [e, e]] for c, e in refs])
    return refs


def _hidden(asm, joint, kind, refs):
    JO = _ja()
    part = joint_group(asm).newObject("App::FeaturePython", "MatePart")
    _joint_proxy(JO, part, JO.JointTypes.index(kind))
    if App.GuiUp:
        JO.ViewProviderJoint(part.ViewObject)
    part.addProperty("App::PropertyString", PART_OF_PROP, "FreeCAD", "Part of this mate")
    setattr(part, PART_OF_PROP, joint.Name)
    part.setPropertyStatus(PART_OF_PROP, "Hidden")
    part.Label = "%s %s" % (joint.Label.split(" (")[0], kind)
    part.Proxy.setJointConnectors(part, refs)
    part.Suppressed = bool(getattr(joint, "Suppressed", False))
    _quiet(part, tree=False)
    return part


def sync_parts(asm):
    """Hidden joints follow their mate: gone with it, suppressed with it, dropped when the
    mate became another type."""
    doc = asm.Document
    for part in parts(asm):
        joint = doc.getObject(getattr(part, PART_OF_PROP))
        if joint is None or mate_type(joint) not in ("Rack Pinion", "Screw", "Slot", "Path Mate"):
            doc.removeObject(part.Name)
            continue
        off = bool(getattr(joint, "Suppressed", False))
        if part.Suppressed != off:
            part.Suppressed = off


FLEX_SYNC = ("Distance", "Distance2", "Angle", "Offset1", "Offset2", "Placement1", "Placement2", "Activated",
             "Suppressed", "EnableLengthMin", "EnableLengthMax", "LengthMin", "LengthMax", "EnableAngleMin",
             "EnableAngleMax", "AngleMin", "AngleMax", "Detach1", "Detach2")


def sync_flexible(asm):
    _sync_flexible(asm)             # (making the copies again takes the holds away)
    _keep_flexible_holds(asm)


def _sync_flexible(asm):
    ""


    for sub in components(asm):
        if not is_flexible(sub):
            continue
        src = getattr(sub, "LinkedObject", None)
        if src is None:
            continue
        # FreeCAD copies the subassembly's own joints only: not a range mate's row (its limits sit
        # on the joint it limits), not a hold. Counting those rows made the copies anew at every
        # solve, which put the components back where the file has them (a limited slider froze).
        real = [j for j in joint_group(src).Group if hasattr(j, "JointType") and not hasattr(j, "ObjectToGround")]
        copies = [c for g in (getattr(sub, "Group", []) or []) if g.TypeId == "Assembly::JointGroup" for c in g.Group]
        order = real if len(real) == len(copies) else [j for j in real if not getattr(j, "Suppressed", False)]
        theirs = {j.Label: j for j in order}
        stale = len(copies) != len(order)
        same_doc = src.Document is sub.Document     # a virtual subassembly: the copies' labels were made unique
        for i, copy in enumerate(copies):
            j = theirs.get(copy.Label)
            if j is None and i < len(order) and (same_doc or len(copies) == len(order)):
                j = order[i]        # FreeCAD names its copies anew (Mate156): the file's order
            if j is None:
                stale = True
                break
            changed = []
            for prop in FLEX_SYNC:
                if not hasattr(j, prop) or not hasattr(copy, prop):
                    continue
                try:
                    v, old = getattr(j, prop), getattr(copy, prop)
                    if not (old.isSame(v, 1e-12) if hasattr(old, "isSame") else old == v):
                        changed.append((prop, v))
                except Exception as _fw_err:
                    _fw_log("asmcore.py:2890", _fw_err)
            if changed and not _copy_props(copy, changed):
                stale = True
                break
        if stale:
            # FreeCAD makes its copies when the subassembly turns flexible: made again from the file
            try:
                sub.Rigid = True
                sub.recompute()
                sub.Rigid = False
                sub.recompute()
            except Exception as error:
                App.Console.PrintLog("FreeCAD: flexible subassembly: %s\n" % error)


def _copy_props(copy, changed):
    """A mate's copy in a flexible subassembly takes its file's values ([(property, value)]): the
    copy names the same faces of the same parts, so its frames (Placement1/2, relative to each
    part) are the file's too. FreeCAD's copy of a subassembly from another file keeps its second
    frame at the part's origin (four copies of a piston subassembly: each pin went to the rod's
    big end), and making the copies again gave the same frame and moved the subassembly's
    components back to the file's places at every solve. True when set."""
    JO = _ja()
    saved = getattr(JO, "solveIfAllowed", None)
    if saved is not None:
        JO.solveIfAllowed = lambda *a, **k: None    # an Offset set solves: solved right after
    try:
        for prop, value in changed:
            setattr(copy, prop, value)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: flexible subassembly mate %s: %s\n" % (copy.Label, error))
        return False
    finally:
        if saved is not None:
            JO.solveIfAllowed = saved


# ----------------------------------------------------------------------------- Hinge
def _prefix(element):
    return element.rsplit(".", 1)[0] + "." if "." in element else ""


def circle_edge(comp, elem):
    """A circular edge of the picked round face (or the picked circular edge): its name in comp."""
    picked = element(comp, elem)
    if picked is None:
        return None
    if picked.ShapeType == "Edge":
        return elem
    circles = [e for e in picked.Edges if e.Curve.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle")]
    if not circles:
        return None
    want = circles[0]
    prefix = _prefix(elem)
    for i in range(1, 10000):
        name = "%sEdge%d" % (prefix, i)
        try:
            e = comp.getSubObject(name)
        except Exception:
            e = None
        if e is None or e.isNull():
            break
        if e.isSame(want) or (e.Curve.TypeId == want.Curve.TypeId and
                              (V(e.Curve.Center) - V(want.Curve.Center)).Length < 1e-7 and
                              abs(e.Curve.Radius - want.Curve.Radius) < 1e-7):
            return name
    return None


def make_hinge(asm, joint, planes, limits=None):
    ""


    import UtilsAssembly
    before = _save_placements(asm)
    refs = [(joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])]
    by_comp = {c: e for c, e in planes}
    new_refs, offsets = [], []
    for comp, elem in refs:
        edge = circle_edge(comp, elem)
        face = by_comp.get(comp)
        if edge is None or face is None:
            return False
        g = geometry(element(comp, edge))
        p = geometry(element(comp, face))
        if g is None or p is None or p[0] != "plane":
            return False
        d = (p[1] - g[1]).dot(g[2])
        new_refs.append([comp, [edge, edge]])
        offsets.append(d)
    _unsuppress(joint)
    if joint.JointType != "Revolute":
        joint.Proxy.setJointType(joint, "Revolute")
    setattr(joint, MATE_PROP, "Hinge")
    joint.Label = _next_mate_name(asm, "Hinge") if not joint.Label.startswith("Hinge") else joint.Label
    joint.Proxy.setJointConnectors(joint, new_refs)
    joint.Offset1 = App.Placement(V(0, 0, offsets[0]), App.Rotation())
    joint.Offset2 = App.Placement(V(0, 0, offsets[1]), App.Rotation())
    set_limits(joint, limits)
    try:
        joint.Proxy.updateJCSPlacements(joint)
    except Exception as _fw_err:
        _fw_log("asmcore.py:2969", _fw_err)
    ok = solve(asm, before)
    if not ok:
        joint.Proxy.flipOnePart(joint)
        ok = solve(asm, before)
    return _mark(joint, ok)


def set_limits(joint, limits):
    on = limits is not None
    for prop in ("EnableAngleMin", "EnableAngleMax"):
        if hasattr(joint, prop):
            setattr(joint, prop, on)
    if on:
        joint.AngleMin = float(limits[0])
        joint.AngleMax = float(limits[1])


HINGE_ANGLE_PROP = "FwHingeAngle"     # Hinge: the Angle Selections ("component element" twice)


def hinge_angle_refs(joint):
    out = []
    for text in list(getattr(joint, HINGE_ANGLE_PROP, []) or []):
        name, elem = text.split(" ", 1)
        comp = joint.Document.getObject(name)
        if comp is not None:
            out.append((comp, elem))
    return out if len(out) == 2 else []


def hinge_angle(joint, refs):
    ""

    f1 = joint.Reference1[0].Placement.multiply(joint.Placement1)
    z = f1.Rotation.multVec(V(0, 0, 1))
    by = {c: e for c, e in refs}
    g1 = geometry(element(joint.Reference1[0], by[joint.Reference1[0]]))
    g2 = geometry(element(joint.Reference2[0], by[joint.Reference2[0]]))
    n1, n2 = V(g1[2]).normalize(), V(g2[2]).normalize()
    return math.degrees(math.atan2(z.dot(n1.cross(n2)), n1.dot(n2)))


def hinge_limits(joint, limits, angle_refs=None):
    """Specify angle limits. With Angle Selections the limits are the angle between those faces,
    put onto FreeCAD's Revolute's own angle (its zero is its frames); else its own angle."""
    if not hasattr(joint, HINGE_ANGLE_PROP):
        joint.addProperty("App::PropertyStringList", HINGE_ANGLE_PROP, "FreeCAD", "Hinge: Angle Selections")
        joint.setPropertyStatus(HINGE_ANGLE_PROP, "Hidden")
    refs = list(angle_refs or [])
    comps = {joint.Reference1[0], joint.Reference2[0]}
    if len(refs) != 2 or {c for c, _e in refs} != comps:
        refs = []
    setattr(joint, HINGE_ANGLE_PROP, ["%s %s" % (c.Name, e) for c, e in refs])
    if limits is None or not refs:
        set_limits(joint, limits)
        return
    raw = hinge_angle(joint, refs)
    sign = -1.0 if raw < 0 else 1.0
    now = raw * sign
    own = _host_value("Angle Range", joint)
    ends = sorted(own + sign * (float(v) - now) for v in limits)
    set_limits(joint, (ends[0], ends[1]))


def _hinge_holds(joint, tol=1e-3):
    """One axis for the two circular edges (the faces' coincidence is FreeCAD's Revolute's own),
    and the angle inside its limits when they are on."""
    try:
        a = geometry(element(joint.Reference1[0], joint.Reference1[1][0]))
        b = geometry(element(joint.Reference2[0], joint.Reference2[1][0]))
    except Exception:
        return True
    if a is None or b is None:
        return True
    if not (a[2].cross(b[2]).Length < tol and (b[1] - a[1]).cross(a[2]).Length < tol * 10):
        return False
    return _hinge_off_by(joint) < 0.05


def _hinge_off_by(joint):
    """Degrees the Hinge is past its nearer limit (signed: turn by this to be back on it), 0 inside."""
    if not (getattr(joint, "EnableAngleMin", False) and getattr(joint, "EnableAngleMax", False)):
        return 0.0
    try:
        lo, hi = float(joint.AngleMin), float(joint.AngleMax)
        own = _host_value("Angle Range", joint)
    except Exception:
        return 0.0
    if lo > hi:
        lo, hi = hi, lo
    wrap = lambda x: (x + 180.0) % 360.0 - 180.0
    if lo - 1e-9 <= own <= hi + 1e-9 or lo - 1e-9 <= own + 360 <= hi + 1e-9 or lo - 1e-9 <= own - 360 <= hi + 1e-9:
        return 0.0
    to_lo, to_hi = wrap(lo - own), wrap(hi - own)
    return abs(to_lo) if abs(to_lo) <= abs(to_hi) else abs(to_hi)


def _angle_range_clamp(asm, joint):
    ""


    data = limit_values(joint)
    if data is None or data[0] is None or getattr(joint, "Suppressed", False):
        return False
    host, low, high = data[0], min(data[1], data[2]), max(data[1], data[2])
    refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    now = picked_value("Angle Range", refs)
    if now is None or low - 1e-6 <= now <= high + 1e-6:
        return False
    edge = min(1e-3, (high - low) / 4.0)       # just inside: FreeCAD's solver fails on a limit's very end
    want = low + edge if abs(now - low) <= abs(now - high) else high - edge
    d = (want - now) * _rate("Angle Range", host, refs)
    f1 = host.Reference1[0].Placement.multiply(host.Placement1)
    z = f1.Rotation.multVec(V(0, 0, 1))
    comp = host.Reference2[0]
    picked = {refs[0][0], refs[1][0]}
    fixed = set(grounded(asm))
    if comp in fixed or (comp not in picked and host.Reference1[0] in picked):
        comp, d = host.Reference1[0], -d
    if comp in fixed:
        return False
    comp.Placement = App.Placement(V(), App.Rotation(z, d), f1.Base).multiply(comp.Placement)
    return True


def _hinge_clamp(asm, joint):
    ""

    if mate_type(joint) != "Hinge" or getattr(joint, "Suppressed", False) or _hinge_off_by(joint) < 1e-6:
        return False
    lo, hi = sorted((float(joint.AngleMin), float(joint.AngleMax)))
    own = _host_value("Angle Range", joint)
    wrap = lambda x: (x + 180.0) % 360.0 - 180.0
    to_lo, to_hi = wrap(lo - own), wrap(hi - own)
    turn = to_lo if abs(to_lo) <= abs(to_hi) else to_hi
    f1 = joint.Reference1[0].Placement.multiply(joint.Placement1)
    z = f1.Rotation.multVec(V(0, 0, 1))
    fixed = set(grounded(asm))
    comp = joint.Reference2[0]
    if comp in fixed:
        comp, turn = joint.Reference1[0], -turn
    if comp in fixed:
        return False
    comp.Placement = App.Placement(V(), App.Rotation(z, turn), f1.Base).multiply(comp.Placement)
    return True


# ----------------------------------------------------------------------------- defined or not
def _equations(kind, g1, g2, lock_rotation=False):
    """The mate's equations (as functions of the two moved geometries) whose Jacobian rank
    counts the motions it takes away."""
    t1, t2 = g1[0], g2[0]

    def cross(a, b):
        c = a.cross(b)
        return [c.x, c.y, c.z]

    def vec(a):
        return [a.x, a.y, a.z]

    rows = []
    if kind == "Lock":
        return "lock"
    if kind in ("Coincident", "Distance", "Tangent"):
        if t1 == "plane" and t2 == "plane":
            rows += [lambda a, b: cross(a[2], b[2]), lambda a, b: [a[2].dot(b[1] - a[1])]]
        elif "plane" in (t1, t2):
            p, o = (g1, g2) if t1 == "plane" else (g2, g1)
            first = 0 if t1 == "plane" else 1
            if o[0] == "point":
                rows += [lambda a, b, f=first: [(a, b)[f][2].dot((a, b)[1 - f][1] - (a, b)[f][1])]]
            else:   # line, circle or cylinder: in (or tangent to) the plane
                rows += [lambda a, b, f=first: [(a, b)[f][2].dot((a, b)[1 - f][2])],
                         lambda a, b, f=first: [(a, b)[f][2].dot((a, b)[1 - f][1] - (a, b)[f][1])]]
        elif t1 == "point" and t2 == "point":
            rows += [lambda a, b: vec(b[1] - a[1])]
        elif "point" in (t1, t2):
            f = 0 if t1 != "point" else 1    # f: the line or axis
            rows += [lambda a, b, f=f: cross((a, b)[1 - f][1] - (a, b)[f][1], (a, b)[f][2])]
        else:  # line/axis with line/axis: coincident lines (or the same axis)
            rows += [lambda a, b: cross(a[2], b[2]), lambda a, b: cross(b[1] - a[1], a[2])]
    elif kind == "Concentric":
        if "point" in (t1, t2):
            f = 0 if t1 != "point" else 1
            rows += [lambda a, b, f=f: cross((a, b)[1 - f][1] - (a, b)[f][1], (a, b)[f][2])]
        else:
            rows += [lambda a, b: cross(a[2], b[2]), lambda a, b: cross(b[1] - a[1], a[2])]
            if lock_rotation:
                rows += ["spin"]
    elif kind == "Parallel":
        if "plane" in (t1, t2) and t1 != t2:
            rows += [lambda a, b: [a[2].dot(b[2])]]
        else:
            rows += [lambda a, b: cross(a[2], b[2])]
    elif kind == "Perpendicular":
        if "plane" in (t1, t2) and t1 != t2:
            rows += [lambda a, b: cross(a[2], b[2])]
        else:
            rows += [lambda a, b: [a[2].dot(b[2])]]
    elif kind == "Angle":
        rows += [lambda a, b: [a[2].dot(b[2])]]
    elif kind == "Hinge":      # one axis, the two faces on each other: only the turn is left
        rows += [lambda a, b: cross(a[2], b[2]), lambda a, b: cross(b[1] - a[1], a[2]),
                 lambda a, b: [a[2].dot(b[1] - a[1])]]
    return rows


def _moved(g, x):
    """g moved by the small motion x = (tx, ty, tz, rx, ry, rz) about the assembly origin."""
    t = V(x[0], x[1], x[2])
    w = V(x[3], x[4], x[5])
    out = [g[0]]
    for i, item in enumerate(g[1:], 1):
        if isinstance(item, App.Vector):
            if i == 1:
                out.append(item + t + w.cross(item))
            else:
                out.append(item + w.cross(item))
        else:
            out.append(item)
    return tuple(out)


_DEFINED = {}


def defined(asm):
    """{component: True when fully defined}. Fixed components are fully defined. Kept while the
    document is unchanged (the tree asks for each subassembly on every refresh)."""
    from . import asmgen
    g = asmgen.gen(asm.Document)
    key = (asm.Document.Name, asm.Name)
    kept = _DEFINED.get(key)
    if kept is not None and kept[0] == g and g >= 0:
        try:
            if all(c.isValid() for c in kept[1]):
                return dict(kept[1])
        except Exception as _fw_err:
            _fw_log("asmcore.py:3137", _fw_err)
    out = _defined(asm)
    _DEFINED[key] = (g, out)
    return dict(out)


def _defined(asm):
    import numpy

    comps = components(asm)
    fixed = set(grounded(asm))
    free = [c for c in comps if c not in fixed]
    if not free:
        return {c: True for c in comps}
    col = {c: 6 * i for i, c in enumerate(free)}
    blocks = []
    for joint in mates(asm):
        if (getattr(joint, "Suppressed", False) and not is_misaligned(joint)) \
                or getattr(joint, "Activated", True) is False or mate_error(joint):
            continue
        kind = mate_type(joint)
        if kind == "Screw":
            kind = "Concentric"
        if kind in ("Width", "Symmetric"):
            kind = "Coincident"     # mid-plane on mid-plane / a set distance: offsets are constants
        if kind == "Profile Center":
            if joint.JointType == "Fixed":
                kind = "Lock"
            else:   # the profiles' centres on one axis, on each other: only the turn is left
                kind = "Hinge"
        if kind == "Concentric" and is_misaligned(joint):
            kind = "Parallel"
        if kind == "InPlace":       # New Part's mate holds the part to the face it was made on: all six
            ends = [r[0] for r in (getattr(joint, "Reference1", None), getattr(joint, "Reference2", None))
                    if r and r[0] is not None]
            n = 6 * len(free)
            for k in range(6):
                row = numpy.zeros(n)
                for c, sign in zip(ends, (-1.0, 1.0)):
                    if c in col:
                        row[col[c] + k] += sign
                blocks.append(row)
            continue
        refs = []
        for prop in ("Reference1", "Reference2"):
            ref = getattr(joint, prop, None)
            if not ref or ref[0] is None or not ref[1]:
                refs = None
                break
            refs.append((ref[0], ref[1][0]))
        if not refs:
            continue
        (c1, e1), (c2, e2) = refs
        s1, s2 = element(c1, e1), element(c2, e2)
        g1, g2 = geometry(s1), geometry(s2)
        if g1 is None or g2 is None:
            continue
        if kind in ("Coincident", "Distance") and "plane" in (g1[0], g2[0]):
            # a circular edge on a face: its own plane lies on the face (three motions, not two)
            g1, g2 = [("plane", g[1], g[2]) if g[0] == "axis" and sh.ShapeType == "Edge" else g
                      for g, sh in ((g1, s1), (g2, s2))]
        eqs = _equations(kind, g1, g2, getattr(joint, LOCK_PROP, False))
        n = 6 * len(free)
        if eqs == "lock" or "spin" in eqs:
            # relative motion of c2 against c1: all six, or the turn about the shared axis
            idx = range(6) if eqs == "lock" else None
            rows = []
            if eqs == "lock":
                for k in idx:
                    row = numpy.zeros(n)
                    if c1 in col:
                        row[col[c1] + k] -= 1.0
                    if c2 in col:
                        row[col[c2] + k] += 1.0
                    rows.append(row)
            else:
                d = g1[2]
                row = numpy.zeros(n)
                for c, sign in ((c1, -1.0), (c2, 1.0)):
                    if c in col:
                        row[col[c] + 3:col[c] + 6] += sign * numpy.array([d.x, d.y, d.z])
                rows.append(row)
                eqs = [e for e in eqs if e != "spin"]
            blocks += rows
            if eqs == "lock":
                continue
        h = 1e-6
        for eq in eqs:
            base = numpy.array(eq(g1, g2), dtype=float)
            jac = numpy.zeros((len(base), n))
            for c, g, which in ((c1, g1, 0), (c2, g2, 1)):
                if c not in col:
                    continue
                for k in range(6):
                    x = [0.0] * 6
                    x[k] = h
                    gm = _moved(g, x)
                    val = numpy.array(eq(gm, g2) if which == 0 else eq(g1, gm), dtype=float)
                    jac[:, col[c] + k] = (val - base) / h
            blocks += list(jac)
    n = 6 * len(free)
    if not blocks:
        out = {c: False for c in free}
    else:
        J = numpy.array(blocks)
        out = {}
        # components that no mate ties together move independently: one small analysis per group
        # of mated components instead of one for all (300 components: a 1800-column matrix)
        idx = {col[c] // 6: c for c in free}
        parent = list(range(len(free)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        row_comps = []
        for r in J:
            nz = numpy.nonzero(numpy.abs(r) > 0.0)[0]
            cs = sorted(set(int(k) // 6 for k in nz))
            row_comps.append(cs)
            for a in cs[1:]:
                ra, rb = find(cs[0]), find(a)
                if ra != rb:
                    parent[rb] = ra
        groups = {}
        for i in range(len(free)):
            groups.setdefault(find(i), []).append(i)
        rows_of = {}
        for r, cs in enumerate(row_comps):
            if cs:
                rows_of.setdefault(find(cs[0]), []).append(r)
        for g, members in groups.items():
            rows = rows_of.get(g)
            if not rows:
                for i in members:
                    out[idx[i]] = False
                continue
            cols = [6 * i + k for i in members for k in range(6)]
            sub = J[numpy.ix_(rows, cols)]
            _u, sv, vt = numpy.linalg.svd(sub)
            tol = max(sub.shape) * (sv[0] if len(sv) else 1.0) * 1e-7
            rank = int((sv > tol).sum())
            null = vt[rank:]
            for j, i in enumerate(members):
                block = null[:, 6 * j:6 * j + 6] if len(null) else numpy.zeros((0, 6))
                out[idx[i]] = bool(len(null) == 0 or numpy.abs(block).max() < 1e-6)
    for c in fixed:
        out[c] = True
    return out


def over_defined(asm):
    """Components whose mates could not all be solved."""
    out = set()
    fixed = None
    for joint in mates(asm):
        if mate_error(joint):
            fixed = grounded(asm) if fixed is None else fixed
            for prop in ("Reference1", "Reference2"):
                ref = getattr(joint, prop, None)
                if ref and ref[0] is not None and ref[0] not in fixed:
                    out.add(ref[0])
    return out


def prefix(asm, comp, state=None, over=None):
    """"(f) ", "(+) ", "(-) " or "" for the component's tree row."""
    if comp in grounded(asm):
        return FIXED_PREFIX
    over = over_defined(asm) if over is None else over
    if comp in over:
        return OVER_PREFIX
    state = defined(asm) if state is None else state
    return "" if state.get(comp, False) else FLOAT_PREFIX


def assembly_state(asm):
    ""
    if any(mate_error(j) for j in mates(asm)):
        return "Over Defined"
    state = defined(asm)
    return "Fully Defined" if state and all(state.values()) else "Under Defined"


# ----------------------------------------------------------------------------- Slot
SLOT_MODES = ("Free", "Center in Slot", "Distance Along Slot", "Percent Along Slot")


def _faces_of(comp):
    out = []
    for i in range(1, 100000):
        name = "Face%d" % i
        try:
            s = comp.getSubObject(name)
        except Exception:
            s = None
        if s is None or s.isNull() or s.ShapeType != "Face":
            break
        out.append((name, s))
    return out


def slot(comp, elem):
    """The straight slot a picked face belongs to (a flat side or a round end of it), as
    {"start", "end": the end arcs' axis points, "depth", "along": unit directions, "radius":
    half its width, "side": a flat side's element}; None when the face is not a slot's."""
    shape = element(comp, elem)
    if shape is None or shape.ShapeType != "Face":
        return None
    faces = _faces_of(comp)
    cyls = [(n, geometry(f)) for n, f in faces if f.Surface.TypeId == "Part::GeomCylinder"]
    planes = [(n, geometry(f)) for n, f in faces if f.Surface.TypeId == "Part::GeomPlane"]
    g = geometry(shape)
    if g is None:
        return None
    if g[0] == "axis":
        ends = [c for c in cyls if c[0] == elem]
    else:
        n = V(g[2]).normalize()
        ends = [c for c in cyls if abs(V(c[1][2]).normalize().dot(n)) < 1e-6
                and abs(abs((c[1][1] - g[1]).dot(n)) - c[1][3]) < 1e-5]
    best = None
    for e1 in ends:
        g1 = e1[1]
        ax = V(g1[2]).normalize()
        for e2 in cyls:
            g2 = e2[1]
            if e2[0] == e1[0] or abs(g2[3] - g1[3]) > 1e-6 or V(g2[2]).cross(ax).Length > 1e-6:
                continue
            d = g2[1] - g1[1]
            d = d - ax * d.dot(ax)
            if d.Length < 1e-6:
                continue
            along = V(d).normalize()
            side_n = ax.cross(along)
            sides = [p for p in planes if abs(abs(V(p[1][2]).normalize().dot(side_n)) - 1) < 1e-6
                     and abs(abs((p[1][1] - g1[1]).dot(side_n)) - g1[3]) < 1e-5]
            if g[0] == "plane":
                if elem not in [p[0] for p in sides]:
                    continue
                side = elem
            elif sides:
                side = sides[0][0]
            else:
                continue
            if best is None or d.Length < best[0]:
                best = (d.Length, g1[1], g1[1] + d, ax, along, g1[3], side, e1[0], e2[0])
    if best is None:
        return None
    _l, start, end, ax, along, radius, side, n1, n2 = best
    if g[0] == "plane" and int(n1[4:]) > int(n2[4:]):
        start, end, along = end, start, -along      # picked a side: from the end named first
    return {"start": start, "end": end, "depth": ax, "along": along, "radius": radius,
            "side": side, "length": (end - start).Length}


def slot_refs(refs):
    """(pin, slot pick, slot) from the two picks in either order, or None."""
    for a, b in (refs, refs[::-1]):
        g = geometry(element(*a))
        s = element(*a)
        if g is None or g[0] != "axis" or s.ShapeType != "Face":
            continue
        found = slot(*b)
        if found is not None and found["radius"] >= g[3] - 1e-6:
            return a, b, found
    return None


def slot_target(found, mode, value):
    """The point along the slot the pin's axis is held at (None for Free)."""
    if mode == "Center in Slot":
        s = found["length"] / 2.0
    elif mode == "Distance Along Slot":
        s = float(value or 0.0)
    elif mode == "Percent Along Slot":
        s = found["length"] * float(value or 0.0) / 100.0
    else:
        return None
    return found["start"] + found["along"] * s


def _plane_frame(part, slot_comp, normal, point, radius, sign):
    """The hidden Distance's flat side frame turned to normal and moved so FreeCAD's line in
    plane (the pin's axis at its radius off the frame) puts the axis on the plane through point."""
    which = 1 if part.Reference1[0] is slot_comp else 2
    setattr(part, "Offset%d" % which, App.Placement())
    try:
        part.Proxy.updateJCSPlacements(part)
    except Exception as _fw_err:
        _fw_log("asmcore.py:3417", _fw_err)
    raw = slot_comp.Placement.multiply(getattr(part, "Placement%d" % which))
    n = V(normal).normalize()
    origin = point - n * (radius * sign)
    local = raw.inverse()
    setattr(part, "Offset%d" % which, App.Placement(local.multVec(origin),
                                                    App.Rotation(V(0, 0, 1), local.Rotation.multVec(n))))
    try:
        part.Proxy.updateJCSPlacements(part)
    except Exception as _fw_err:
        _fw_log("asmcore.py:3427", _fw_err)


def _square_frame(part, slot_comp, direction):
    which = 1 if part.Reference1[0] is slot_comp else 2
    setattr(part, "Offset%d" % which, App.Placement())
    try:
        part.Proxy.updateJCSPlacements(part)
    except Exception as _fw_err:
        _fw_log("asmcore.py:3436", _fw_err)
    raw = slot_comp.Placement.multiply(getattr(part, "Placement%d" % which))
    setattr(part, "Offset%d" % which, App.Placement(V(), App.Rotation(V(0, 0, 1), raw.Rotation.inverted().multVec(direction))))
    try:
        part.Proxy.updateJCSPlacements(part)
    except Exception as _fw_err:
        _fw_log("asmcore.py:3442", _fw_err)


def slot_values(joint):
    data = list(getattr(joint, SLOT_PROP, []) or [])
    mode = data[0] if data and data[0] in SLOT_MODES else "Free"
    value = float(data[1]) if len(data) > 1 else 0.0
    return mode, value


def make_slot(asm, refs, mode="Free", value=0.0, joint=None):
    ""





    import UtilsAssembly
    found = slot_refs(refs)
    if found is None:
        return None, "Pick the pin's round face and a face of a straight slot."
    pin, pick, info = found
    radius = geometry(element(*pin))[3]
    if joint is None:
        joint = joint_group(asm).newObject("App::FeaturePython", "Slot")
        for prop, t, doc in ((MATE_PROP, "App::PropertyString", "Mate type"),
                             (ERROR_PROP, "App::PropertyBool", "The mate over defines the assembly"),
                             (SLOT_PROP, "App::PropertyStringList", "Slot: constraint, value"),
                             ("Suppressed", "App::PropertyBool", "Suppressed"),
                             ("Reference1", "App::PropertyXLinkSubHidden", "First pick"),
                             ("Reference2", "App::PropertyXLinkSubHidden", "Second pick")):
            joint.addProperty(t, prop, "FreeCAD", doc)
        setattr(joint, MATE_PROP, "Slot")
        joint.Label = _next_mate_name(asm, "Slot")
        if App.GuiUp and joint.ViewObject is not None:
            joint.ViewObject.Proxy = 0
        joint.Reference1 = (refs[0][0], [refs[0][1]])
        joint.Reference2 = (refs[1][0], [refs[1][1]])
    setattr(joint, SLOT_PROP, [mode, repr(float(value or 0.0))])
    for old in _part_for(asm, joint):
        asm.Document.removeObject(old.Name)
    before = _save_placements(asm)
    comp = pick[0]
    side = [[pin[0], [pin[1], pin[1]]], [comp, [info["side"], info["side"]]]]
    middle = _hidden(asm, joint, "Distance", side)
    middle.Distance = 0.0
    target = slot_target(info, mode, value)
    if target is None:
        across = _hidden(asm, joint, "Perpendicular", side)
    else:
        across = _hidden(asm, joint, "Distance", side)
        across.Distance = 0.0
    _restore_placements(asm, before)
    side_n = info["depth"].cross(info["along"])
    ok = False
    for s1 in (1, -1):
        for s2 in ((1, -1) if target is not None else (1,)):
            _plane_frame(middle, comp, side_n, info["start"], radius, s1)
            if target is None:
                _square_frame(across, comp, info["along"])
            else:
                _plane_frame(across, comp, info["along"], target, radius, s2)
            if solve(asm, before) and slot_holds(joint):
                ok = True
                break
            _restore_placements(asm, before)
        if ok:
            break
    return joint, (None if _mark(joint, ok) else OVER_MESSAGE)


def slot_free_clamp(asm):
    ""


    fixed = set(grounded(asm))
    moved = False
    for joint in mates(asm):
        if getattr(joint, MATE_PROP, "") != "Slot" or getattr(joint, "Suppressed", False):
            continue
        if slot_values(joint)[0] != "Free":
            continue
        try:
            found = slot_refs([(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)])
        except Exception:
            found = None
        if found is None:
            continue
        pin, pick, info = found
        g = geometry(element(*pin))
        if g is None:
            continue
        length = (info["end"] - info["start"]).Length
        s = (V(g[1]) - info["start"]).dot(info["along"])
        want = min(max(s, 0.0), length)
        if abs(want - s) < 1e-7:
            continue
        shift = info["along"] * (want - s)
        if pin[0] not in fixed:
            pin[0].Placement = App.Placement(pin[0].Placement.Base + shift, pin[0].Placement.Rotation)
        elif pick[0] not in fixed:
            pick[0].Placement = App.Placement(pick[0].Placement.Base - shift, pick[0].Placement.Rotation)
        else:
            continue
        moved = True
    return moved


def slot_holds(joint, tol=1e-3):
    """The pin's axis on the slot's middle plane, along its depth, at its place (not Free)."""
    try:
        refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
    except Exception:
        return True
    found = slot_refs(refs)
    if found is None:
        return False
    pin, _pick, info = found
    g = geometry(element(*pin))
    p, d = g[1], V(g[2]).normalize()
    if abs(abs(d.dot(info["depth"])) - 1) > tol:
        return False
    side_n = info["depth"].cross(info["along"])
    if abs((p - info["start"]).dot(side_n)) > tol * 10:
        return False
    mode, value = slot_values(joint)
    target = slot_target(info, mode, value)
    return target is None or abs((p - target).dot(info["along"])) < tol * 10
