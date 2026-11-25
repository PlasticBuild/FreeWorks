# SPDX-License-Identifier: LGPL-2.1-or-later
"""extapps101: what ScanRuler saves, read into FreeCAD (formats from ScanRuler's own manual and source, AGPL, read not copied).

- XYZ text (Export cloud: one "x y z nx ny nz" line per point, millimetres; also ASC and plain "x y z" tables) -> a point cloud;
  a flat table (one z for every point) with up to MAX_SKETCH points -> sketch points.
- CSV from the 2D Measure sheet (Export CSV: elements with x, y, diameter, length, angle, sweep, in the unit its header names) ->
  a Sketch with the points, lines, circles and arcs at true scale; a spline is kept as its start point. A plain numeric
  x,y[,z] table is read as points like XYZ.
- .scanruler project (a zip: project.json, scan.<ext>, reference.<ext>, image.<ext>) -> the scan as a mesh (or STEP shape) at its true size
  in the pose it was aligned to, and the reference part, in one group; the measurements stay in the page (the count is said).
- extapps102: the project's measurements come back as reference geometry in a "Measurements" group: points, lines (axes), plane patches,
  circles, cylinder and cone axes with their radius circle, and the 2D sheet's elements as a Sketch; distances as Draft dimensions on their
  true end points and every other dimension as a text note, the value worked out here from the saved geometry.
Every reader is one undo step and puts nothing in the document when it fails."""
import csv as _csv
import json
import math
import os
import re
import tempfile
import zipfile

import FreeCAD as App

MAX_SKETCH = 2000
_PROJECT = re.compile(r"\.scanruler(?:-\d+| ?\(\d+\))?$", re.I)
_UNIT_MM = {"mm": 1.0, "in": 25.4, "px": 1.0}


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD scanimport %s: %s\n" % (site, err))
    except Exception:
        return


def is_project(path):
    return bool(_PROJECT.search(os.path.basename(path).strip()))


def kind_of(path):
    """What reader a file goes to: 'cloud', 'csv', 'project' or None."""
    name = os.path.basename(path).lower()
    if is_project(name):
        return "project"
    ext = os.path.splitext(name)[1]
    return {".xyz": "cloud", ".asc": "cloud", ".csv": "csv"}.get(ext)


def _doc(label):
    return App.ActiveDocument or App.newDocument(label)


def _name(path):
    base = os.path.splitext(os.path.basename(path))[0]
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in base).strip() or "ScanRuler"


def _numbers(line):
    out = []
    for tok in re.split(r"[\s,;]+", line.strip()):
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            return None
    return out


def read_table(path):
    """[(x, y, z)] from an XYZ, ASC or plain numeric CSV file; lines that are not numbers (comments, headers) are skipped.
    A table of two columns is flat (z = 0). Returns (points, normals_dropped)."""
    pts, normals = [], False
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            if not line.strip() or line.lstrip().startswith(("#", "//")):
                continue
            nums = _numbers(line)
            if not nums or len(nums) < 2:
                continue
            if len(nums) == 2:
                pts.append((nums[0], nums[1], 0.0))
            else:
                pts.append((nums[0], nums[1], nums[2]))
                normals = normals or len(nums) >= 6
    return pts, normals


def _cloud(doc, pts, label):
    import Points
    cloud = Points.Points()
    cloud.addPoints([App.Vector(*p) for p in pts])
    obj = doc.addObject("Points::Feature", label)
    obj.Points = cloud
    return obj


def _sketch_points(doc, pts, label):
    import Part
    sk = doc.addObject("Sketcher::SketchObject", label)
    for p in pts:
        sk.addGeometry(Part.Point(App.Vector(p[0], p[1], 0)), False)
    return sk


def import_cloud(path):
    """The points of an XYZ / ASC / numeric CSV file as a point cloud, or as sketch points for a small flat table. Returns the object."""
    pts, normals = read_table(path)
    if not pts:
        raise ValueError("no points in %s" % os.path.basename(path))
    doc = _doc(_name(path))
    flat = len({round(p[2], 9) for p in pts}) == 1
    doc.openTransaction("Import %s" % os.path.basename(path))
    try:
        if flat and len(pts) <= MAX_SKETCH:
            z = pts[0][2]
            obj = _sketch_points(doc, pts, _name(path))
            if z:
                obj.Placement = App.Placement(App.Vector(0, 0, z), App.Rotation())
            what = "%d sketch points" % len(pts)
        else:
            obj = _cloud(doc, pts, _name(path))
            what = "a cloud of %d points" % len(pts)
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    return obj, what + (" (the normals are not kept)" if normals and "cloud" in what else "")


def _length_text(mm):
    """A length in the user's unit system (inch parts read inches), as FreeCAD writes any length."""
    try:
        text = App.Units.Quantity(float(mm), App.Units.Length).UserString
        return "%.3f mm" % mm if text.endswith(" mm") else text      # millimetres keep their three decimals
    except Exception as _fw_err:
        return "%.3f mm" % mm


def _header_unit(cols):
    for c in cols:
        m = re.match(r"x_(mm|in|px)$", c.strip().lower())
        if m:
            return m.group(1)
    return None


def read_sheet(path):
    """Rows of the 2D Measure CSV: [(name, kind, x, y, diameter, length, angle_deg, sweep_deg)] in millimetres (inches converted) and
    the unit the file was in. None when the file is not that sheet."""
    with open(path, "r", newline="", errors="replace") as fh:
        rows = list(_csv.reader(fh))
    head = next((i for i, r in enumerate(rows) if r and r[0].strip().lower() == "name" and len(r) > 3 and r[1].strip().lower() == "kind"), None)
    if head is None:
        return None, None
    unit = _header_unit(rows[head]) or "mm"
    k = _UNIT_MM[unit]
    out = []

    def num(v, scale=1.0):
        try:
            return float(v) * scale if v.strip() != "" else None
        except ValueError:
            return None
    for r in rows[head + 1:]:
        if not r or not r[0].strip():
            break           # the next section (dimensions, counts) starts after a blank line
        r = r + [""] * (8 - len(r))
        out.append((r[0].strip(), r[1].strip().lower(), num(r[2], k), num(r[3], k), num(r[4], k), num(r[5], k), num(r[6]), num(r[7])))
    return out, unit


def _add_element(sk, row):
    import Part
    _n, kind, x, y, d, ln, ang, sweep = row
    if x is None or y is None:
        return 0
    c = App.Vector(x, y, 0)
    if kind == "circle" and d:
        sk.addGeometry(Part.Circle(c, App.Vector(0, 0, 1), d / 2.0), False)
    elif kind == "arc" and d and sweep is not None:
        a0 = math.radians(ang or 0.0)
        a1 = a0 + math.radians(sweep)
        lo, hi = (a0, a1) if sweep >= 0 else (a1, a0)
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(c, App.Vector(0, 0, 1), d / 2.0), lo, hi), False)
    elif kind == "line" and ln:
        t = math.radians(ang or 0.0)
        h = App.Vector(math.cos(t), math.sin(t), 0) * (ln / 2.0)
        sk.addGeometry(Part.LineSegment(c - h, c + h), False)
    else:               # a point, or a spline (kept as where it starts)
        sk.addGeometry(Part.Point(c), False)
    return 1


def import_sheet(path):
    """A 2D Measure CSV as a Sketch (points, lines, circles, arcs at true scale); a plain numeric table is read as points instead."""
    rows, unit = read_sheet(path)
    if rows is None:
        return import_cloud(path)
    if not rows:
        raise ValueError("no elements in %s" % os.path.basename(path))
    doc = _doc(_name(path))
    doc.openTransaction("Import %s" % os.path.basename(path))
    try:
        sk = doc.addObject("Sketcher::SketchObject", _name(path))
        n = sum(_add_element(sk, r) for r in rows)
        if not n:
            raise ValueError("no element with a position in %s" % os.path.basename(path))
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    note = " (in pixels: the image was not calibrated, so the sketch is not at true size)" if unit == "px" else ""
    return sk, "a sketch of %d elements%s" % (n, note)


def _matrix(rigid, scale):
    r, t = rigid["r"], rigid["t"]
    m = App.Matrix()
    m.A11, m.A12, m.A13, m.A14 = r[0] * scale, r[1] * scale, r[2] * scale, t[0]
    m.A21, m.A22, m.A23, m.A24 = r[3] * scale, r[4] * scale, r[5] * scale, t[1]
    m.A31, m.A32, m.A33, m.A34 = r[6] * scale, r[7] * scale, r[8] * scale, t[2]
    return m


def read_project(path):
    """(manifest dict, {member: bytes}) of a .scanruler file; ValueError when it is not one."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "project.json" not in names:
                raise ValueError("not a ScanRuler project file")
            manifest = json.loads(z.read("project.json").decode("utf-8"))
            members = {n: z.read(n) for n in names if n != "project.json" and "/" not in n and "\\" not in n and n != "__proto__"}
    except zipfile.BadZipFile:
        raise ValueError("not a ScanRuler project file")
    if manifest.get("app") not in (None, "ScanRuler"):
        raise ValueError("not a ScanRuler project file")
    return manifest, members


def _one(manifest, key):
    """The scan or reference entry: member name, file name, units."""
    if key == "scan":
        e = manifest.get("scan")
    else:
        e = (manifest.get("deviation") or {}).get("reference")
    return e if isinstance(e, dict) and e.get("member") else None


def _v(a):
    return App.Vector(float(a[0]), float(a[1]), float(a[2]))


def _unit(a):
    v = _v(a)
    return v.normalize() if v.Length > 1e-12 else App.Vector(0, 0, 1)


def _role(fit, role):
    """(point, direction) a fit stands for as a 'point', an 'axis' or a 'plane' in a dimension, or None."""
    k = fit.get("kind")
    c = _v(fit["center"]) if "center" in fit else None
    if role == "point":
        return (c, None) if k in ("point", "sphere") else None
    if role == "axis":
        if k == "line":
            return c, _unit(fit["dir"])
        if k in ("cylinder", "cone", "torus"):
            return c, _unit(fit["axis"])
        if k == "circle":
            return c, _unit(fit["normal"])
        return None
    if role == "plane":
        return (c, _unit(fit["normal"])) if k == "plane" else None
    return None


def _closest_axes(a, da, b, db):
    """The points on two skew lines where they are nearest (the caller handles parallel lines)."""
    w = a - b
    d, e = da.dot(db), w.dot(da)
    f, g = db.dot(w), da.dot(da)
    den = g * db.dot(db) - d * d
    t = (d * f - e * db.dot(db)) / den
    u = (g * f - d * e) / den
    return a + da * t, b + db * u


def _angle_deg(d1, d2, flat=False):
    c = max(-1.0, min(1.0, d1.dot(d2)))
    return math.degrees(math.acos(abs(c))) if not flat else math.degrees(math.asin(abs(c)))


def dimension_value(kind, fits):
    """(value, unit, (p1, p2) end points of a distance or None, anchor) of a dimension from the saved geometry, or None when it cannot
    be worked out here (a tolerance, a missing element, a case the app resolves by a rule this does not repeat)."""
    try:
        if kind == "size-diameter":
            f = fits[0]
            r = f.get("minorRadius") if f.get("kind") == "torus" else f.get("radius")
            return (2 * r, "mm", None, _v(f["center"])) if r else None
        if kind == "dist-point-point":
            a, b = _role(fits[0], "point")[0], _role(fits[1], "point")[0]
            return (a.distanceToPoint(b), "mm", (a, b), a)
        if kind == "dist-point-axis":
            p, (c, d) = _role(fits[0], "point")[0], _role(fits[1], "axis")
            foot = c + d * (p - c).dot(d)
            return (p.distanceToPoint(foot), "mm", (p, foot), p)
        if kind == "dist-point-plane":
            p, (c, n) = _role(fits[0], "point")[0], _role(fits[1], "plane")
            dist = (p - c).dot(n)
            return (dist, "mm", (p, p - n * dist), p)
        if kind == "dist-axis-axis":
            (a, da), (b, db) = _role(fits[0], "axis"), _role(fits[1], "axis")
            n = da.cross(db)
            if n.Length < 1e-9:
                w = b - a
                foot = a + da * w.dot(da)
                return (b.distanceToPoint(foot), "mm", (foot, b), a)
            p, q = _closest_axes(a, da, b, db)
            return (p.distanceToPoint(q), "mm", (p, q), p)
        if kind == "dist-axis-plane":
            (a, da), (c, n) = _role(fits[0], "axis"), _role(fits[1], "plane")
            dist = (a - c).dot(n)
            return (abs(dist), "mm", (a, a - n * dist), a)
        if kind == "dist-plane-plane":
            (c1, n1), (c2, n2) = _role(fits[0], "plane"), _role(fits[1], "plane")
            if abs(n1.dot(n2)) < 0.999:
                return None          # planes that are not parallel have no single distance: the app's rule is not repeated
            dist = (c2 - c1).dot(n1)
            return (abs(dist), "mm", (c2, c2 - n1 * dist), c1)
        if kind == "angle-axis-axis":
            (a, da), (b, db) = _role(fits[0], "axis"), _role(fits[1], "axis")
            return (_angle_deg(da, db), "deg", None, a)
        if kind == "angle-axis-plane":
            (a, da), (c, n) = _role(fits[0], "axis"), _role(fits[1], "plane")
            return (_angle_deg(da, n, True), "deg", None, a)
        if kind == "angle-plane-plane":
            (c1, n1), (c2, n2) = _role(fits[0], "plane"), _role(fits[1], "plane")
            return (_angle_deg(n1, n2), "deg", None, c1)
    except Exception as _fw_err:
        _fw_log("dimension_value", _fw_err)
    return None


def _shape_of(fit):
    """The reference geometry (a Part shape) of one saved fit, or None."""
    import Part
    k = fit.get("kind")
    if k == "point" or k == "sphere":
        return Part.Vertex(_v(fit["center"]))
    c = _v(fit["center"]) if "center" in fit else None
    if k == "line":
        d, h = _unit(fit["dir"]), float(fit.get("length") or 1.0) / 2.0
        return Part.makeLine(c - d * h, c + d * h)
    if k == "plane":
        u, w = _unit(fit["basisU"]), _unit(fit["basisV"])
        eu, ev = float(fit.get("extentU") or 1.0), float(fit.get("extentV") or 1.0)
        pts = [c - u * eu - w * ev, c + u * eu - w * ev, c + u * eu + w * ev, c - u * eu + w * ev]
        return Part.Face(Part.makePolygon(pts + [pts[0]]))
    if k in ("cylinder", "cone"):
        d, h = _unit(fit["axis"]), max(float(fit.get("length") or 1.0), 1e-3) / 2.0
        return Part.makeCompound([Part.makeLine(c - d * h, c + d * h), Part.makeCircle(float(fit["radius"]), c, d)])
    if k == "torus":
        return Part.makeCircle(float(fit["majorRadius"]), c, _unit(fit["axis"]))
    if k == "circle":
        return Part.makeCircle(float(fit["radius"]), c, _unit(fit["normal"]))
    return None


def _flat_sketch(doc, flat, label):
    """The 2D sheet's elements (those with a saved fit, in millimetres) as one Sketch."""
    import Part
    els = [e for e in (flat.get("elements") or []) if isinstance(e, dict) and isinstance(e.get("fit"), dict)]
    if not els:
        return None, 0
    sk = doc.addObject("Sketcher::SketchObject", label)
    z = App.Vector(0, 0, 1)
    n = 0
    for e in els:
        f = e["fit"]
        k = f.get("kind")
        try:
            if k == "point":
                sk.addGeometry(Part.Point(App.Vector(f["at"][0], f["at"][1], 0)), False)
            elif k == "line":
                c = App.Vector(f["center"][0], f["center"][1], 0)
                d = App.Vector(f["dir"][0], f["dir"][1], 0).normalize() * (float(f["length"]) / 2.0)
                sk.addGeometry(Part.LineSegment(c - d, c + d), False)
            elif k == "circle":
                sk.addGeometry(Part.Circle(App.Vector(f["center"][0], f["center"][1], 0), z, float(f["radius"])), False)
            elif k == "arc":
                circ = Part.Circle(App.Vector(f["center"][0], f["center"][1], 0), z, float(f["radius"]))
                sk.addGeometry(Part.ArcOfCircle(circ, float(f["start"]), float(f["start"]) + float(f["sweep"])), False)
            elif k == "spline" and len(f.get("points") or []) >= 2:
                bs = Part.BSplineCurve()
                bs.interpolate([App.Vector(p[0], p[1], 0) for p in f["points"]], PeriodicFlag=bool(f.get("closed")))
                sk.addGeometry(bs, False)
            else:
                continue
            n += 1
        except Exception as _fw_err:
            _fw_log("flat element %s" % k, _fw_err)
    if not n:
        doc.removeObject(sk.Name)
        return None, 0
    sk.Label = label
    return sk, n


def rebuild_measurements(doc, group, manifest):
    """The project's 3D elements, dimensions and 2D sheet as reference geometry in a group inside `group`. Returns a sentence."""
    import Draft
    scan = manifest.get("scan") or {}
    elements = [e for e in (scan.get("elements") or []) if isinstance(e, dict)]
    by_id, made, skipped = {}, 0, 0
    box = doc.addObject("App::DocumentObjectGroup", "Measurements")
    group.addObject(box)
    for e in elements:
        fit = e.get("fit")
        if not isinstance(fit, dict):
            skipped += 1
            continue
        try:
            shape = _shape_of(fit)
        except Exception as _fw_err:
            _fw_log("element shape", _fw_err)
            shape = None
        if shape is None:
            skipped += 1
            continue
        obj = doc.addObject("Part::Feature", "Element")
        obj.Shape = shape
        obj.Label = str(e.get("name") or "Element")
        box.addObject(obj)
        by_id[e.get("id")] = fit
        made += 1
    dims_done = dims_note = 0
    for d in scan.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        if not d.get("refs"):
            continue
        name = str(d.get("name") or d.get("type") or "Dimension")
        fits = [by_id.get(r) for r in d.get("refs") or []]
        res = dimension_value(str(d.get("type")), fits) if fits and all(fits) else None
        try:
            if res is None:
                at = _v(next(iter(f for f in fits if f and "center" in f))["center"]) if any(f and "center" in f for f in fits) else App.Vector(0, 0, 0)
                note = Draft.make_text(["%s (%s)" % (name, d.get("type")), "value not rebuilt here"], placement=at)
            else:
                value, unit, ends, anchor = res
                text = "%s: %s" % (name, _length_text(value) if unit == "mm" else "%.3f deg" % value)     # extapps113: in the units of the part
                if ends is not None and ends[0].distanceToPoint(ends[1]) > 1e-6:
                    note = Draft.make_linear_dimension(ends[0], ends[1])
                    note.Label = name
                    dims_done += 1
                    box.addObject(note)
                    continue
                note = Draft.make_text([text], placement=anchor)
                dims_done += 1
            note.Label = name
            box.addObject(note)
            if res is None:
                dims_note += 1
        except Exception as _fw_err:
            _fw_log("dimension note", _fw_err)
    flat = manifest.get("flat") or {}
    sk, nflat = _flat_sketch(doc, flat, "Sheet")
    if sk is not None:
        box.addObject(sk)
    bits = []
    if made or skipped:
        bits.append("%d elements as reference geometry%s" % (made, (" (%d without saved geometry)" % skipped) if skipped else ""))
    if dims_done or dims_note:
        bits.append("%d dimensions%s" % (dims_done + dims_note, (" (%d as notes without a value)" % dims_note) if dims_note else ""))
    if nflat:
        bits.append("the sheet's %d 2D elements as a sketch" % nflat)
    if not (made or nflat or dims_done or dims_note):
        doc.removeObject(box.Name)          # nothing was rebuilt: no empty folder
    return ", ".join(bits)


def import_project(path):
    """The scan (true size, in the pose it was aligned to) and the reference part of a .scanruler project, in one group."""
    manifest, members = read_project(path)
    doc = _doc(_name(path))
    folder = tempfile.mkdtemp(prefix="freecad-scanruler-project-")
    made = []
    doc.openTransaction("Import %s" % os.path.basename(path))
    try:
        group = doc.addObject("App::DocumentObjectGroup", _name(path))
        for key, label in (("scan", "Scan"), ("reference", "Reference")):
            e = _one(manifest, key)
            if e is None or e["member"] not in members:
                continue
            member = e["member"]
            target = os.path.join(folder, member)
            with open(target, "wb") as fh:
                fh.write(members[member])
            step = os.path.splitext(member)[1].lower() in (".step", ".stp")
            units = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}.get(e.get("units") or "mm", 1.0)
            scale = 1.0 if step else units
            scale *= float(e.get("scale") or 1.0) if key == "scan" else 1.0
            rigid = manifest.get("scan", {}).get("appliedAlignment") if key == "scan" else None
            if step:
                import Part
                shape = Part.read(target)
                if scale != 1.0:
                    m = App.Matrix(); m.scale(scale, scale, scale)
                    shape = shape.transformGeometry(m)
                if rigid:
                    shape = shape.transformGeometry(_matrix(rigid, 1.0))
                obj = doc.addObject("Part::Feature", label)
                obj.Shape = shape
            else:
                import Mesh
                mesh = Mesh.Mesh(target)
                if scale != 1.0 or rigid:
                    mesh.transform(_matrix(rigid or {"r": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0]}, scale))
                obj = doc.addObject("Mesh::Feature", label)
                obj.Mesh = mesh
            obj.Label = "%s %s" % (label, os.path.splitext(e.get("fileName") or member)[0])
            group.addObject(obj)
            made.append(obj)
        if not made:
            raise ValueError("no scan or reference part in %s" % os.path.basename(path))
        try:
            measured = rebuild_measurements(doc, group, manifest)
        except Exception as _fw_err:
            _fw_log("rebuild_measurements", _fw_err)
            measured = ""
        doc.recompute()
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()
    sc = manifest.get("scan") or {}
    els, dims = len(sc.get("elements") or []), len(sc.get("dimensions") or [])
    img = [m for m in members if m.lower().startswith("image.")]
    extra = []
    if measured:
        extra.append(measured)
    elif els or dims:
        extra.append("its %d elements and %d dimensions have no saved geometry to rebuild" % (els, dims))
    if img:
        extra.append("the flatbed image is in %s" % folder)
        with open(os.path.join(folder, img[0]), "wb") as fh:
            fh.write(members[img[0]])
    return group, "%d part%s%s" % (len(made), "s" if len(made) != 1 else "", ("; " + "; ".join(extra)) if extra else "")


def open_any(path):
    """(object, what) for a file of kind_of(path); raises on a bad file."""
    k = kind_of(path)
    if k == "project":
        return import_project(path)
    if k == "csv":
        return import_sheet(path)
    if k == "cloud":
        return import_cloud(path)
    raise ValueError("not a ScanRuler file")
