""











import os
import shutil
import tempfile
from pathlib import Path

import FreeCAD as App

from . import slicer as backend


# ---------------------------------------------------------------------- colours
def part_colour(obj):
    """'#RRGGBB' of a FreeCAD object's colour (its appearance, else its shape colour), or None."""
    vobj = getattr(obj, "ViewObject", None)
    if vobj is None:
        return None
    c = None
    try:
        app = getattr(vobj, "ShapeAppearance", None)
        if app:
            c = app[0].DiffuseColor
    except Exception as error:
        backend._fw_log("slicer3mf appearance", error)
    if c is None:
        c = getattr(vobj, "ShapeColor", None)
    if not c:
        return None
    r, g, b = [max(0, min(255, int(round(float(x) * 255)))) for x in tuple(c)[:3]]
    return "#%02X%02X%02X" % (r, g, b)


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def colour_slots(colours, limit, preset):
    """Filament slots for the parts' colours: ([{"preset", "colour"}], [slot of each part, 1-based]). Parts with no
    colour print with the first slot; past the limit a colour takes the nearest slot's."""
    slots, slot_of = [], []
    for c in colours:
        if not c:
            slot_of.append(1)
            continue
        known = [s["colour"].upper() for s in slots]
        if c.upper() in known:
            slot_of.append(known.index(c.upper()) + 1)
        elif len(slots) < max(1, limit):
            slots.append({"preset": preset, "colour": c.upper()})
            slot_of.append(len(slots))
        else:
            rgb = _rgb(c)
            near = min(range(len(slots)), key=lambda i: sum((a - b) ** 2 for a, b in zip(_rgb(slots[i]["colour"]), rgb)))
            slot_of.append(near + 1)
    if not slots:
        slots = [{"preset": preset, "colour": ""}]
    return slots, slot_of


def _source_object(source):
    if isinstance(source, tuple) and len(source) == 2 and source[0] in App.listDocuments():
        return App.getDocument(source[0]).getObject(source[1])
    return None


# ---------------------------------------------------------------------- what is sent
def gather(key, objects=None):
    """{"items": [(name, shape, matrix, plate)], "sources": [object or None], "plates": [names], "choice": {..},
    "current": plate} for this slicer: the 3D Slicer panel's plates when that panel (of this slicer) has parts on them,
    else the given FreeCAD objects (else the selected or every printable body)."""
    panel = None
    try:
        from . import slicerui
        panel = slicerui.SlicerPanel.current
        saved_choice = slicerui.saved(key)
    except Exception as error:
        backend._fw_log("slicer3mf panel", error)
        saved_choice = {}
    if panel is not None and getattr(panel, "key", None) == key and panel.bed.items:
        bed = panel.bed
        return {"items": bed.slice_items(), "sources": [_source_object(it.source) for it in bed.items],
                "plates": list(bed.plates), "choice": dict(panel.choice), "current": bed.current, "panel": True,
                "locked": sorted(getattr(bed, "locked", ()) or ())}
    objects = objects if objects is not None else backend.printable()
    items = [(o.Label, backend.mesh_object(o) if backend.is_mesh(o) else o.Shape, list(App.Matrix().A), 0)
             for o in objects]
    return {"items": items, "sources": list(objects), "plates": [""], "choice": dict(saved_choice), "current": 0,
            "panel": False}


def _centred(slicer_obj, printer, items):
    """Parts as they stand in FreeCAD, moved together so their middle is the plate's middle and they sit on it."""
    try:
        area = slicer_obj.resolve("machine", printer).get("printable_area") or []
        pts = [tuple(float(v) for v in str(p).split("x")) for p in area]
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    except Exception:
        cx, cy = 128.0, 128.0
    box = None
    for _n, shape, _m, _p in items:
        b = shape.BoundBox
        box = b if box is None else box.united(b)
    if box is None:
        return items
    m = App.Matrix()
    m.move(App.Vector(cx - box.Center.x, cy - box.Center.y, -box.ZMin))
    return [(n, s, list(m.A), p) for n, s, _m, p in items]


def slots_for(slicer_obj, data):
    """(slots, slot of each part): the panel's when it gives parts slots, else from the parts' colours."""
    choice = data["choice"]
    slots, slot_of = choice.get("slots") or [], choice.get("slot_of") or []
    if data.get("panel") and len(slots) > 1 and any(k != 1 for k in slot_of):
        return slots, slot_of
    limit = 16
    if hasattr(slicer_obj, "slot_limit") and choice.get("printer"):
        try:
            limit = slicer_obj.slot_limit(choice.get("printer"))
        except Exception as error:
            backend._fw_log("slicer3mf limit", error)
    return colour_slots([part_colour(o) if o is not None else None for o in data["sources"]], limit,
                        choice.get("filament") or "")


# ---------------------------------------------------------------------- writing
def write(key, path, objects=None, env=None):
    """Write the 3MF for this slicer. Returns (ok, message, [paths written])."""
    s = backend.get(key)
    if s is None:
        return False, "No such slicer.", []
    data = gather(key, objects)
    if not data["items"]:
        return False, "Nothing to send: pick a body or solid, or put parts on the 3D Slicer plate.", []
    choice = data["choice"]
    if not choice.get("printer"):
        cur = s.current_presets() if hasattr(s, "current_presets") else {}
        choice.setdefault("printer", cur.get("machine") or "")
        choice["filament"] = choice.get("filament") or cur.get("filament") or ""
        choice["process"] = choice.get("process") or cur.get("print") or ""
    items = data["items"] if data["panel"] else _centred(s, choice.get("printer"), data["items"])
    slots, slot_of = slots_for(s, data)
    if key == "prusa":
        return _write_prusa(s, items, data, slot_of, path)
    from . import slicerproject
    if not (choice.get("printer") and choice.get("filament") and choice.get("process")):
        return False, "Pick a printer, filament and process in the 3D Slicer panel first.", []
    choice["slots"] = slots
    over = dict(choice.get("filament_overrides") or {})
    if slots and slots[0].get("colour"):
        over["filament_colour"] = [slots[0]["colour"]]
        over["default_filament_colour"] = [slots[0]["colour"]]
    choice["filament_overrides"] = over
    ok, msg = slicerproject.save_project(s, choice, items, data["plates"], path, env, locked=data.get("locked") or (),
                                         slots=slots, slot_of=slot_of)
    return ok, msg, [Path(path)] if ok else []


def _write_prusa(s, items, data, slot_of, path):
    from . import slicerprusa
    work = Path(tempfile.mkdtemp(prefix="swstyle-print3d-"))
    try:
        linear, angular = s.mesh_deflection()
        meshes, _ = backend.export_items(items, work, linear, angular)
        names = [it[0] for it in items]
        plates = sorted({p for _m, p in meshes})
        written = []
        for plate in plates:
            obs = []
            for k, (mesh, p) in enumerate(meshes):
                if p != plate:
                    continue
                obs.append(slicerprusa.mesh_object(mesh, names[k], slot_of[k] if k < len(slot_of) else 1))
            out = Path(path) if len(plates) == 1 else \
                Path(path).with_name("%s - plate %d%s" % (Path(path).stem, plate + 1, Path(path).suffix))
            slicerprusa.write_3mf(obs, out)
            written.append(out)
        return True, ", ".join(p.name for p in written), written
    except Exception as error:
        return False, str(error), []
    finally:
        shutil.rmtree(str(work), ignore_errors=True)


def default_path(key, folder):
    doc = App.ActiveDocument
    name = backend.safe_name(doc.Label if doc else "Part")
    return Path(folder) / ("%s-%s.3mf" % (name, key))
