# SPDX-License-Identifier: LGPL-2.1-or-later
""











import os

import FreeCAD as App

from . import doc_name, msg, params, warn
from . import part as partmod
from . import swapp


def _placement(matrix):
    from . import djb_import
    return djb_import._placement(matrix)


def read_tree(path):
    from . import djb_import
    return djb_import._asm.read_tree(path)


def resolve(leaves, path):
    from . import djb_import
    return djb_import._resolve_components(leaves, path)


def open_assembly(path, doc=None, read_tree_api=None):
    if read_tree_api is not False:
        try:
            from . import asmrt
            if asmrt.available():
                return asmrt.open_assembly(path, doc, read_tree_api)
        except Exception as exc:
            warn("assembly tree not read through SolidWorks (%s); opening its components only" % exc)
    return open_components(path, doc, read_tree_api)


def open_components(path, doc=None, read_tree_api=None):
    root = read_tree(path)
    base = os.path.splitext(os.path.basename(path))[0]
    if doc is None:
        doc = App.newDocument(doc_name(base))
        doc.Label = base
    leaves = [(c, m) for c, m in root.walk() if c.doc_type == "PART"]
    files = resolve(leaves, path)

    asm = _make_assembly(doc, base)
    folder = doc.addObject("App::DocumentObjectGroup", "Parts")
    folder.Label = "Parts"
    bodies = {}                 # local file -> body
    trees = {}
    for comp, _m in leaves:
        local = files.get(comp.path)
        if not local or local in bodies:
            continue
        try:
            body, how = _part_body(doc, local, read_tree_api)
        except Exception as exc:
            warn("component %s: %s" % (comp.name, exc))
            bodies[local] = None
            continue
        folder.addObject(body)
        body.Visibility = False
        bodies[local] = body
        trees[local] = how

    placed = missing = 0
    first = True
    links = {}
    for comp, matrix in leaves:
        body = bodies.get(files.get(comp.path))
        if body is None:
            missing += 1
            continue
        link = asm.newObject("App::Link", "Component")
        link.LinkedObject = body
        link.Label = "%s<%d>" % (comp.name, comp.instance)
        link.Placement = _placement(matrix)
        if comp.hidden:
            link.Visibility = False
        links["%s-%d" % (comp.name, comp.instance)] = link
        if first:
            _fix(asm, link)
            first = False
        placed += 1
    meta = dict(doc.Meta)
    meta.update({"FreeWorksSource": os.path.abspath(path), "FreeWorksSourceKind": "sldasm"})
    doc.Meta = meta
    doc.recompute()
    mated = ""
    if links and read_tree_api is not False and params().GetBool("ReadMates", True) \
            and swapp.use_solidworks():
        from . import mates
        try:
            made, total, notes = mates.read(asm, links, path)
            mated = ", %d of %d mates" % (made, total) if total else ""
            for note in notes:
                warn(note)
        except Exception as exc:
            warn("mates not read: %s" % exc)
    with_tree = sum(1 for h in trees.values() if h == "tree")
    msg("%s: %d components placed, %d parts (%d with their feature tree)%s%s" % (
        base, placed, len([b for b in bodies.values() if b]), with_tree, mated,
        ", %d left out (part file missing or unreadable, see above)" % missing if missing else ""))
    return doc


def _part_body(doc, path, read_tree_api):
    """Opens a part file into doc and returns its single body (several solids: a Part holding
    them)."""
    before = set(o.Name for o in doc.Objects)
    _doc, how = partmod.open_part(path, doc, read_tree_api)
    new = [o for o in doc.Objects if o.Name not in before]
    bodies = [o for o in new if o.TypeId == "PartDesign::Body"]
    name = os.path.splitext(os.path.basename(path))[0]
    if len(bodies) == 1:
        bodies[0].Label = name
        partmod.mark_source_body(bodies[0], path)   # Save As can hand back the file itself while unchanged
        return bodies[0], how
    holder = doc.addObject("App::Part", "Part")
    holder.Label = name
    for b in bodies:
        holder.addObject(b)
    return holder, how


def _make_assembly(doc, label):
    try:
        from swstyle import asmcore
        asm = asmcore.make_assembly(doc)
    except Exception:
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        group = asm.newObject("Assembly::JointGroup", "Joints")
        group.Label = "Mates"
    asm.Label = label
    return asm


def _fix(asm, link):
    try:
        from swstyle import asmcore
        asmcore.fix(asm, link)
    except Exception:
        try:
            if not App.GuiUp:
                raise ImportError("no GUI")
            import UtilsAssembly  # noqa: F401  (Assembly workbench loaded)
            import CommandCreateJoint
            CommandCreateJoint.createGroundedJoint(link)
        except Exception:
            try:                    # without the GUI: the same grounded joint, no view provider
                import JointObject
                group = next(o for o in asm.Group if o.TypeId == "Assembly::JointGroup")
                ground = group.newObject("App::FeaturePython", "GroundedJoint")
                JointObject.GroundedJoint(ground, link)
            except Exception as exc:
                warn("first component not fixed: %s" % exc)
