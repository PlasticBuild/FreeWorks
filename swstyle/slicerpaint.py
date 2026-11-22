""





import zipfile
from xml.sax.saxutils import escape, quoteattr

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

KINDS = ("support", "seam", "color", "fuzzy")
TITLES = {"support": "Support Painting", "seam": "Seam Painting", "color": "Color Painting",
          "fuzzy": "Fuzzy Skin Painting"}
ATTRS = {"support": "paint_supports", "seam": "paint_seam", "color": "paint_color", "fuzzy": "paint_fuzzy_skin"}
FUZZY_COLOUR = (0.62, 0.40, 0.88)
# overlay colours: enforcer green, blocker red (as the slicers' painting)
ENFORCE_COLOUR, BLOCK_COLOUR = (0.13, 0.75, 0.33), (0.86, 0.20, 0.18)
SEAM_COLOUR = (0.95, 0.55, 0.10)


# ---------------------------------------------------------------------- data
def paint_of(item):
    """The item's paint: {"support": {face: "enforce"|"block"}, "seam": {...}, "color": {face: filament number},
    "dabs": {kind: [(x, y, z, radius, value[, options]), ...]}} (brush dabs in model coordinates, in order; value None
    erases; options: {"dir": (x, y, z)} for the Circle tool (a cylinder along the view, front faces only; without it
    the dab is a ball, the Sphere tool), {"overhang": angle} to paint overhangs only)."""
    p = getattr(item, "paint", None)
    if p is None:
        p = item.paint = {k: {} for k in KINDS}
    for k in KINDS:
        p.setdefault(k, {})
    d = p.setdefault("dabs", {})
    for k in KINDS:
        d.setdefault(k, [])
    return p


def has_paint(paint):
    if not paint:
        return False
    dabs = paint.get("dabs") or {}
    return (any(paint.get(k) for k in KINDS) or any(any(d[4] is not None for d in dabs.get(k) or []) for k in KINDS)
            or bool(paint.get("ears")))


def state(kind, value):
    """The slicers' paint state: support / seam enforce 1, block 2; colour the filament number; none 0."""
    if value is None:
        return 0
    if kind in ("support", "seam", "fuzzy"):
        return 1 if value == "enforce" else 2
    return int(value)


# ---------------------------------------------------------------------- smart fill
def _normal_near(face, point):
    try:
        u, v = face.Surface.parameter(point)
        n = face.normalAt(u, v)
        return n if n.Length > 1e-12 else None
    except Exception:
        return None


def smart_faces(shape, start, angle=30.0):
    """The CAD faces reached from one across edges where the surface turns by no more than angle degrees (the
    slicers' Smart fill: a smooth region, however many faces it is made of)."""
    import math
    faces = shape.Faces
    edge_faces = {}
    for i, f in enumerate(faces):
        for e in f.Edges:
            edge_faces.setdefault(e.hashCode(), []).append(i)
    limit = math.cos(math.radians(max(0.0, min(180.0, angle))))
    seen, todo = {start}, [start]
    while todo:
        i = todo.pop()
        for e in faces[i].Edges:
            mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
            for j in edge_faces.get(e.hashCode(), []):
                if j in seen:
                    continue
                a, b = _normal_near(faces[i], mid), _normal_near(faces[j], mid)
                if a is not None and b is not None and a.normalize().dot(b.normalize()) >= limit - 1e-9:
                    seen.add(j)
                    todo.append(j)
    return sorted(seen)


# ---------------------------------------------------------------------- brush strokes on triangles
MAX_DEPTH = 7


def _d2(a, b):
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _mid(a, b):
    return ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)


def tree(a, b, c, base, dabs, kind, depth=0):
    """The paint of one triangle: a state (int), or its four children [c0, c1, c2, c3] as the slicers split a
    triangle on all three sides (c0 at the first corner, c1 the second, c2 the third, c3 the middle one).
    base: the triangle's own value (its CAD face's paint); dabs over it in order."""
    g = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0, (a[2] + b[2] + c[2]) / 3.0)
    reach = max(_d2(g, a), _d2(g, b), _d2(g, c)) ** 0.5
    value, split = base, False
    for d in dabs:
        x, y, z, r, v = d[:5]
        centre = (x, y, z)
        dg = _d2(centre, g) ** 0.5
        if dg > _reach(d) + reach:
            continue                                   # out of reach
        if _inside(d, a) and _inside(d, b) and _inside(d, c):
            value = v                                  # the dab covers the whole triangle
            continue
        if _inside(d, g):
            value = v                                  # partly: the middle decides unless split further
        split = True
    if split and depth < MAX_DEPTH:
        edge = max(_d2(a, b), _d2(b, c), _d2(c, a)) ** 0.5
        smallest = min((d[3] for d in dabs), default=1.0)
        if edge > max(0.05, smallest / 4.0):
            ab, bc, ca = _mid(a, b), _mid(b, c), _mid(c, a)
            kids = [tree(a, ab, ca, base, dabs, kind, depth + 1), tree(ab, b, bc, base, dabs, kind, depth + 1),
                    tree(bc, c, ca, base, dabs, kind, depth + 1), tree(ab, bc, ca, base, dabs, kind, depth + 1)]
            if all(isinstance(k, int) for k in kids) and len(set(kids)) == 1:
                return kids[0]
            return kids
    return state(kind, value)


def tree_code(t):
    """The slicers' paint string of a triangle's tree (TriangleSelector::serialize, written as bbs_3mf does: 4-bit
    nibbles, the last first); "" for no paint."""
    if t == 0:
        return ""
    bits = []

    def put(node):
        if isinstance(node, int):
            bits.extend((0, 0))
            if node >= 3:
                bits.extend((1, 1))
                bits.extend(((node - 3) >> i) & 1 for i in range(4))
            else:
                bits.extend((node & 1, (node >> 1) & 1))
        else:
            bits.extend((1, 1, 0, 0))                  # three split sides, special side 0
            for k in reversed(node):                   # children last first, as the slicers write them
                put(k)
    put(t)
    nibbles = [sum(bits[i + k] << k for k in range(4)) for i in range(0, len(bits), 4)]
    return "".join("%X" % n for n in reversed(nibbles))


def leaves(a, b, c, t, out):
    """The painted pieces of a triangle's tree: [(a, b, c, state)]."""
    if isinstance(t, int):
        if t:
            out.append((a, b, c, t))
        return out
    ab, bc, ca = _mid(a, b), _mid(b, c), _mid(c, a)
    for (p, q, r), k in zip(((a, ab, ca), (ab, b, bc), (bc, c, ca), (ab, bc, ca)), t):
        leaves(p, q, r, k, out)
    return out


def _opts(d):
    return d[5] if len(d) > 5 and d[5] else {}


def _reach(d):
    """How far from its centre a dab can paint: a ball its radius, a Circle's cylinder (as deep as wide) more."""
    return d[3] * (1.42 if _opts(d).get("dir") else 1.0)


def _inside(d, p):
    """A point in the dab: a ball (Sphere) or a cylinder along the view direction (Circle), as the slicers' cursors."""
    x, y, z, r = d[:4]
    q = (p[0] - x, p[1] - y, p[2] - z)
    axis = _opts(d).get("dir")
    if not axis:
        return q[0] * q[0] + q[1] * q[1] + q[2] * q[2] <= r * r
    along = q[0] * axis[0] + q[1] * axis[1] + q[2] * axis[2]
    across2 = q[0] * q[0] + q[1] * q[1] + q[2] * q[2] - along * along
    return across2 <= r * r and abs(along) <= r


def _facet_normal(a, b, c):
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
    length = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) ** 0.5
    return (n[0] / length, n[1] / length, n[2] / length) if length > 1e-15 else None


def overhanging(normal, angle, up=(0.0, 0.0, 1.0)):
    """A facet the slicers count as an overhang at this threshold angle (degrees from the horizontal): it faces
    down more steeply than the angle allows. up: the plate's up in the object's own coordinates."""
    import math
    if normal is None:
        return False
    down = -(normal[0] * up[0] + normal[1] * up[1] + normal[2] * up[2])
    return down > math.sin(math.radians(90.0 - float(angle))) - 1e-9


def _applies(d, normal):
    """A dab's options that look at the facet: Circle paints faces turned to the eye; On overhangs only paints
    overhangs."""
    o = _opts(d)
    axis = o.get("dir")
    if axis and normal is not None and normal[0] * axis[0] + normal[1] * axis[1] + normal[2] * axis[2] > -0.05:
        return False                 # turned away from the eye, or edge-on
    if o.get("overhang") is not None and not overhanging(normal, o["overhang"], o.get("up") or (0.0, 0.0, 1.0)):
        return False
    return True


def near_dabs(dabs, a, b, c):
    g = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0, (a[2] + b[2] + c[2]) / 3.0)
    reach = max(_d2(g, a), _d2(g, b), _d2(g, c)) ** 0.5
    near = [d for d in dabs if _d2((d[0], d[1], d[2]), g) <= (_reach(d) + reach) ** 2]
    if any(_opts(d) for d in near):
        n = _facet_normal(a, b, c)
        near = [d for d in near if _applies(d, n)]
    return near


def triangle_trees(points, faces, owner, paint, kind):
    """{facet: tree} of the painted facets of a mesh for one kind (face paint and brush dabs)."""
    base = paint.get(kind) or {}
    dabs = list((paint.get("dabs") or {}).get(kind) or [])
    out = {}
    for k, (i, j, m) in enumerate(faces):
        fv = base.get(owner.get(k)) if base else None
        a, b, c = points[i], points[j], points[m]
        a, b, c = (a.x, a.y, a.z), (b.x, b.y, b.z), (c.x, c.y, c.z)
        near = near_dabs(dabs, a, b, c) if dabs else []
        if not near:
            if fv is not None:
                out[k] = state(kind, fv)
            continue
        t = tree(a, b, c, fv, near, kind)
        if t != 0:
            out[k] = t
    return out


def can_paint(item):
    """Painting goes on the CAD faces: a FreeCAD part or a STEP file (not a mesh)."""
    return getattr(item, "_shape", None) is not None and bool(getattr(item._shape, "Faces", None))


def code(kind, value):
    """The slicers' triangle paint code (TriangleSelector, one whole triangle): state 1 = "4", 2 = "8",
    3 and up = "C" with the state - 3 in the next hex digit (written first)."""
    if kind in ("support", "seam", "fuzzy"):
        state = 1 if value == "enforce" else 2
    else:
        state = int(value)
    if state < 3:
        return "%X" % (state << 2)
    return "%XC" % (state - 3)


def segments(shape, linear=0.05, angular=0.5):
    """(mesh, [facet indices per CAD face]) of a shape, one mesh segment per face, the points shared (welded)."""
    import MeshPart
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=linear, AngularDeflection=angular, Relative=False,
                                  Segments=True)
    segs = [list(mesh.getSegment(i)) for i in range(mesh.countSegments())]
    return mesh, segs


def face_solids(shape):
    """{CAD face index: solid index} of a shape made of several solids (Split to parts)."""
    solid_of = {}
    for k, solid in enumerate(shape.Solids):
        for f in solid.Faces:
            solid_of.setdefault(f.hashCode(), k)
    return {i: solid_of.get(f.hashCode(), 0) for i, f in enumerate(shape.Faces)}


SUBTYPES = {"part": "normal_part", "modifier": "modifier_part", "negative": "negative_part"}
MODIFIER_COLOUR = (0.62, 0.62, 0.66)                  # modifier parts: grey, as the slicers show them


def part_slots(item):
    """{solid index: filament} of the parts that print with a filament of their own (Split to parts)."""
    return {k: int(p.get("slot") or 0) for k, p in enumerate(getattr(item, "parts", None) or []) if p.get("slot")}


def display_segments(item):
    """The segments the plate shows and picks on (cached on the item; the display deflection)."""
    cached = getattr(item, "_paint_segments", None)
    if cached is not None and cached[0] is item._shape:
        return cached[1], cached[2]
    mesh, segs = segments(item._shape)
    owner = {}
    for face, facets in enumerate(segs):
        for f in facets:
            owner[f] = face
    item._paint_segments = (item._shape, mesh, segs)
    item._paint_owner = owner
    return mesh, segs


# ---------------------------------------------------------------------- the 3MF the slicer gets
def write_plate(objects, path, linear=0.003, angular=0.5, extra=None, plates=None):
    """The plate's objects as one 3MF with their paint, filament, own settings and height ranges.
    objects: [{"name", "shape" (model coordinates, or a mesh), "matrix" (16 numbers, model -> plate), "paint",
    "slot", "params", "ranges", "parts" (Split to parts: [{"name", "slot"}] per solid)}]. plates: the plate (0-based) of each object, for a 3MF of several plates (the
    matrices then place each object on its plate, laid out as the slicers lay plates out). Returns (path, facets)."""
    resources, build = [], []
    config = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    ranges_xml = ['<?xml version="1.0" encoding="utf-8"?>', "<objects>"]
    profiles = []
    facets_total = 0
    ears_by_object = []
    next_id = len(objects) + 1                       # ids of the parts' own meshes (Split to parts)
    for i, o in enumerate(objects, 1):
        matrix = o["matrix"] if isinstance(o["matrix"], App.Matrix) else App.Matrix(*o["matrix"])
        shape = o["shape"]
        if hasattr(shape, "Facets"):
            mesh, segs = shape.copy(), [list(range(shape.CountFacets))]
        else:
            mesh, segs = segments(shape, linear, angular)
        paint = o.get("paint") or {}
        tag = {}
        if has_paint(paint):
            points, faces = mesh.Topology
            owner = {f: face for face, facets in enumerate(segs) for f in facets}
            for kind in KINDS:
                faces_paint = {int(k): v for k, v in (paint.get(kind) or {}).items()}
                part = dict(paint, **{kind: faces_paint})
                for f, t in triangle_trees(points, faces, owner, part, kind).items():
                    text = tree_code(t)
                    if text:
                        tag.setdefault(f, []).append('%s="%s"' % (ATTRS[kind], text))
        mesh.transform(matrix)
        if paint.get("ears"):
            # brim ears: the slicer reads them in the object's own coordinates, which it centres on the object's box
            # when it loads the 3MF; so they go relative to that centre, and land on the bed under the object
            from . import slicerears
            c = mesh.BoundBox.Center
            ears_by_object.append((i, [(x - c.x, y - c.y, z - c.z, r) for x, y, z, r in
                                       slicerears.placed(paint["ears"], matrix)]))
        points, faces = mesh.Topology
        facets_total += len(faces)
        parts = o.get("parts") or []
        part_ids = []
        if parts and not hasattr(shape, "Facets") and len(shape.Solids) > 1:
            # Split to parts: one object of several parts (the slicers' volumes), each with its own mesh
            solid = face_solids(shape)
            owner_all = {f: face for face, facets in enumerate(segs) for f in facets}
            by_part = {}
            for k in range(len(faces)):
                by_part.setdefault(solid.get(owner_all.get(k), 0), []).append(k)
            comps = []
            for sk in sorted(by_part):
                used = sorted({v for f in by_part[sk] for v in faces[f]})
                remap = {v: n for n, v in enumerate(used)}
                verts = "".join('<vertex x="%.6g" y="%.6g" z="%.6g"/>' % (points[v].x, points[v].y, points[v].z)
                                for v in used)
                tris = "".join('<triangle v1="%d" v2="%d" v3="%d"%s/>' % (
                    remap[faces[k][0]], remap[faces[k][1]], remap[faces[k][2]],
                    (" " + " ".join(tag[k])) if k in tag else "") for k in by_part[sk])
                resources.append('<object id="%d" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles>'
                                 '</mesh></object>' % (next_id, verts, tris))
                comps.append('<component objectid="%d"/>' % next_id)
                part_ids.append((next_id, sk))
                next_id += 1
            resources.append('<object id="%d" type="model"><components>%s</components></object>' % (i, "".join(comps)))
        else:
            verts = "".join('<vertex x="%.6g" y="%.6g" z="%.6g"/>' % (p.x, p.y, p.z) for p in points)
            tris = "".join('<triangle v1="%d" v2="%d" v3="%d"%s/>' % (a, b, c, (" " + " ".join(tag[k])) if k in tag else "")
                           for k, (a, b, c) in enumerate(faces))
            resources.append('<object id="%d" type="model"><mesh><vertices>%s</vertices><triangles>%s</triangles>'
                             '</mesh></object>' % (i, verts, tris))
        build.append('<item objectid="%d" printable="1"/>' % i)
        name = quoteattr(str(o.get("name") or "Object %d" % i))
        config.append(' <object id="%d">' % i)
        config.append('  <metadata key="name" value=%s/>' % name)
        config.append('  <metadata key="extruder" value="%d"/>' % int(o.get("slot") or 1))
        for k, v in sorted((o.get("params") or {}).items()):
            config.append('  <metadata key=%s value=%s/>' % (quoteattr(str(k)), quoteattr(str(v))))
        if part_ids:
            for pid, sk in part_ids:
                part = parts[sk] if sk < len(parts) else {}
                slot = int(part.get("slot") or 0)
                own = "".join('<metadata key=%s value=%s/>' % (quoteattr(str(k)), quoteattr(str(v)))
                              for k, v in sorted((part.get("settings") or {}).items()))
                config.append('  <part id="%d" subtype="%s"><metadata key="name" value=%s/>%s%s</part>' % (
                    pid, SUBTYPES.get(part.get("type") or "part", "normal_part"),
                    quoteattr(str(part.get("name") or "Part %d" % (sk + 1))),
                    ('<metadata key="extruder" value="%d"/>' % slot) if slot else "", own))
        else:
            config.append('  <part id="1" subtype="normal_part"><metadata key="name" value=%s/></part>' % name)
        config.append(" </object>")
        profiles.append(o.get("profile"))
        if o.get("ranges"):
            ranges_xml.append(' <object id="%d">' % i)
            for r in o["ranges"]:
                opts = "".join('<option opt_key=%s>%s</option>' % (quoteattr(str(k)), escape(str(v)))
                               for k, v in (r.get("params") or {}).items())
                ranges_xml.append('  <range min_z="%g" max_z="%g">%s</range>' % (float(r["min_z"]), float(r["max_z"]), opts))
            ranges_xml.append(" </object>")
    if plates:
        for number in range(max(plates) + 1):
            config.append(" <plate>")
            config.append('  <metadata key="plater_id" value="%d"/>' % (number + 1))
            config.append('  <metadata key="plater_name" value=""/>')
            config.append('  <metadata key="locked" value="false"/>')
            for i, p in enumerate(plates, 1):
                if p == number:
                    config.append("  <model_instance>")
                    config.append('   <metadata key="object_id" value="%d"/>' % i)
                    config.append('   <metadata key="instance_id" value="0"/>')
                    config.append('   <metadata key="identify_id" value="%d"/>' % i)
                    config.append("  </model_instance>")
            config.append(" </plate>")
    config.append("</config>")
    ranges_xml.append("</objects>")
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>%s</resources>'
             '<build>%s</build></model>' % ("".join(resources), "".join(build)))
    types = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-'
             '3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.'
            'com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", "\n".join(config))
        if len(ranges_xml) > 3:
            z.writestr("Metadata/layer_config_ranges.xml", "\n".join(ranges_xml))
        for name, text in (extra or {}).items():
            z.writestr(name, text)
        if ears_by_object:
            from . import slicerears
            z.writestr("Metadata/brim_ear_points.txt", slicerears.file_text(ears_by_object))
        if any(profiles):
            # variable layer height (the slicers' own file and format)
            from . import slicerlayers
            z.writestr("Metadata/layer_heights_profile.txt", slicerlayers.profile_text(profiles))
    return path, facets_total


# ---------------------------------------------------------------------- the paint on the plate
def decorate(item, colours=None):
    """Draw the item's paint over it (under its transform), as the slicers show painted areas."""
    from pivy import coin
    if item.switch is None or not can_paint(item):
        return
    if HIGHLIGHT.get("angle") is not None:
        _highlight(item, HIGHLIGHT["angle"])
    paint = paint_of(item)
    own = part_slots(item)
    mods = {k for k, p in enumerate(getattr(item, "parts", None) or []) if p.get("type") == "modifier"}
    if mods:
        own = dict(own, **{k: own.get(k, 0) for k in mods})
    if not has_paint(paint) and not own:
        return
    mesh, segs = display_segments(item)
    points, faces = mesh.Topology
    groups = {}
    part_groups = {}                                   # parts with a filament of their own, under the paint
    if own:
        solid = face_solids(item._shape)
        for f, face in item._paint_owner.items():
            k = solid.get(face)
            if k in mods:
                part_groups.setdefault(MODIFIER_COLOUR, []).append(f)
                continue
            slot = own.get(k)
            if slot:
                part_groups.setdefault(tuple((colours or {}).get(slot) or (0.8, 0.8, 0.8)), []).append(f)

    def colour(kind, st):
        if kind == "color":
            return tuple((colours or {}).get(int(st)) or (0.8, 0.8, 0.8))
        if kind == "seam":
            return SEAM_COLOUR if st == 1 else BLOCK_COLOUR
        if kind == "fuzzy":
            return FUZZY_COLOUR
        return ENFORCE_COLOUR if st == 1 else BLOCK_COLOUR
    tris = []                                          # brush pieces: (a, b, c, colour)
    for kind in KINDS:
        for f, t in triangle_trees(points, faces, item._paint_owner, paint, kind).items():
            if isinstance(t, int):
                groups.setdefault(colour(kind, t), []).append(f)
            else:
                i, j, m = faces[f]
                a, b, c = points[i], points[j], points[m]
                for p, q, r, st in leaves((a.x, a.y, a.z), (b.x, b.y, b.z), (c.x, c.y, c.z), t, []):
                    tris.append((p, q, r, colour(kind, st)))
    sep = coin.SoSeparator()
    sep.setName("SWStyle_SlicerPaint")
    offset = coin.SoPolygonOffset()
    offset.factor = -1.0
    offset.units = -1.0
    sep.addChild(offset)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
    sep.addChild(coords)
    if part_groups:
        under = coin.SoSeparator()
        under.setName("SWStyle_SlicerParts")
        off = coin.SoPolygonOffset()
        off.factor = -0.5
        off.units = -0.5
        under.addChild(off)
        for colour, facets in part_groups.items():
            mat = coin.SoMaterial()
            mat.diffuseColor = colour
            under.addChild(mat)
            fs = coin.SoIndexedFaceSet()
            idx = []
            for f in facets:
                a, b, c = faces[f]
                idx += [a, b, c, -1]
            fs.coordIndex.setValues(0, len(idx), idx)
            under.addChild(fs)
        sep.addChild(under)
    for colour, facets in groups.items():
        mat = coin.SoMaterial()
        mat.diffuseColor = colour
        sep.addChild(mat)
        fs = coin.SoIndexedFaceSet()
        idx = []
        for f in facets:
            a, b, c = faces[f]
            idx += [a, b, c, -1]
        fs.coordIndex.setValues(0, len(idx), idx)
        sep.addChild(fs)
    if tris:
        by = {}
        for p, q, r, c in tris:
            by.setdefault(c, []).extend((p, q, r))
        for c, pts in by.items():
            sub = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor = c
            sub.addChild(mat)
            co = coin.SoCoordinate3()
            co.point.setValues(0, len(pts), pts)
            sub.addChild(co)
            fs = coin.SoFaceSet()
            fs.numVertices.setValues(0, len(pts) // 3, [3] * (len(pts) // 3))
            sub.addChild(fs)
            sep.addChild(sub)
    item.switch.addChild(sep)


def undecorate(item):
    if item.switch is None:
        return
    for i in reversed(range(item.switch.getNumChildren())):
        n = item.switch.getChild(i)
        if n.getName().getString() in ("SWStyle_SlicerPaint", "SWStyle_SlicerOverhang"):
            item.switch.removeChild(i)


HIGHLIGHT = {"angle": None}     # Highlight overhang areas (support painting): the threshold angle, None = off
OVERHANG_COLOUR = (0.25, 0.55, 0.95)


def model_up(item, bed=None):
    """The plate's up (+Z) in the item's own coordinates (its rotation on the plate turned back)."""
    try:
        m = bed.world_matrix(item) if bed is not None else item.transform_matrix()
        inv = m.inverse()
        o, u = inv.multVec(App.Vector(0, 0, 0)), inv.multVec(App.Vector(0, 0, 1))
        d = u - o
        return (d.x / d.Length, d.y / d.Length, d.z / d.Length) if d.Length > 1e-12 else (0.0, 0.0, 1.0)
    except Exception:
        return getattr(item, "_up", None) or (0.0, 0.0, 1.0)


def _highlight(item, angle):
    """The overhangs of the object at the angle, tinted (as the slicers' Highlight overhang areas)."""
    from pivy import coin
    mesh, _segs = display_segments(item)
    points, faces = mesh.Topology
    up = getattr(item, "_up", None) or (0.0, 0.0, 1.0)
    idx = []
    for i, j, m in faces:
        a, b, c = points[i], points[j], points[m]
        if overhanging(_facet_normal((a.x, a.y, a.z), (b.x, b.y, b.z), (c.x, c.y, c.z)), angle, up):
            idx += [i, j, m, -1]
    if not idx:
        return
    sep = coin.SoSeparator()
    sep.setName("SWStyle_SlicerOverhang")
    off = coin.SoPolygonOffset()
    off.factor = -0.7
    off.units = -0.7
    sep.addChild(off)
    mat = coin.SoMaterial()
    mat.diffuseColor = OVERHANG_COLOUR
    mat.emissiveColor = (0.05, 0.12, 0.25)
    sep.addChild(mat)
    co = coin.SoCoordinate3()
    co.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
    sep.addChild(co)
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(idx), idx)
    sep.addChild(fs)
    item.switch.addChild(sep)


def gap_faces(item, kind, value, max_area):
    """Gap fill: the unpainted faces no bigger than max_area (mm²) whose every neighbour is painted value (face
    paint, or brush dabs over the neighbour's middle): the gaps a brush left between painted areas."""
    shape = item._shape
    p = paint_of(item)
    faces = p[kind]
    dabs = [d for d in p["dabs"][kind]]

    def painted(k):
        v = faces.get(k)
        try:
            c = shape.Faces[k].CenterOfMass
        except Exception:
            return v
        for d in dabs:
            if _inside(d, (c.x, c.y, c.z)):
                v = d[4]
        return v
    edges = {}
    for k, f in enumerate(shape.Faces):
        for e in f.Edges:
            edges.setdefault(e.hashCode(), set()).add(k)
    out = []
    for k, f in enumerate(shape.Faces):
        if f.Area > max_area or painted(k) is not None:
            continue
        near = set()
        for e in f.Edges:
            near |= edges.get(e.hashCode(), set())
        near.discard(k)
        if near and all(painted(n) == value for n in near):
            out.append(k)
    return out


def face_under(bed, pos):
    """(item, CAD face index) under a screen position, or None."""
    hit = hit_under(bed, pos)
    return None if hit is None else hit[:2]


def hit_under(bed, pos):
    """(item, CAD face index, point in model coordinates) under a screen position, or None."""
    hit = bed._pick(pos)
    if hit is None:
        return None
    item = bed.items[hit[0]]
    if not can_paint(item):
        return item, None, None
    mesh, _segs = display_segments(item)
    inv = bed.world_matrix(item).inverse()
    ray = bed.ray(pos)
    point = inv.multVec(hit[2])
    if ray is not None:
        p, d = ray
        a, b = inv.multVec(p), inv.multVec(p + d)
        hits = mesh.nearestFacetOnRay((a.x, a.y, a.z), (b.x - a.x, b.y - a.y, b.z - a.z))
        cut = getattr(bed, "section", None)
        if hits and cut is not None:
            # Section view: what is cut away is not there to paint
            m = bed.world_matrix(item)
            hits = {k: v for k, v in hits.items() if (m.multVec(App.Vector(*v)) - cut[1]).dot(cut[0]) >= 0}
        if hits:
            # the hit nearest the eye
            f = min(hits, key=lambda k: (App.Vector(*hits[k]) - a).Length)
            return item, item._paint_owner.get(int(f)), App.Vector(*hits[f])
    # no ray: the face nearest the picked point
    import Part
    v = Part.Vertex(point)
    best = min(range(len(item._shape.Faces)), key=lambda i: item._shape.Faces[i].distToShape(v)[0])
    return item, best, point


class Painter:
    """A paint tool on the plate: a click or a drag paints faces (the toolbar's tool panel sets what)."""

    def __init__(self, toolbar, kind):
        self.toolbar, self.kind = toolbar, kind
        self.bed = toolbar.bed
        self.value = "enforce" if kind != "color" else 2
        self.tool = "circle"          # the slicers' Tool type: "circle" (a round brush), "fill" (a whole face) or
                                      # "smart" (Smart fill: the smooth region around the face)
        self.smart_angle = 30.0       # Smart fill: how sharp an edge stops it (degrees)
        self.radius = 2.0             # the brush's radius (mm)
        self.overhang_only = None     # support painting's On overhangs only: the threshold angle, or None
        self.gap_area = 10.0          # Gap fill: the biggest gap filled (mm²)
        self.clip = None              # Section view: the clip plane node
        self.section = 1.0            # 1 = whole object, less cuts it away from the eye's side
        self.down = False
        self.callbacks = None
        self.last = None
        self.start()

    def start(self):
        from pivy import coin
        bed = self.bed
        if bed.view is None:
            return
        bed.stop_pick()
        bed.picking = self            # the plate's own clicks (select, drag) stand aside while painting

        def button(cb):
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                return
            if ev.getState() == coin.SoButtonEvent.DOWN:
                if self.paint_at(ev.getPosition()):
                    self.down = True
                    cb.setHandled()
            else:
                if self.down:
                    cb.setHandled()
                self.down = False
                self.last = None

        def motion(cb):
            if self.down:
                self.paint_at(cb.getEvent().getPosition())
                cb.setHandled()

        self.callbacks = (bed.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), button),
                          bed.view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), motion))

    def stop(self):
        from pivy import coin
        bed = self.bed
        self._remove_clip()
        if HIGHLIGHT.get("angle") is not None:
            HIGHLIGHT["angle"] = None
            for it in bed.items:
                refresh(bed, it, self.toolbar.panel)
        if self.callbacks is not None and bed.view is not None:
            try:
                bed.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callbacks[0])
                bed.view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.callbacks[1])
            except Exception as error:
                App.Console.PrintLog("slicer paint: %s\n" % error)
        self.callbacks = None
        if bed.picking is self:
            bed.picking = None

    def paint_at(self, pos):
        found = hit_under(self.bed, pos)
        if found is None:
            return False
        item, face, point = found
        if face is None:
            self.toolbar.panel._say("Painting goes on the faces of a FreeCAD part or a STEP file, not on a mesh.")
            return True
        if self.tool in ("circle", "sphere") and point is not None:
            # a drag lays dabs a third of the brush apart (closer ones add nothing)
            if self.last is not None and self.last[0] is item and len(self.last) > 2 and \
                    (point - self.last[2]).Length < self.radius / 3.0:
                return True
            self.last = (item, face, point)
            opts = {}
            if self.tool == "circle":
                # a cylinder along the view, front faces only (the Circle cursor); Sphere is a ball, both sides
                ray = self.bed.ray(pos)
                if ray is not None:
                    inv = self.bed.world_matrix(item).inverse()
                    o, e = inv.multVec(App.Vector(0, 0, 0)), inv.multVec(ray[1])
                    d = e - o
                    if d.Length > 1e-12:
                        d.normalize()
                        opts["dir"] = (d.x, d.y, d.z)
            if self.overhang_only is not None:
                opts["overhang"] = float(self.overhang_only)
                opts["up"] = model_up(item, self.bed)
            return self.dab(item, point, self.value, opts=opts)
        if self.tool == "gap":
            filled = gap_faces(item, self.kind, self.value, self.gap_area) if self.value is not None else []
            for f in filled:
                paint_of(item)[self.kind][f] = self.value
            refresh(self.bed, item, self.toolbar.panel)
            self.toolbar.panel._stale()
            self.toolbar.panel._say("Gap fill: %d gap%s filled." % (len(filled), "" if len(filled) == 1 else "s"))
            self.last = None
            return True
        if (item, face) == self.last:
            return True
        self.last = (item, face)
        if self.tool == "smart":
            for f in smart_faces(item._shape, face, self.smart_angle):
                if self._face_ok(item, f):
                    self.paint(item, f, self.value)
            return True
        if not self._face_ok(item, face):
            return True
        return self.paint(item, face, self.value)

    def _face_ok(self, item, k):
        """On overhangs only: a face is painted when it overhangs (at its middle)."""
        if self.overhang_only is None or self.value is None:
            return True
        try:
            f = item._shape.Faces[k]
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            if f.Orientation == "Reversed":
                n = -n
        except Exception:
            return True
        return overhanging((n.x, n.y, n.z), self.overhang_only, model_up(item, self.bed))

    # ------------------------------------------------------------------ highlight and section view
    def highlight(self, angle):
        """Highlight overhang areas at the angle (None: off): every object on the plate redrawn with it."""
        HIGHLIGHT["angle"] = angle
        for it in self.bed.items:
            it._up = model_up(it, self.bed)
            refresh(self.bed, it, self.toolbar.panel)

    def set_section(self, t):
        """Section view: 1 shows the whole objects; less cuts them away from the eye's side, a plane across the
        view, so inner faces can be painted (the slicers' Section view slider)."""
        from pivy import coin
        self.section = max(0.0, min(1.0, float(t)))
        root, sw = self.bed.root, self.bed.part_switch
        if root is None or sw is None:
            return
        if self.section >= 1.0:
            self._remove_clip()
            return
        if self.clip is None or root.findChild(self.clip) < 0:
            self.clip = coin.SoClipPlane()
            self.clip.setName("SWStyle_SlicerSection")
            root.insertChild(self.clip, max(0, root.findChild(sw)))
        box = App.BoundBox()
        for it in self.bed.items:
            if it.plate == self.bed.current:
                box.add(self.bed.placed_mesh(items=[it]).BoundBox)
        if not box.isValid():
            return
        d = App.Vector(self.bed.view.getViewDirection())
        d.normalize()
        c = box.Center
        half = box.DiagonalLength / 2.0
        # the plane faces away from the eye: what is nearer the eye than it is cut away
        at = c + d * (half - 2.0 * half * self.section)
        self.clip.plane.setValue(coin.SbPlane(coin.SbVec3f(d.x, d.y, d.z), coin.SbVec3f(at.x, at.y, at.z)))
        self.clip.on = True
        self.bed.section = (d, at)        # picks skip what is cut away

    def _remove_clip(self):
        self.bed.section = None
        root = self.bed.root
        if self.clip is not None and root is not None:
            i = root.findChild(self.clip)
            if i >= 0:
                root.removeChild(i)
        self.clip = None

    def dab(self, item, point, value, radius=None, opts=None):
        """One brush dab at a point of the item (model coordinates); value None erases there."""
        d = paint_of(item)["dabs"]
        dab = (point.x, point.y, point.z, float(radius or self.radius), value)
        d[self.kind] = list(d[self.kind]) + [dab + (dict(opts),) if opts else dab]
        self._changed(item)
        return True

    def _changed(self, item):
        self.toolbar.panel._stale()
        if self.toolbar.tool_panel is not None and hasattr(self.toolbar.tool_panel, "note"):
            self.toolbar.tool_panel.note.setText(hint(self.toolbar.panel, self.kind))
        # a drag lays many dabs: the plate redraws once they stop coming
        self._dirty = item
        if not getattr(self, "_queued", False):
            self._queued = True
            QtCore.QTimer.singleShot(30, self._redraw)

    def _redraw(self):
        self._queued = False
        item, self._dirty = getattr(self, "_dirty", None), None
        if item is not None:
            refresh(self.bed, item, self.toolbar.panel)

    def paint(self, item, face, value):
        """value None erases."""
        p = paint_of(item)[self.kind]
        if value is None:
            if p.pop(face, None) is None:
                return True
        else:
            if p.get(face) == value:
                return True
            p[face] = value
        refresh(self.bed, item, self.toolbar.panel)
        self.toolbar.panel._stale()
        if self.toolbar.tool_panel is not None and hasattr(self.toolbar.tool_panel, "note"):
            self.toolbar.tool_panel.note.setText(hint(self.toolbar.panel, self.kind))
        return True


def colours_of(panel):
    """Filament number -> (r, g, b) from the panel's filament slots."""
    out = {}
    try:
        for i, c in enumerate(panel.slots.colours, 1):
            q = QtGui.QColor(c)
            out[i] = (q.redF(), q.greenF(), q.blueF())
    except Exception as error:
        App.Console.PrintLog("slicer paint colours: %s\n" % error)
    return out


def refresh(bed, item, panel=None):
    undecorate(item)
    decorate(item, colours_of(panel) if panel is not None else None)


def clear(bed, kind, items=None, panel=None):
    """Remove one kind of paint from the objects (default: all of them on the plate)."""
    changed = False
    for it in (items if items is not None else bed.items):
        p = paint_of(it)
        if p[kind] or p["dabs"][kind]:
            p[kind] = {}
            p["dabs"][kind] = []
            changed = True
            refresh(bed, it, panel)
    return changed


def counts(bed, kind):
    n = {}
    for it in bed.items:
        for v in paint_of(it)[kind].values():
            n[v] = n.get(v, 0) + 1
    return n


def strokes(bed, kind):
    return sum(1 for it in bed.items for d in paint_of(it)["dabs"][kind] if d[4] is not None)


def hint(panel, kind):
    """What the tool panel says under its buttons (the slicers' notes in the paint gizmos)."""
    n = counts(panel.bed, kind)
    s = strokes(panel.bed, kind)
    if s and not n:
        text = "Painted with the brush (%d dab(s))." % s
        if kind == "support" and any(d[4] == "enforce" for it in panel.bed.items for d in paint_of(it)["dabs"][kind]):
            extra = _hint(panel, kind, {"enforce": 1}).split("\n", 1)
            text += ("\n" + extra[1]) if len(extra) > 1 else ""
        return text
    return _hint(panel, kind, n) + (("\n%d brush dab(s)." % s) if s else "")


def _hint(panel, kind, n):
    if kind == "support":
        text = "%d face(s) enforced, %d blocked." % (n.get("enforce", 0), n.get("block", 0))
        if n.get("enforce"):
            try:
                from . import slicerobject
                on = str(slicerobject.effective_process(panel).get("enable_support", "0")).lower() in ("1", "true")
            except Exception:
                on = True
            if not on:
                text += "\nSupport enforcers print only with supports on (Support > Enable support), as in the slicer."
        return text
    if kind == "seam":
        return "%d face(s) for the seam, %d kept free of it." % (n.get("enforce", 0), n.get("block", 0))
    if kind == "fuzzy":
        return ("%d face(s) with fuzzy skin (its settings: Others > Fuzzy Skin; when that is Disabled, the slice uses "
                "Painted only)." % n.get("enforce", 0))
    return "%d face(s) painted with another filament." % sum(n.values())
