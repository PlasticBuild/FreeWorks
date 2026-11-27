# SPDX-License-Identifier: LGPL-2.1-or-later
""
















import os
import shutil
import tempfile

import FreeCAD as App

from . import msg, params, swapp, tell


class SaveError(RuntimeError):
    pass


def _need_solidworks():
    if not swapp.solidworks_installed():
        raise SaveError("Saving SolidWorks files needs SolidWorks installed on this PC: SolidWorks "
                        "itself writes the file. Save as STEP or Parasolid instead to open it in "
                        "SolidWorks elsewhere.")


def _backup(path):
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
        return path + ".bak"
    return None


def _solid_objects(objs):
    """The objects whose shapes make the part: bodies and loose solids, not their insides."""
    keep = []
    for o in objs:
        if o.TypeId == "PartDesign::Body" or (o.isDerivedFrom("Part::Feature") and not o.InList):
            if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids:
                keep.append(o)
        elif o.TypeId in ("App::Part", "App::Link"):
            keep.append(o)
    return keep or [o for o in objs if hasattr(o, "Shape") and not o.Shape.isNull()]


def export_part(objs, path):
    _need_solidworks()
    objs = _solid_objects(objs)
    if not objs:
        raise SaveError("Nothing with a solid shape to save.")
    tmp = tempfile.mkdtemp(prefix="fw-sw-")
    try:
        import Import
        step = os.path.join(tmp, "part.step")
        Import.export(objs, step)
        bodies = [o for o in objs if o.TypeId == "PartDesign::Body"]
        source = _unchanged_source(bodies[0]) if len(bodies) == 1 and len(objs) == 1 else None
        if source:
            if os.path.normcase(os.path.abspath(source)) != os.path.normcase(os.path.abspath(path)):
                _backup(path)
                shutil.copyfile(source, path)
            return
        job, args = "save-part", [step, path]
        if len(bodies) == 1 and len(objs) == 1 and params().GetBool("SaveFeatureTree", True):
            import json
            from . import fctree
            data = fctree.body_data(bodies[0])
            data["volume"] = bodies[0].Shape.Volume
            tree = os.path.join(tmp, "tree.json")
            with open(tree, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            job, args = "save-tree", [tree, step, path]
        bak = _backup(path)
        label = "Saving %s..." % os.path.basename(path)
        try:
            try:
                res = swapp.run(job, args, label)
            except swapp.HelperError as exc:
                if job != "save-tree" or str(exc) == "Cancelled.":
                    raise

                res = swapp.run("save-part", [step, path], label)
                res.update(how="solid", tree_not_saved="The other CAD program stopped while rebuilding the features (%s)" % exc)
        except swapp.HelperError as exc:
            if bak:
                shutil.copy2(bak, path)
            raise SaveError(str(exc))
        for note in res.get("notes", []):
            tell(note, icon="warning")
        if res.get("how") == "solid" and res.get("tree_not_saved"):
            msg("%s: saved as an imported body; the feature tree was not carried over (%s)"
                % (os.path.basename(path), res["tree_not_saved"]))
        elif res.get("how") == "tree":
            msg("%s: saved with its feature tree" % os.path.basename(path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    msg("Saved %s" % path)


def _assembly(objs):
    for o in objs:
        if o.TypeId == "Assembly::AssemblyObject":
            return o
    doc = objs[0].Document if objs else App.ActiveDocument
    for o in doc.RootObjects:
        if o.TypeId == "Assembly::AssemblyObject":
            return o
    return None


def _rows(placement):
    m = placement.toMatrix()
    return [[m.A11, m.A12, m.A13, m.A14], [m.A21, m.A22, m.A23, m.A24],
            [m.A31, m.A32, m.A33, m.A34], [0.0, 0.0, 0.0, 1.0]]


def _safe(name):
    return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name).strip() or "Part"



# workbench carry only their JointType
_JOINT_MATE = {"Fixed": "Lock", "Cylindrical": "Concentric", "Slider": "Concentric", "Revolute": "Concentric",
               "Ball": "Coincident", "Parallel": "Parallel", "Perpendicular": "Perpendicular", "Angle": "Angle"}


def _mate_kind(joint):
    kind = getattr(joint, "FwMateType", "")
    if kind:
        return kind
    jt = getattr(joint, "JointType", "")
    if jt == "Distance":
        return "Distance" if abs(float(getattr(joint, "Distance", 0))) > 1e-9 else "Coincident"
    return _JOINT_MATE.get(jt)


def _point_on(shape):
    ""
    kind = shape.ShapeType
    if kind == "Vertex":
        return shape.Point
    if kind == "Edge":
        a, b = shape.ParameterRange
        return shape.valueAt((a + b) / 2.0)
    pts, tris = shape.tessellate(0.1)
    best, area = None, -1.0
    for i, j, k in tris:
        a = (pts[j] - pts[i]).cross(pts[k] - pts[i]).Length
        if a > area:
            best, area = (pts[i] + pts[j] + pts[k]) * (1.0 / 3.0), a
    return best if best is not None else shape.CenterOfMass


def _mate_ref(ref, index):
    """{"comp": component number, "kind": Face/Edge/Vertex, "point": assembly mm, "local": part mm}."""
    if not ref or ref[0] is None:
        return None
    obj, subs = ref[0], ref[1]
    sub = subs[0] if isinstance(subs, (list, tuple)) else subs
    comp = obj
    if obj not in index:                    # a joint made from the assembly root: Assembly.Component.Face
        first = sub.split(".")[0]
        comp = obj.Document.getObject(first)
        if comp not in index:
            return None
        sub = sub[len(first) + 1:]
    shape = comp.getSubObject(sub)
    if shape is None or shape.isNull():
        return None
    number, matrix = index[comp]
    p = _point_on(shape)
    local = matrix.inverse().multVec(p)
    kind = shape.ShapeType
    return {"comp": number, "kind": kind if kind in ("Face", "Edge", "Vertex") else "Face",
            "point": [p.x, p.y, p.z], "local": [local.x, local.y, local.z]}


def _mates(asm, index):
    ""
    rows, fixed, notes = [], [], []
    for group in [o for o in asm.Group if o.TypeId == "Assembly::JointGroup"]:
        for j in group.Group:
            ground = getattr(j, "ObjectToGround", None)
            if ground is not None:
                if ground in index:
                    fixed.append(index[ground][0])
                continue
            if not hasattr(j, "JointType") or not hasattr(j, "Reference1"):
                continue
            name = j.Label.split(" (")[0]
            kind = _mate_kind(j)
            if kind is None:
                notes.append("%s: %s mate not saved (the file format has no plain mate for it)" % (name, j.JointType))
                continue
            refs = [_mate_ref(j.Reference1, index), _mate_ref(j.Reference2, index)]
            if kind == "Lock":
                comps = [r["comp"] for r in refs if r]
                if len(comps) != 2:
                    notes.append("%s: its components were not found" % name)
                    continue
            elif None in refs:
                notes.append("%s: a picked face or edge was not found" % name)
                continue
            rows.append({"name": name, "kind": kind, "refs": refs,
                         "distance": float(getattr(j, "Distance", 0) or 0),
                         "angle": float(getattr(j, "Angle", 0) or 0),
                         "lock_rotation": bool(getattr(j, "FwLockRotation", False)) or j.JointType == "Slider",
                         "suppressed": bool(getattr(j, "Suppressed", False))})
            if j.JointType == "Revolute" and not getattr(j, "FwMateType", ""):
                notes.append("%s: Revolute saved as a Concentric mate" % name)
    return rows, fixed, notes


def _unchanged_source(target):
    """The .SLDPRT an imported body came from, when nothing has been added to the body since."""
    path = getattr(target, "FwSourceFile", "")
    if not path or target.TypeId != "PartDesign::Body" or not os.path.isfile(path):
        return None
    if not any(o.isDerivedFrom("PartDesign::Feature") and o.TypeId != "PartDesign::FeatureBase" for o in target.Group):
        return path
    from . import part as partmod
    key = getattr(target, "FwSourceShape", "")
    if key and key == partmod.shape_key(target.Shape):     # opened with its tree and not edited since
        return path
    return None


def _tree_body(target):
    """The body whose features make the component's part: the body itself, or the one body of a
    Part container (its other children only datums and sketches), else None."""
    if target.TypeId == "PartDesign::Body":
        return target
    if target.TypeId != "App::Part":
        return None
    bodies, others = [], []
    for o in target.Group:
        if o.TypeId == "PartDesign::Body":
            bodies.append(o)
        elif o.TypeId in ("App::Origin", "Sketcher::SketchObject") or o.isDerivedFrom("App::DocumentObjectGroup") \
                or o.TypeId.startswith(("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point")):
            continue
        elif not getattr(o, "Shape", None) or o.Shape.isNull() or not o.Shape.Solids:
            continue
        else:
            others.append(o)
    return bodies[0] if len(bodies) == 1 and not others else None


def export_assembly(objs, path):
    _need_solidworks()
    asm = _assembly(objs)
    if asm is None:
        raise SaveError("The document has no assembly to save.")
    if params().GetBool("AssemblyTree", True):
        try:                    # subassemblies, patterns, folders, advanced mates, assembly cuts
            from . import asmrt
            import swstyle.asmcore
        except ImportError:
            asmrt = None
        if asmrt is not None:
            try:
                return asmrt.export_assembly(asm, path)
            except swapp.HelperError as exc:
                if "save-asm2" not in str(exc) and "unknown" not in str(exc).lower():
                    raise SaveError(str(exc))
                msg("The helper has no assembly save: saving components and mates only")
    folder = os.path.dirname(os.path.abspath(path))
    tmp = tempfile.mkdtemp(prefix="fw-sw-")
    try:
        import Import
        parts, files, components = [], {}, []
        index = {}                  # component -> (number, placement of its part in the assembly)
        for link in asm.Group:
            if link.TypeId != "App::Link" or link.LinkedObject is None:
                continue
            target = link.LinkedObject
            key = (target.Document.Name, target.Name)
            if key not in files:
                name = target.Document.Label if target.Document is not asm.Document else target.Label
                part_file = os.path.join(folder, _safe(name) + ".SLDPRT")
                step = os.path.join(tmp, "p%d.step" % len(files))
                # the part in its own coordinates: placement comes from the component
                saved = target.Placement
                row = {"step": step, "file": part_file}
                source = _unchanged_source(target)
                if source:

                    if os.path.normcase(source) != os.path.normcase(os.path.abspath(part_file)):
                        _backup(part_file)
                    parts.append({"copy": source, "file": part_file})
                    files[key] = part_file
                    where = link.Placement.multiply(target.Placement)
                    index[link] = (len(components), where.toMatrix())
                    components.append({"file": part_file, "name": link.Label, "matrix": _rows(where)})
                    continue
                try:
                    target.Placement = App.Placement()
                    Import.export([target], step)
                    body = _tree_body(target)
                    if body is not None and params().GetBool("SaveFeatureTree", True):
                        from . import fctree
                        try:
                            row["tree"] = fctree.body_data(body)         # in the part's own coordinates
                            row["tree"]["volume"] = body.Shape.Volume
                        except Exception as exc:
                            msg("%s: feature tree not exported (%s)" % (name, exc))
                finally:
                    target.Placement = saved
                _backup(part_file)
                parts.append(row)
                files[key] = part_file
            where = link.Placement.multiply(target.Placement)
            index[link] = (len(components), where.toMatrix())
            components.append({"file": files[key], "name": link.Label, "matrix": _rows(where)})
        if not components:
            raise SaveError("The assembly has no components.")
        import json
        spec = os.path.join(tmp, "spec.json")
        with open(spec, "w", encoding="utf-8") as fh:
            mates, fixed, notes = _mates(asm, index) if params().GetBool("SaveMates", True) else ([], [], [])
            json.dump({"parts": parts, "components": components, "mates": mates, "fixed": fixed}, fh)
        _backup(path)
        try:
            res = swapp.run("save-asm", [spec, path], "Saving %s..." % os.path.basename(path),
                            timeout=1800)
        except swapp.HelperError as exc:
            raise SaveError(str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    made = [m for m in res.get("mates", []) if m.get("ok")]
    notes += res.get("notes", [])
    notes += ["%s: %s" % (m["name"], m.get("why", "not made")) for m in res.get("mates", []) if not m.get("ok")]
    msg("Saved %s (%d components, %d part files, %d with their feature tree, %d of %d mates)" % (
        path, len(res.get("components", [])), len(res.get("parts_written", [])), res.get("parts_with_tree", 0),
        len(made), len(res.get("mates", []))))
    if notes:
        tell("%s was saved. About its mates:\n\n%s" % (os.path.basename(path), "\n".join(notes)),
             icon="warning")


def export(objs, path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".sldprt":
            export_part(objs, path)
        elif ext == ".sldasm":
            export_assembly(objs, path)
        else:
            from . import cadconv
            cadconv.save_file(objs, path)
    except (SaveError, Exception) as exc:
        tell("Could not save %s:\n\n%s" % (os.path.basename(path), exc), icon="warning")
        raise
