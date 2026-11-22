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

import os
import shutil

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

SUPPRESS_PROP = "FwComponentSuppressed"
SUPPRESSED_MATES_PROP = "FwSuppressedWith"  # the mates its suppression suppressed
TEMP_PROP = "FwTemporaryFix"                # a fix or group joint made by Temporary Fix/Group
LIGHT_PROP = "FwLightweight"
DISPLAY_PROP = "FwComponentDisplay"

DISPLAYS = (("Wireframe", "Wireframe"), ("Hidden Lines Visible", "Wireframe"),
            ("Hidden Lines Removed", "Flat Lines"), ("Shaded With Edges", "Flat Lines"),
            ("Shaded", "Shaded"), ("Default Display", None))


def _asm(comp):
    return ac.assembly_of(comp.Document)


def _tell(title, text):
    if App.GuiUp:
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, title, text,
                                    QtWidgets.QMessageBox.Ok, Gui.getMainWindow())
        box.setObjectName("FW_ComponentMessage")
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        box.open()
    App.Console.PrintMessage("%s: %s\n" % (title, text))


def _transaction(doc, name, run):
    doc.openTransaction(name)
    try:
        return run()
    finally:
        doc.commitTransaction()
        _refresh()


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmcomp.py:69", _fw_err)


def part_document(comp):
    from . import asmmenu
    return asmmenu.part_document(comp)


# ----------------------------------------------------------------------------- Open Part in Position
def camera_for_part(asm_rotation, comp_rotation):
    """The part window's camera turn that shows the part as it sits in the assembly."""
    return comp_rotation.inverted().multiply(asm_rotation)


def open_part_in_position(comp):
    """The part opens in its own window, turned as it shows in the assembly."""
    from . import asmmenu
    try:
        cam = Gui.ActiveDocument.ActiveView.getCameraOrientation()
    except Exception:
        cam = None
    rot = ac_global_rotation(comp)
    if not asmmenu.open_part(comp):
        return False
    if cam is not None:
        try:
            view = Gui.ActiveDocument.ActiveView
            view.setCameraOrientation(camera_for_part(cam, rot))
            Gui.SendMsgToActiveView("ViewFit")
        except Exception as error:
            App.Console.PrintLog("FreeCAD: open part in position: %s\n" % error)
    return True


def ac_global_rotation(comp):
    try:
        from . import asmexplode
        return asmexplode.gplacement(comp).Rotation
    except Exception:
        return comp.Placement.Rotation


# ----------------------------------------------------------------------------- Open Drawing
def drawing_files(path):
    """Drawings next to a part file that show it: <name>.FCStd siblings holding a TechDraw page
    whose views use the part's file (first the ones named after the part)."""
    import zipfile
    if not path:
        return []
    folder, stem = os.path.dirname(path), os.path.splitext(os.path.basename(path))[0]
    out = []
    try:
        names = sorted(os.listdir(folder), key=lambda n: (not n.lower().startswith(stem.lower()), n.lower()))
    except OSError:
        return []
    for n in names:
        full = os.path.join(folder, n)
        if not n.lower().endswith(".fcstd") or os.path.normcase(full) == os.path.normcase(path):
            continue
        try:
            with zipfile.ZipFile(full) as z:
                xml = z.read("Document.xml").decode("utf-8", "replace")
        except Exception:
            continue
        if "TechDraw::DrawPage" in xml and os.path.basename(path) in xml:
            out.append(full)
    return out


def open_drawing(comp):
    ""
    doc = part_document(comp)
    if doc is None:
        doc = comp.getLinkedObject(True).Document if hasattr(comp, "getLinkedObject") else None
    files = drawing_files(getattr(doc, "FileName", "") or "")
    if not files:
        _tell("Open Drawing", "Cannot locate the drawing of %s." % ac.part_name(comp))
        return None
    path = files[0]
    for d in App.listDocuments().values():
        if os.path.normcase(d.FileName or "") == os.path.normcase(path):
            if App.GuiUp:
                Gui.setActiveDocument(d.Name)
            return d
    return App.openDocument(path)


# ----------------------------------------------------------------------------- Suppress / Set to Resolved
def is_suppressed(comp):
    return bool(getattr(comp, SUPPRESS_PROP, False))


def suppress(comp, on=True, solve=None):
    """Suppress: the component leaves the view, its mates stop holding; Set to Resolved brings
    both back. Only Set to Resolved solves (solve=None): taking mates away leaves every other mate
    holding, and a full solve of a 300-part assembly per suppressed component took seconds."""
    from . import asmmenu
    asm = _asm(comp)
    if on == is_suppressed(comp):
        return False
    if not hasattr(comp, SUPPRESS_PROP):
        comp.addProperty("App::PropertyBool", SUPPRESS_PROP, "FreeCAD", "Suppressed component")
        comp.setEditorMode(SUPPRESS_PROP, 2)
        comp.addProperty("App::PropertyStringList", SUPPRESSED_MATES_PROP, "FreeCAD", "Mates suppressed with it")
        comp.setEditorMode(SUPPRESSED_MATES_PROP, 2)
    if on:
        mates = [j for j in asmmenu.mates_of(comp) if not getattr(j, "Suppressed", False)]
        for j in mates:
            j.Suppressed = True
        setattr(comp, SUPPRESSED_MATES_PROP, [j.Name for j in mates])
        setattr(comp, SUPPRESS_PROP, True)
        if comp.ViewObject is not None:
            comp.ViewObject.Visibility = False
    else:
        for name in getattr(comp, SUPPRESSED_MATES_PROP, []) or []:
            j = comp.Document.getObject(name)
            if j is not None and not asmmenu.suppressed(j):
                j.Suppressed = False
        setattr(comp, SUPPRESSED_MATES_PROP, [])
        setattr(comp, SUPPRESS_PROP, False)
        if comp.ViewObject is not None:
            comp.ViewObject.Visibility = True
    _with_seed(asm, comp, on)
    if (not on) if solve is None else solve:
        ac.solve(asm)
    return True


WITH_SEED_PROP = "FwSuppressedWithSeed"


def _with_seed(asm, comp, on):
    ""


    try:
        from . import asmcpattern as cp
        if on:
            took = []
            for feat in cp.patterns(asm):
                for link in cp.instances(feat):
                    if getattr(link, cp.SEED_PROP, None) is comp and not is_suppressed(link):
                        suppress(link, True, solve=False)
                        took.append(link.Name)
            if took:
                if not hasattr(comp, WITH_SEED_PROP):
                    comp.addProperty("App::PropertyStringList", WITH_SEED_PROP, "FreeCAD", "Pattern instances suppressed with it")
                    comp.setEditorMode(WITH_SEED_PROP, 2)
                setattr(comp, WITH_SEED_PROP, took)
        else:
            for name in getattr(comp, WITH_SEED_PROP, []) or []:
                link = comp.Document.getObject(name)
                if link is not None:
                    suppress(link, False, solve=False)
            if getattr(comp, WITH_SEED_PROP, None):
                setattr(comp, WITH_SEED_PROP, [])
    except Exception as _fw_err:
        _fw_log("asmcomp.py:with seed", _fw_err)


# ----------------------------------------------------------------------------- Temporary Fix/Group
def temporary_joints(asm):
    return [j for j in ac.joint_group(asm).Group if getattr(j, TEMP_PROP, False)]


def is_temporary(comp):
    asm = _asm(comp)
    for j in temporary_joints(asm):
        if getattr(j, "ObjectToGround", None) is comp:
            return True
        for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)):
            if r and r[0] is comp:
                return True
    return False


def _element(comp):
    shape = comp.Shape
    return "Face1" if shape.Faces else "Edge1" if shape.Edges else "Vertex1"


def _mark_temp(joint):
    joint.addProperty("App::PropertyBool", TEMP_PROP, "FreeCAD", "Temporary Fix/Group")
    joint.setEditorMode(TEMP_PROP, 2)
    setattr(joint, TEMP_PROP, True)


def temporary_fix(asm, comps):
    """One component: fixed where it is. Several: they move as one group (the first holds the
    others), until Release Temporary Fix/Group or a rebuild."""
    comps = [c for c in comps if c is not None]
    if not comps:
        return []
    made = []
    if len(comps) == 1:
        c = comps[0]
        if c in ac.grounded(asm):
            return []
        j = ac.fix(asm, c)
        j.Label = "Temporary Fix (%s)" % c.Label
        _mark_temp(j)
        made.append(j)
    else:
        first = comps[0]
        for other in comps[1:]:
            j = ac.add_mate(asm, "Lock", (first, _element(first)), (other, _element(other)))
            if j is not None:
                j.Label = "Temporary Group (%s,%s)" % (first.Label, other.Label)
                _mark_temp(j)
                made.append(j)
    ac.solve(asm)
    return made


def release_temporary(asm):
    gone = 0
    for j in temporary_joints(asm):
        asm.Document.removeObject(j.Name)
        gone += 1
    if gone:
        ac.solve(asm)
    return gone


# ----------------------------------------------------------------------------- Form New Subassembly
def _next_assembly_name(folder):
    n = 1
    while os.path.exists(os.path.join(folder, "Assem%d.FCStd" % n)) or \
            any(d.Label == "Assem%d" % n for d in App.listDocuments().values()):
        n += 1
    return "Assem%d" % n


def _offsets_of(j):
    """A mate's own offsets (a Hinge's coincident planes, a mate made on a face away from its
    edge) with the element each goes with, to be put on the mate made again."""
    try:
        o1, o2 = App.Placement(j.Offset1), App.Placement(j.Offset2)
        e1, e2 = j.Reference1[1][0].split(".")[-1], j.Reference2[1][0].split(".")[-1]
    except Exception:
        return None
    if o1.isIdentity() and o2.isIdentity():
        return None
    return (o1, e1), (o2, e2)


def _keep_offsets(made, offsets):
    """The offsets of the mate made again: the same element keeps the same offset (the new mate
    can name its two picks the other way round)."""
    if made is None or offsets is None:
        return False
    (o1, e1), (o2, e2) = offsets
    try:
        n1 = made.Reference1[1][0].split(".")[-1]
    except Exception:
        return False
    if n1 != e1 and n1 == e2:
        o1, o2 = o2, o1
    try:
        if made.Offset1 == o1 and made.Offset2 == o2:
            return False
        made.Offset1, made.Offset2 = o1, o2
        made.Proxy.updateJCSPlacements(made)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: form new subassembly, offsets of %s: %s\n" % (made.Label, error))
        return False
    return True


def _remake_mate(sub, j, copies):
    """The mate j made again in sub on the copies of its components: its type, value, Lock
    rotation and name, and the picks an advanced mate keeps (Width, Slot, Limit distance/angle)."""
    kind = ac.mate_type(j)
    name = j.Label.split(" (")[0]
    m = lambda r: (copies[r[0]], r[1])
    refs = [(r[0], r[1][0]) for r in (j.Reference1, j.Reference2)]
    made = None
    if kind == "Width":
        data = ac.width_values(j)
        if data is not None and all(c in copies for c, _ in data[0] + data[1]):
            made = ac.make_width(sub, [m(r) for r in data[0]], [m(r) for r in data[1]], data[2], data[3], data[4])[0]
    elif kind in ac.LIMITS:
        data = ac.limit_values(j)
        if data is not None:
            made = ac.make_limit(sub, kind, [m(r) for r in refs], data[1], data[2])[0]
    elif kind == "Slot":
        mode, value = ac.slot_values(j)
        made = ac.make_slot(sub, [m(r) for r in refs], mode, value)[0]
    else:
        from .asmcopy import value_of
        made = ac.add_mate(sub, kind, m(refs[0]), m(refs[1]), value_of(j),
                           lock_rotation=bool(getattr(j, ac.LOCK_PROP, False)), name=name,
                           side=ac.distance_side(j) if kind == "Distance" else None)
    if made is not None and kind not in ("Width", "Slot") + tuple(ac.LIMITS) and _keep_offsets(made, _offsets_of(j)):
        ac.solve(sub)
    if made is not None and kind in ("Width", "Slot") + tuple(ac.LIMITS):
        made.Label = name
    return made


def _virtual_name(doc):
    """Assem<n> for a new virtual subassembly: not a file beside the assembly, an open document
    or another virtual subassembly of this one."""
    folder = os.path.dirname(doc.FileName or "") or App.getUserAppDataDir()
    taken = {o.Label.split("^")[0] for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"}
    n = 1
    while "Assem%d" % n in taken or os.path.exists(os.path.join(folder, "Assem%d.FCStd" % n)) or \
            any(d.Label == "Assem%d" % n for d in App.listDocuments().values()):
        n += 1
    return "Assem%d" % n


def virtual_assembly(doc):
    ""

    name = _virtual_name(doc)
    sub = doc.addObject("Assembly::AssemblyObject", "Assembly")
    sub.Type = "Assembly"
    sub.Label = "%s^%s" % (name, doc.Label)
    ac.joint_group(sub)
    try:
        if sub.ViewObject is not None:
            sub.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("asmcomp.py:360", _fw_err)
    return sub


def mark_virtual(asm, link):
    """The subassembly component of a virtual assembly: [Assem1^Top]<1>, marked virtual."""
    from . import asminsert
    if not hasattr(link, asminsert.VIRTUAL_PROP):
        link.addProperty("App::PropertyBool", asminsert.VIRTUAL_PROP, "FreeCAD", "Virtual component (kept in the assembly)")
        link.setEditorMode(asminsert.VIRTUAL_PROP, 2)
    setattr(link, asminsert.VIRTUAL_PROP, True)
    link.Label = asminsert._instance(asm, "[%s]" % link.LinkedObject.Label, link)
    return link


def plain_label(label):
    """Pin<1> for FreeCAD's Pin<1>004 (a label taken twice in one document)."""
    import re
    return re.sub(r"(<\d+>)\d{3}$", r"\1", label)


def is_virtual_sub(comp):
    """A subassembly kept inside its assembly's document (virtual)."""
    target = getattr(comp, "LinkedObject", None)
    return ac.is_subassembly(comp) and target is not None and target.Document is comp.Document


def remove_virtual_source(sub, kids=()):
    """A virtual subassembly's own assembly, with its mates and components (this document only).
    kids: the subassembly component's own copies, gone first (they link these components)."""
    doc = sub.Document
    jg = ac.joint_group(sub) if hasattr(sub, "Group") else None
    joints = [o for o in (getattr(jg, "Group", []) or [])] if jg is not None else []
    comps = [o for o in getattr(sub, "Group", []) or [] if o is not jg]
    order = [k for k in kids] + joints + comps + ([jg] if jg is not None else []) + [sub]
    for o in order:
        try:
            if o is not None and doc.getObject(o.Name) is not None:
                doc.removeObject(o.Name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: virtual subassembly: %s\n" % error)


def save_sub_external(asm, comp, path=None):
    """Save Assembly (in External File) on a virtual subassembly: it becomes Assem1.FCStd beside
    the assembly (asked where when not given), its components and mates kept."""
    from . import asmmenubar
    if not is_virtual_sub(comp):
        return None
    name = comp.LinkedObject.Label.split("^")[0]
    if path is None:
        folder = os.path.dirname(asm.Document.FileName or "") or App.getUserAppDataDir()
        from PySide import QtWidgets
        path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save As",
                                                        os.path.join(folder, name + ".FCStd"), "FreeCAD (*.FCStd)")
        if not path:
            return None
    comps = asmmenubar.dissolve(asm, comp)
    return form_new_subassembly(asm, comps, path=path, virtual=False)


def form_new_subassembly(asm, comps, path=None, virtual=None):
    ""



    comps = [c for c in comps if c is not None and not ac.is_subassembly(c)]
    if not comps:
        return None
    if virtual is None:
        virtual = path is None
    top_doc = asm.Document
    if virtual:
        new_doc = top_doc
        sub = virtual_assembly(top_doc)
    else:
        folder = os.path.dirname(top_doc.FileName or "") or App.getUserAppDataDir()
        name = _next_assembly_name(folder)
        path = path or os.path.join(folder, name + ".FCStd")
        try:
            new_doc = App.newDocument(name, name, True, False)
        except TypeError:
            new_doc = App.newDocument(name)
        sub = ac.make_assembly(new_doc)
        new_doc.saveAs(path)
        new_doc.Label = os.path.splitext(os.path.basename(path))[0]
        sub.Label = new_doc.Label
    fixed = ac.grounded(asm)
    copies = {}
    from . import asmreorg
    configs = {}
    for c in comps:
        target, config = asmreorg._part_of(c)     # an instance in its own configuration: the part itself
        link = sub.newObject("App::Link", "Component")
        link.LinkedObject = target
        link.Label = c.Label
        link.Placement = c.Placement
        copies[c] = link
        configs[link] = config
    sub.Document.recompute()
    for link, config in configs.items():
        asmreorg._same_configuration(link, config)
    first = copies[comps[0]]
    ac.fix(sub, first)
    # the mates among the picked components go with them
    from . import asmmenu
    moved = []
    later = []
    for j in list(ac.mates(asm)):
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        owners = [r[0] for r in refs if r]
        if owners and all(o in copies for o in owners):
            if ac.mate_type(j) in ac.LIMITS:
                later.append(j)         # a range sets limits on a mate made before it
                continue
            try:
                if _remake_mate(sub, j, copies) is not None:
                    moved.append(j)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: form new subassembly, mate %s: %s\n" % (j.Label, error))
    for j in later:
        try:
            if _remake_mate(sub, j, copies) is not None:
                moved.append(j)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: form new subassembly, mate %s: %s\n" % (j.Label, error))
    ac.solve(sub)

    # lets it (a piston along its pin, which only the bore in the top assembly held)
    solved = {l: App.Placement(l.Placement) for l in copies.values()}
    for c, l in copies.items():
        l.Placement = c.Placement
    if not all(ac.satisfied(j) for j in ac.mates(sub) if not getattr(j, "Suppressed", False)):
        for l, p in solved.items():
            l.Placement = p
    new_doc.recompute()
    if not virtual:
        new_doc.save()

    # them: made again on the component inside the new subassembly
    across = []
    for j in list(ac.mates(asm)):
        refs = [getattr(j, p, None) for p in ("Reference1", "Reference2")]
        if not all(refs) or j in moved:
            continue
        inside = [r[0] in copies for r in refs]
        if any(inside) and not all(inside):
            value = None
            kind = ac.mate_type(j)
            if kind == "Distance":
                value = ac.distance_value(j)
            elif kind == "Angle":
                value = float(getattr(j, "Angle", 0.0))
            across.append((kind, [(copies[r[0]], r[1][0]) if r[0] in copies else (r[0], r[1][0]) for r in refs],
                           value, j.Label.split(" (")[0], bool(getattr(j, ac.LOCK_PROP, False)), ac.distance_side(j),
                           _offsets_of(j) if kind not in ("Width", "Slot") + tuple(ac.LIMITS) else None))
    # out of the top assembly: their mates, their fixes, the components
    for j in list(ac.mates(asm)):
        owners = [r[0] for r in (getattr(j, "Reference1", None), getattr(j, "Reference2", None)) if r]
        if any(o in copies for o in owners):
            top_doc.removeObject(j.Name)
    for c in comps:
        if c in fixed:
            top_doc.removeObject(fixed[c].Name)
    was_fixed = any(c in fixed for c in comps)
    for c in comps:
        top_doc.removeObject(c.Name)
    link = ac.insert(asm, sub, App.Placement())
    if virtual:
        mark_virtual(asm, link)
    if was_fixed and link not in ac.grounded(asm):
        ac.fix(asm, link)
    top_doc.recompute()
    ac.solve(asm)       # FreeCAD's solver forgets the removed components (a new joint's undoSolve reads them)
    # FreeCAD's subassembly link holds its own copies of the components (Component003 for the
    # subassembly's Component): a mate on the subassembly names the copy, as a pick in the view does
    kids = {}
    for g in getattr(link, "Group", []) or []:
        target = getattr(g, "LinkedObject", None)
        if target is not None and target.Document is new_doc:
            kids[target.Name] = g.Name
    for kind, refs, value, label, lock, side, offsets in across:
        made = []
        for comp, sub_el in refs:
            if comp in copies.values():
                made.append((link, "%s.%s" % (kids.get(comp.Name, comp.Name), sub_el)))
            else:
                made.append((comp, sub_el))
        try:
            joint = ac.add_mate(asm, kind, made[0], made[1], value, lock_rotation=lock, name=label,
                                side=side if kind == "Distance" else None)
            if _keep_offsets(joint, offsets):
                ac._unsuppress(joint)           # solved again with them, its error checked again
                if getattr(joint, ac.ERROR_PROP, False):
                    setattr(joint, ac.ERROR_PROP, False)
                ac._mark(joint, ac.solve(asm))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: form new subassembly, top mate %s: %s\n" % (label, error))
    ac.solve(asm)
    if not virtual:
        try:
            from . import asmpm
            asmpm.hold_with(top_doc, new_doc)       # a top assembly not saved yet: the subassembly moves with it
        except Exception as _fw_err:
            _fw_log("asmcomp.py:564", _fw_err)
    # the top assembly stays the active document (FreeCAD made the new one active)
    try:
        App.setActiveDocument(top_doc.Name)
        Gui.ActiveDocument = Gui.getDocument(top_doc.Name)
    except Exception as _fw_err:
        _fw_log("asmcomp.py:570", _fw_err)
    return link


# ----------------------------------------------------------------------------- Make Independent
def instances(asm, comp):
    from .asmcfginst import source
    target = source(comp)
    return [c for c in ac.components(asm) if source(c) is target]


def make_independent(asm, comp, path=None):
    """This instance gets its own copy of the part file (Plate_2.FCStd); the other instances keep
    the old one."""
    doc = part_document(comp)
    if doc is None or not doc.FileName:
        _tell("Make Independent", "Save the part first.")
        return None
    if doc.isTouched() if hasattr(doc, "isTouched") else False:
        doc.save()
    stem, ext = os.path.splitext(doc.FileName)
    if path is None:
        n = 2
        while os.path.exists("%s_%d%s" % (stem, n, ext)):
            n += 1
        path = "%s_%d%s" % (stem, n, ext)
    shutil.copyfile(doc.FileName, path)
    new_doc = App.openDocument(path)
    target_name = comp.LinkedObject.Name
    new_target = new_doc.getObject(target_name) or ac.part_object(new_doc)
    old_label = comp.Label
    comp.LinkedObject = new_target
    comp.Label = ac._instance(asm, new_doc.Label) if new_doc.Label != doc.Label else old_label
    asm.Document.recompute()
    ac.solve(asm)
    return new_doc


# ----------------------------------------------------------------------------- Component Display
_display_nodes = {}


def _style_node(comp, lines):
    """Wireframe: a draw style node at the top of the component's picture (a link's own
    DisplayMode only offers Link / ChildView)."""
    from pivy import coin
    vo = comp.ViewObject
    root = vo.RootNode
    old = _display_nodes.pop((comp.Document.Name, comp.Name), None)
    if old is not None:
        i = root.findChild(old)
        if i >= 0:
            root.removeChild(i)
    if lines:
        node = coin.SoDrawStyle()
        node.style = coin.SoDrawStyle.LINES
        node.setOverride(True)
        root.insertChild(node, 0)
        _display_nodes[(comp.Document.Name, comp.Name)] = node


def component_display(comp, name):
    """Component Display > Wireframe / Hidden Lines Visible / Hidden Lines Removed / Shaded With
    Edges / Shaded / Default Display."""
    vo = comp.ViewObject
    if vo is None:
        return False
    if not hasattr(comp, DISPLAY_PROP):
        comp.addProperty("App::PropertyString", DISPLAY_PROP, "FreeCAD", "Component Display")
        comp.setEditorMode(DISPLAY_PROP, 2)
    name = "" if name == "Default Display" else name
    try:
        _style_node(comp, name in ("Wireframe", "Hidden Lines Visible", "Hidden Lines Removed"))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: component display: %s\n" % error)
    setattr(comp, DISPLAY_PROP, name)
    return True


def reapply_displays(asm):
    """After a file opens: each component's Component Display again."""
    for c in ac.components(asm):
        name = getattr(c, DISPLAY_PROP, "")
        if name and (c.Document.Name, c.Name) not in _display_nodes:
            component_display(c, name)


def is_wireframe(comp):
    return (comp.Document.Name, comp.Name) in _display_nodes


def display_of(comp):
    return getattr(comp, DISPLAY_PROP, "") or "Default Display"


# ----------------------------------------------------------------------------- Lightweight
def is_lightweight(comp):
    return bool(getattr(comp, LIGHT_PROP, False))


def set_lightweight(comp, on=True):
    """Set to Lightweight / Set to Resolved. FreeCAD always loads the whole part, so lightweight
    only marks the component and leaves it out of the
    assembly's recompute until it is resolved again."""
    if not hasattr(comp, LIGHT_PROP):
        comp.addProperty("App::PropertyBool", LIGHT_PROP, "FreeCAD", "Lightweight component")
        comp.setEditorMode(LIGHT_PROP, 2)
    setattr(comp, LIGHT_PROP, bool(on))
    try:
        comp.purgeTouched()
    except Exception as _fw_err:
        _fw_log("asmcomp.py:681", _fw_err)
    return True


# ----------------------------------------------------------------------------- Reload
def reload(comp):
    ""

    doc = part_document(comp)
    if doc is None or not doc.FileName:
        return False
    if any("Touched" in o.State for o in doc.Objects):
        _tell("Reload", "%s has changes that are not saved. Save it first." % doc.Label)
        return False
    path, target = doc.FileName, comp.LinkedObject.Name
    users = [c for c in comp.Document.Objects if getattr(c, "LinkedObject", None) is not None
             and getattr(c.LinkedObject, "Document", None) is doc]
    names = [(c, c.LinkedObject.Name) for c in users]
    App.closeDocument(doc.Name)
    new_doc = App.openDocument(path)
    for c, name in names:
        o = new_doc.getObject(name)
        if o is not None and c.LinkedObject is not o:
            c.LinkedObject = o
    comp.Document.recompute()
    return True


# ----------------------------------------------------------------------------- Replace Components
def replace_component(asm, comp, target, all_instances=False):
    """Replace Components: the component (or every instance of its part) now shows target; its
    mates keep their references by name (a face that is gone shows the mate's error)."""
    comps = instances(asm, comp) if all_instances else [comp]
    for c in comps:
        c.LinkedObject = target
        base, _, inst = c.Label.rpartition("<")
        c.Label = "%s<%s" % (ac.part_name(c), inst) if base else ac.part_name(c)
    asm.Document.recompute()
    ok = ac.solve(asm)
    return comps, ok


def replace_dialog(comp):
    ""
    from . import asmreplacecomp
    return asmreplacecomp.start(comp)
