"""Slicer projects as 3MF, the format Bambu Studio and Orca Slicer save: plates, objects where
they stand on them, and the printer / filament / process settings.

Saving: the slicer itself writes the file from its plate list (load_assemble_list) and the
settings, so Bambu Studio and Orca Slicer open it as one of their own projects.
Opening: plates and objects from the 3MF's model and Metadata/model_settings.config, the settings
from Metadata/project_settings.config."""
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import FreeCAD as App

from . import slicer as backend

NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def _q(tag):
    return "{%s}%s" % (NS_CORE, tag)


def _matrix(text):
    """3MF transform "m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32" (row vectors) -> App.Matrix."""
    if not text:
        return App.Matrix()
    v = [float(x) for x in text.split()]
    if len(v) != 12:
        return App.Matrix()
    return App.Matrix(v[0], v[3], v[6], v[9],
                      v[1], v[4], v[7], v[10],
                      v[2], v[5], v[8], v[11],
                      0, 0, 0, 1)


def _mesh_of(obj_el):
    """(points, facets) of a 3MF <object> holding a <mesh>, or None."""
    mesh = obj_el.find(_q("mesh"))
    if mesh is None:
        return None
    pts = [(float(v.get("x")), float(v.get("y")), float(v.get("z")))
           for v in mesh.find(_q("vertices")).findall(_q("vertex"))]
    tris = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3")))
            for t in mesh.find(_q("triangles")).findall(_q("triangle"))]
    return pts, tris


def read_project(path):
    """{"plates": [names], "objects": [{"name", "mesh" (Mesh.Mesh in world coordinates),
    "plate"}], "settings": {...}} from a Bambu Studio / Orca Slicer project 3MF."""
    import Mesh
    out = {"plates": [], "objects": [], "settings": {}}
    with zipfile.ZipFile(str(path)) as z:
        names = set(z.namelist())
        models = {}

        def model(name):
            name = name.lstrip("/")
            if name not in models:
                models[name] = ET.fromstring(z.read(name))
            return models[name]

        root = model("3D/3dmodel.model")
        objects = {o.get("id"): o for o in root.find(_q("resources")).findall(_q("object"))}
        meta_names = {}
        plates_of = {}
        if "Metadata/model_settings.config" in names:
            cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
            for o in cfg.findall("object"):
                n = o.find("metadata[@key='name']")
                if n is not None:
                    meta_names[o.get("id")] = n.get("value")
            for k, p in enumerate(cfg.findall("plate")):
                pname = p.find("metadata[@key='plater_name']")
                out["plates"].append(pname.get("value") if pname is not None else "")
                lock = p.find("metadata[@key='locked']")
                if lock is not None and lock.get("value", "").lower() in ("true", "1"):
                    out.setdefault("locked", []).append(k)
                for inst in p.findall("model_instance"):
                    oid = inst.find("metadata[@key='object_id']")
                    if oid is not None:
                        plates_of[oid.get("value")] = k
        if "Metadata/project_settings.config" in names:
            try:
                out["settings"] = json.loads(z.read("Metadata/project_settings.config").decode("utf-8"))
            except Exception:
                out["settings"] = {}

        def collect(obj_el, owner, matrix, mesh):
            got = _mesh_of(obj_el)
            if got is not None:
                pts, tris = got
                m = Mesh.Mesh([[pts[a], pts[b], pts[c]] for a, b, c in tris])
                m.transform(matrix)
                mesh.addMesh(m)
            comps = obj_el.find(_q("components"))
            if comps is None:
                return
            for c in comps.findall(_q("component")):
                sub_path = c.get("{%s}path" % NS_PROD)
                sub_root = model(sub_path) if sub_path else root
                sub_objs = {o.get("id"): o for o in sub_root.find(_q("resources")).findall(_q("object"))}
                sub = sub_objs.get(c.get("objectid"))
                if sub is not None:
                    collect(sub, owner, matrix.multiply(_matrix(c.get("transform"))), mesh)

        for item in root.find(_q("build")).findall(_q("item")):
            oid = item.get("objectid")
            obj = objects.get(oid)
            if obj is None:
                continue
            mesh = Mesh.Mesh()
            collect(obj, oid, _matrix(item.get("transform")), mesh)
            if mesh.CountFacets == 0:
                continue
            out["objects"].append({"name": meta_names.get(oid) or obj.get("name") or "Object %s" % oid,
                                   "mesh": mesh, "plate": plates_of.get(oid, 0)})
    if not out["plates"]:
        out["plates"] = [""]
    return out


def apply_to_plate(bed, project):
    """Put a read project on the plate, replacing what is there. The slicers lay plates out in a
    grid (see SlicerPlate.plate_origin): each object is moved back onto its own plate."""
    from . import slicerplate
    bed.plates = list(project["plates"])
    bed.locked = {k for k in project.get("locked", []) if 0 <= k < len(bed.plates)}
    bed.items = []
    for o in project["objects"]:
        plate = min(max(o["plate"], 0), len(bed.plates) - 1)
        m = o["mesh"].copy()
        m.translate(-bed.plate_origin(plate).x, -bed.plate_origin(plate).y, 0)
        it = slicerplate.Item(o["name"], None, m, None)
        it.plate = plate
        it.pinned = True
        box = m.BoundBox
        it.xy = ((box.XMin + box.XMax) / 2.0, (box.YMin + box.YMax) / 2.0)   # where it prints
        bed.items.append(it)
    bed.current = 0
    bed.selected = set()
    bed._redraw()
    bed._changed()


def choice_from_settings(s, settings):
    """Printer / filament / process names and the changes on top of each, from a project's
    settings: {"printer", "filament", "process", "overrides", "filament_overrides",
    "printer_overrides"} (a name the slicer does not know is left out)."""
    from . import slicersettings

    def first(v):
        return v[0] if isinstance(v, list) and v else v

    def strip(name):
        return re.sub(r"\s*\((FreeCAD|project)\)$", "", name or "")

    lay = slicersettings.layout(s.key)
    pages = lay["pages"]

    def differs(key, a, b):
        if (lay["options"].get(key) or {}).get("type") in ("coPercent", "coPercents"):
            # a percent option: presets write "100", project files "100%"
            a, b = slicersettings.text_of(a).rstrip("%"), slicersettings.text_of(b).rstrip("%")
        return not slicersettings.same(a, b)

    choice = {}
    for tab, kind, id_key, over_name in (("printer", "machine", "printer_settings_id", "printer_overrides"),
                                         ("filament", "filament", "filament_settings_id", "filament_overrides"),
                                         ("process", "process", "print_settings_id", "overrides")):
        name = strip(first(settings.get(id_key)))
        if not name or s.preset(kind, name) is None:
            continue
        choice[{"machine": "printer"}.get(kind, kind)] = name
        base = s.resolve(kind, name)
        over = {}
        for page in pages.get(tab, []):
            for group in page["groups"]:
                for key in group["options"]:
                    if key in settings and key in base and differs(key, settings[key], base[key]):
                        over[key] = settings[key]
        choice[over_name] = over
    return choice


def save_project(slicer, choice, items, plates, path, env=None, locked=(), slots=None, slot_of=None):
    """Write a project 3MF with the slicer's own writer. items = [(name, shape or mesh, matrix,
    plate)]; env = the slicer's QProcessEnvironment; slots / slot_of: the filament slots ([{"preset", "colour"}]) and
    the slot of each item (1-based), so each object keeps its filament and colour. Returns (ok, message)."""
    from PySide import QtCore
    exe = slicer.exe()
    if exe is None:
        return False, "%s was not found." % slicer.title
    work = Path(tempfile.mkdtemp(prefix="swstyle-project-"))
    try:
        linear, angular = slicer.mesh_deflection()
        objs, _ = backend.export_items(items, work, linear, angular)
        slots = slots if slots is not None else (choice.get("slots") or [])
        slot_of = slot_of if slot_of is not None else (choice.get("slot_of") or [])
        many = len(slots) > 1 and any(k != 1 for k in slot_of)
        assemble = backend.write_assemble(objs, plates, work / "plates.json", slots=slot_of if many else None)
        name = "project.3mf"
        args = slicer.slice_args([p for p, _ in objs], choice["printer"], choice["filament"], choice["process"],
                                 choice.get("overrides") or {}, work,
                                 filament_overrides=choice.get("filament_overrides"),
                                 printer_overrides=choice.get("printer_overrides"),
                                 assemble=assemble, project=name, slice_plates=False,
                                 more_filaments=slicer.slot_files(slots, choice["printer"], work) if many else None)
        proc = QtCore.QProcess()
        proc.setWorkingDirectory(str(work))
        if env is not None:
            proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        proc.start(str(exe), [str(a) for a in args])
        proc.waitForFinished(300000)
        made = work / name
        if not made.exists():
            res = backend._read_json(work / "result.json") or {}
            text = bytes(proc.readAll()).decode("utf-8", "replace")
            return False, res.get("error_string") or (text or "the slicer wrote no file")[-400:]
        names = {Path(m).stem + "_1": it[0] for (m, _), it in zip(objs, items)}
        _rename_objects(made, names, Path(path), locked)
        return True, str(path)
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def _lock_plates(text, locked):
    """model_settings.config text with each plate's locked metadata set (true for the plates in locked)."""
    import re
    if not locked:
        return text
    parts = re.split(r"(<plate>)", text)
    out, k = [parts[0]], -1
    for piece in parts[1:]:
        if piece == "<plate>":
            k += 1
            out.append(piece)
            continue
        value = "true" if k in locked else "false"
        head, sep, tail = piece.partition("</plate>")
        if re.search(r'key="locked"', head):
            head = re.sub(r'(<metadata key="locked" value=")[^"]*(")', r"\g<1>%s\g<2>" % value, head, count=1)
        elif k in locked:
            head = '\n  <metadata key="locked" value="true"/>' + head
        out.append(head + sep + tail)
    return "".join(out)


def _rename_objects(src, names, dst, locked=()):
    """The slicer names objects after their mesh file plus "_1": give them back their own names. locked: the
    plates (0-based) saved as locked, as the slicers save a plate's lock."""
    from xml.sax.saxutils import quoteattr
    with zipfile.ZipFile(str(src)) as zin, zipfile.ZipFile(str(dst), "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Metadata/model_settings.config":
                text = data.decode("utf-8")
                for old, new in names.items():
                    text = text.replace('key="name" value=%s' % quoteattr(old), 'key="name" value=%s' % quoteattr(new))
                text = _lock_plates(text, locked)
                data = text.encode("utf-8")
            zout.writestr(info, data)
