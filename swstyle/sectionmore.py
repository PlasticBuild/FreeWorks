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
from PySide import QtCore, QtGui, QtWidgets

try:
    from pivy import coin
except Exception:
    coin = None


TRANS_GROUP = "Transparently Section Components"


def _header_tick():
    """Transparently Section Components is ticked in its header, as Section by Component is."""
    try:
        from . import pmlayout
        pmlayout.HEADER_CHECKS.setdefault(("Section View", TRANS_GROUP), ("inner", "SWSectionTransOn"))
    except Exception as _fw_err:
        _fw_log("sectionmore.py:header_tick", _fw_err)


_header_tick()


def extra_sections():
    from . import sectionview as sv
    out = []
    for name in ("Top", "Right"):
        s = sv.Settings()
        s.ref, s.ref_name = ("std", name), name + " Plane"
        s.enabled = False
        out.append(s)
    return out


def defaults(settings):
    """The new settings on an older Settings object."""
    for key, value in (("method", "planar"), ("graphics_only", False), ("cosmetic", True),
                       ("zones", []), ("bodies", []), ("include_bodies", False), ("trans_on", False),
                       ("trans_comps", []), ("trans_include", True), ("trans_value", 0.9)):
        if not hasattr(settings, key):
            setattr(settings, key, value if not isinstance(value, list) else list(value))
    if not hasattr(settings, "by_body"):
        settings.by_body = bool(settings.bodies)
    if not hasattr(settings, "extra"):
        settings.extra = extra_sections()


def by_body(settings):
    """The bodies Section by Body works on: none while its header is not ticked."""
    defaults(settings)
    return list(settings.bodies) if settings.by_body else []


def active_frames(settings):
    """(point, removed-side normal, u, v) of Section 1 and each section turned on."""
    from . import sectionview as sv
    defaults(settings)
    out = [sv.frame(settings)[:4]]
    for s in settings.extra:
        if getattr(s, "enabled", False):
            s.offset_selected = settings.offset_selected
            out.append(sv.frame(s)[:4])
    return out


def extra_sheets(section):
    ""

    from . import sectionview as sv
    node = getattr(section, "extra_sheets", None)
    if node is None or coin is None:
        return 0
    node.removeAllChildren()
    half = section._size * 0.42
    n = 0
    for point, normal, u, v in active_frames(section.settings)[1:]:
        centre = section._center - normal * normal.dot(section._center - point)
        corners = [centre + u * a * half + v * b * half for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        sheet = sv._base_color(sv.PLANE_FILL, 0.65)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        sheet.addChild(hints)
        sheet.addChild(pick)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 4, [(c.x, c.y, c.z) for c in corners])
        sheet.addChild(coords)
        quad = coin.SoFaceSet()
        quad.numVertices.setValue(4)
        sheet.addChild(quad)
        node.addChild(sheet)
        lines = sv._base_color(sv.PLANE_LINE)
        lines.addChild(pick)
        dashed = coin.SoDrawStyle()
        dashed.linePattern = 0xFFFF
        dashed.lineWidth = 1.5
        lines.addChild(dashed)
        ring = coin.SoCoordinate3()
        ring.point.setValues(0, 5, [(c.x, c.y, c.z) for c in corners + [corners[0]]])
        lines.addChild(ring)
        outline = coin.SoLineSet()
        outline.numVertices.setValue(5)
        lines.addChild(outline)
        node.addChild(lines)
        n += 1
    return n


def solid_mode(settings):
    defaults(settings)
    return bool(not settings.graphics_only or settings.method == "zonal" or by_body(settings)
            or settings.trans_on or any(getattr(s, "enabled", False) for s in settings.extra))


# --------------------------------------------------------------------------- the cut
def _half(point, normal, u, size):
    """A box filling the normal side of the plane (size big enough to cover the model)."""
    import Part
    n = App.Vector(normal)
    n.normalize()
    a = App.Vector(u) - n * App.Vector(u).dot(n)
    if a.Length < 1e-9:
        a = App.Vector(1, 0, 0) if abs(n.x) < 0.9 else App.Vector(0, 1, 0)
        a = a - n * a.dot(n)
    a.normalize()
    b = n.cross(a)
    box = Part.makeBox(2 * size, 2 * size, size)
    rot = App.Rotation(a, b, n, "ZXY")
    box.Placement = App.Placement(App.Vector(point) - a * size - b * size, rot)
    return box


def zones(settings, size, centre):
    """[(bits, solid)] of the zones the planes make (bit i set = on plane i's removed side)."""
    frames = active_frames(settings)
    import Part
    big = Part.makeBox(2 * size, 2 * size, 2 * size, centre - App.Vector(size, size, size))
    out = []
    for bits in range(1 << len(frames)):
        cell = big
        for i, (p, n, u, v) in enumerate(frames):
            side = n if bits & (1 << i) else n * -1
            cell = cell.common(_half(p, side, u, size * 2))
            if cell.isNull() or cell.Volume < 1e-9:
                break
        else:
            out.append((bits, cell))
    return out


def removed_region(settings, size, centre):
    """The solid taken away: every plane's removed side at once (planar), or the picked zones."""
    frames = active_frames(settings)
    if settings.method == "zonal":
        picked = set(settings.zones or [(1 << len(frames)) - 1])
        cells = [c for bits, c in zones(settings, size, centre) if bits in picked]
        if not cells:
            return None
        region = cells[0]
        for c in cells[1:]:
            region = region.fuse(c)
        return region
    region = None
    for p, n, u, v in frames:
        h = _half(p, n, u, size * 2)
        region = h if region is None else region.common(h)
    return region


def body_cut(settings, obj_name):
    """Whether the body is cut (Selected Bodies)."""
    names = [b[1] for b in by_body(settings)]
    if not names:
        return True
    return (obj_name in names) if settings.include_bodies else (obj_name not in names)


def trans_cut(settings, obj_name):
    """Whether the component's cut-away part stays on screen, see-through (Transparently Section
    Components): the picked ones with Include selected, all the others with Exclude selected."""
    defaults(settings)
    if not settings.trans_on:
        return False
    names = [b[1] for b in settings.trans_comps]
    return (obj_name in names) if settings.trans_include else (obj_name not in names)


def removed_part(shape, region):
    if region is None:
        return None
    try:
        out = shape.common(region)
        return None if out.isNull() or not out.Faces else out
    except Exception:
        return None


def draw_see_through(node, shape, colour, transparency, frames, tol):
    """The cut-away part of a component, see-through, with its faces on a section plane left out
    (the cap of the kept part is there)."""
    from . import sectionview as sv
    faces = [f for f in shape.Faces if not _on_plane(f, frames, tol * 5)]
    points, index = [], []
    for face in faces:
        try:
            pts, tris = face.tessellate(tol)
        except Exception:
            continue
        start = len(points)
        points.extend((q.x, q.y, q.z) for q in pts)
        for a, b, c in tris:
            index.extend((start + a, start + b, start + c, -1))
    if not index:
        return
    part = coin.SoSeparator()
    part.setName("SWSectionSeeThrough")
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    part.addChild(pick)
    look = sv._base_color(colour, transparency)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    look.addChild(hints)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), points)
    look.addChild(coords)
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(index), index)
    look.addChild(fs)
    part.addChild(look)
    node.addChild(part)


def kept(shape, region):
    if region is None:
        return shape
    try:
        out = shape.cut(region)
        return out if not out.isNull() else shape
    except Exception:
        return shape


def zone_at(settings, point):
    """The zone (bits) a point of the model lies in."""
    bits = 0
    for i, (p, n, u, v) in enumerate(active_frames(settings)):
        if (App.Vector(point) - p).dot(n) > 0:
            bits |= 1 << i
    return bits


# --------------------------------------------------------------------------- drawing
def _on_plane(face, frames, tol):
    try:
        if "Plane" not in face.Surface.__class__.__name__:
            return False
        u0, u1, v0, v1 = face.ParameterRange
        c = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        nf = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    except Exception:
        return False
    for p, n, u, v in frames:
        if abs(abs(nf.dot(n)) - 1) < 1e-6 and abs((c - p).dot(n)) < tol:
            return True
    return False


def draw(node, shape, colour, cut_colour, frames, tol):
    """The kept shape as faces (cut faces in cut_colour) with its edges, under node."""
    from . import sectionview as sv
    groups = {}
    for face in shape.Faces:
        key = tuple(cut_colour) if (cut_colour is not None and _on_plane(face, frames, tol * 5)) else tuple(colour)
        groups.setdefault(key, []).append(face)
    for col, faces in groups.items():
        part = sv._base_color(col)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
        part.addChild(hints)
        points, index = [], []
        for face in faces:
            try:
                pts, tris = face.tessellate(tol)
            except Exception:
                continue
            start = len(points)
            points.extend((q.x, q.y, q.z) for q in pts)
            for a, b, c in tris:
                index.extend((start + a, start + b, start + c, -1))
        if not index:
            continue
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), points)
        part.addChild(coords)
        fs = coin.SoIndexedFaceSet()
        fs.coordIndex.setValues(0, len(index), index)
        part.addChild(fs)
        node.addChild(part)
    lines(node, shape.Edges, (0.1, 0.1, 0.1), tol)


def lines(node, edges, colour, tol, width=1.5):
    from . import sectionview as sv
    sep = coin.SoSeparator()
    sep.addChild(sv._material(colour))
    style = coin.SoDrawStyle()
    style.lineWidth = width
    sep.addChild(style)
    for edge in edges:
        try:
            pts = edge.discretize(Deflection=tol)
        except Exception:
            continue
        if len(pts) < 2:
            continue
        lc = coin.SoCoordinate3()
        lc.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        sep.addChild(lc)
        ls = coin.SoLineSet()
        ls.numVertices.setValue(len(pts))
        sep.addChild(ls)
    node.addChild(sep)


def has_threads(doc):
    """Whether the model has a cosmetic thread (Show cosmetic threads is offered only then)."""
    try:
        return doc is not None and any(getattr(o, "ThreadInfo", "") for o in doc.Objects)
    except Exception:
        return False


def thread_edges(doc, frames):
    """Where the section planes cut each shown cosmetic thread's other diameter."""
    import Part
    out = []
    if doc is None:
        return out
    try:
        from . import cosmeticthread as ct
    except ImportError:
        return out
    for obj in doc.Objects:
        info = getattr(obj, "ThreadInfo", "")
        if not info:
            continue
        try:
            if not ct._Overlay._shown(obj):
                continue
            g = json.loads(info)
            centre, direction = App.Vector(*g["centre"]), App.Vector(*g["direction"])
            cyl = Part.makeCylinder(g["other"], g["length"], centre, direction)
            side = [f for f in cyl.Faces if "Cylinder" in f.Surface.__class__.__name__]
        except Exception:
            continue
        for p, n, u, v in frames:
            for f in side:
                try:
                    out.extend(e for w in f.slice(n, n.dot(p)) for e in w.Edges)
                except Exception as _fw_err:
                    _fw_log("sectionmore.py:265", _fw_err)
    return out


def solid_caps(section):
    """Section.update_caps in solid mode: the model drawn cut, the real model clipped away."""
    from . import sectionview as sv
    s = section.settings
    doc = App.ActiveDocument
    frames = active_frames(s)
    size = max(section._size, 1.0)
    tol = max(section._size / 2000.0, 0.01)
    region = removed_region(s, size, section._center)
    gdoc = Gui.getDocument(doc.Name) if doc is not None else None
    cache = getattr(section, "_whole", None)
    if cache is None or cache.get("doc") != (doc.Name if doc is not None else None):
        cache = section._whole = {"doc": doc.Name if doc is not None else None}
    cap_col = s.color if s.keep_cap_color else None
    used = set()
    in_asm = _assembly(doc) is not None
    for name, shape, colour in shown_with_names(doc, gdoc):
        cut = body_cut(s, name)
        side = _side(shape, region, frames) if cut else "kept"
        see = in_asm and side != "kept" and trans_cut(s, name)
        if side == "removed" and not see:
            continue                     # wholly in the cut-away part: nothing to draw
        # each drawing is made in the part's own axes and kept between updates: copies of one part
        # (same geometry, placed elsewhere) share it, and a part no plane passes through is drawn whole
        # once; on a big model only the few parts the planes cross are cut and drawn again
        place = shape.Placement
        inv = place.inverse()
        if side == "kept":
            plan = ("kept",)
        else:
            plan = ("cut", tuple(_local_frame(inv, f) for f in frames), s.method, tuple(sorted(s.zones or ())),
                    bool(s.show_cap), tuple(cap_col or colour), side, round(s.trans_value, 3) if see else None)
        key = (plan, tuple(colour), round(tol, 9))
        same = cache.setdefault(key, [])
        node = next((n for rep, n in same if rep.isPartner(shape)), None)
        if node is None:
            local = shape.copy()
            local.Placement = App.Placement()
            node = coin.SoSeparator()
            if side == "kept":
                draw(node, local, colour, None, frames, tol)
            else:
                lreg = region.copy()
                lreg.Placement = inv.multiply(lreg.Placement)
                lframes = [_local_vectors(inv, f) for f in frames]
                if side != "removed":
                    draw(node, kept(local, lreg), colour, (cap_col or colour) if s.show_cap else None, lframes, tol)
                if see:
                    gone = local if side == "removed" else removed_part(local, lreg)
                    if gone is not None:
                        draw_see_through(node, gone, colour, s.trans_value, lframes, tol)
            same.append((shape, node))
        used.add(key)
        put = coin.SoSeparator()
        xf = coin.SoTransform()
        xf.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
        xf.rotation.setValue(coin.SbRotation(*place.Rotation.Q))
        put.addChild(xf)
        put.addChild(node)
        section.caps.addChild(put)
    for key in [k for k in cache if k != "doc" and k not in used]:
        del cache[key]
    if sum(len(v) for k, v in cache.items() if k != "doc") > 600:
        section._whole = None


def _local_vectors(inv, frame):
    p, n, u, v = frame
    r = inv.Rotation
    return (inv.multVec(p), r.multVec(n), r.multVec(u), r.multVec(v))


def _local_frame(inv, frame):
    p, n, u, v = _local_vectors(inv, frame)
    return tuple(round(x, 7) for x in (n.x, n.y, n.z, n.dot(p)))


def _side(shape, region, frames):
    """'kept' or 'removed' for a shape no section plane passes through, else 'cut'."""
    if region is None:
        return "kept"
    from . import sectionview as sv
    box = shape.BoundBox
    for p, n, u, v in frames:
        if sv.crosses(box, n, n.dot(p), 1e-6):
            return "cut"
    try:
        inside = region.isInside(box.Center, 1e-7, True)
    except Exception:
        return "cut"
    return "removed" if inside else "kept"


def _assembly(doc):
    """The document's top assembly, or None (a part)."""
    if doc is None:
        return None
    try:
        from . import asmcore
        return asmcore.assembly_of(doc)
    except Exception as _fw_err:
        _fw_log("sectionmore.py:asm", _fw_err)
        return None


def _list_icon(assembly):
    if assembly:
        for name in ("Assembly_InsertLink", "Assembly_InsertComponent"):
            try:
                info = Gui.Command.get(name).getInfo() if Gui.Command.get(name) is not None else None
                icon = Gui.getIcon((info or {}).get("pixmap") or "")
                if icon is not None and not icon.isNull():
                    return icon
            except Exception:
                continue
        return QtGui.QIcon(":/icons/Assembly_InsertLink.svg")
    return QtGui.QIcon(":/icons/PartDesign_Body.svg")


def component_of(asm, obj, sub=""):
    """The assembly's top component a pick (object, sub-element path) is in, or None."""
    from . import asmcore
    comps = {c.Name: c for c in asmcore.components(asm)}
    if obj is None:
        return None
    if obj.Name in comps:
        return comps[obj.Name]
    if obj.Name == asm.Name and sub:
        return comps.get(sub.split(".")[0])
    for parent in obj.InListRecursive if hasattr(obj, "InListRecursive") else ():
        if parent.Name in comps:
            return comps[parent.Name]
    return None


def _component_colour(comp, vobj):
    from . import sectionview as sv
    try:
        if getattr(vobj, "OverrideMaterial", False):
            c = vobj.ShapeMaterial.DiffuseColor
            return (c[0], c[1], c[2])
    except Exception as _fw_err:
        _fw_log("sectionmore.py:linkcolour", _fw_err)
    try:
        linked = comp.getLinkedObject(True)
        return sv._object_color(linked.ViewObject)
    except Exception:
        return sv._object_color(vobj)


def components_shown(doc, gdoc):
    """(component name, placed shape, colour) for each shown component of the document's assembly,
    or None in a part."""
    asm = _assembly(doc)
    if asm is None:
        return None
    import Part
    from . import asmcore
    out = []
    try:
        place = asm.getGlobalPlacement()
    except Exception:
        place = App.Placement()
    for comp in asmcore.components(asm):
        try:
            vobj = gdoc.getObject(comp.Name)
            if vobj is None or not vobj.Visibility or not comp.Visibility:
                continue
            shape = Part.getShape(comp, "", needSubElement=False, transform=True)
            if shape.isNull() or not shape.Solids:
                continue
            if not place.isIdentity():
                shape = shape.copy()
                shape.Placement = place.multiply(shape.Placement)
            out.append((comp.Name, shape, _component_colour(comp, vobj)))
        except Exception as _fw_err:
            _fw_log("sectionmore.py:component", _fw_err)
    return out


def shown_with_names(doc, gdoc):
    """sectionview._shown_solids with each object's name (Selected Bodies). In an assembly, each
    component as itself instead of the assembly's one compound."""
    from . import sectionview as sv
    out = []
    if doc is None:
        return out
    comps = components_shown(doc, gdoc) if gdoc is not None else None
    if comps is not None:
        asm = _assembly(doc)
        inside = ({o.Name for o in asm.OutListRecursive if o.Document is doc} | {asm.Name}) if asm is not None else set()
        out = [x for x in _named_solids(doc, gdoc) if x[0] not in inside]
        return out + comps
    return _named_solids(doc, gdoc)


def _named_solids(doc, gdoc):
    from . import sectionview as sv
    out = []
    shapes = sv._shown_solids(doc, components=False, surfaces=True)
    names = []
    for obj in doc.Objects:
        try:
            vobj = gdoc.getObject(obj.Name)
            if vobj is None or not vobj.Visibility or not obj.Visibility:
                continue
        except Exception:
            continue
        if obj.isDerivedFrom("PartDesign::Feature"):
            body = obj.getParentGeoFeatureGroup()
            if body is not None and body.TypeId == "PartDesign::Body" and body.Visibility:
                continue
        if obj.TypeId in ("App::Plane", "App::Line", "App::Point", "PartDesign::Plane", "PartDesign::Line",
                          "PartDesign::Point", "Sketcher::SketchObject"):
            continue
        shape = getattr(obj, "Shape", None)
        try:
            if shape is None or shape.isNull() or not (shape.Solids or sv._surface_body(obj, shape)):
                continue
        except Exception:
            continue
        names.append(obj.Name)
    for name, (shape, colour) in zip(names, shapes):
        out.append((name, shape, colour))
    return out


def clip_all(clip):
    clip.plane.setValue(coin.SbPlane(coin.SbVec3f(0, 0, 1), 1e12))
    clip.on.setValue(True)


# --------------------------------------------------------------------------- the boxes
class ExtraBoxes:
    """Section Method, the two option rows, Section 2 / Section 3 and Selected Bodies, added to the
    SectionPanel."""

    def __init__(self, panel):
        self.panel = panel
        s = panel.settings
        defaults(s)
        self.target = 0                    # where a pick goes: 0 / 1 / 2 (a section's plane) or "bodies"

        self.label_box = QtWidgets.QWidget()
        self.label_box.setWindowTitle("Drawing Section View")
        self.label_box.setObjectName("SWSectionLabelBox")
        llay = QtWidgets.QVBoxLayout(self.label_box)
        self.label_edit = QtWidgets.QLineEdit(str(getattr(s, "label", "A")))
        self.label_edit.setObjectName("SWSectionLabel")
        self.label_edit.setMaxLength(2)
        self.label_edit.setToolTip("Section view label: the letter a drawing's section view gets from this cut")
        self.label_edit.textEdited.connect(lambda t: setattr(s, "label", t.strip().upper() or "A"))
        llay.addWidget(self.label_edit)
        # Section Method
        self.method_box = QtWidgets.QWidget()
        self.method_box.setWindowTitle("Section Method")
        self.method_box.setObjectName("SWSectionMethod")
        lay = QtWidgets.QVBoxLayout(self.method_box)
        self.planar = QtWidgets.QRadioButton("Planar")
        self.zonal = QtWidgets.QRadioButton("Zonal")
        self.planar.setObjectName("SWSectionPlanar")
        self.zonal.setObjectName("SWSectionZonal")
        for radio in (self.planar, self.zonal):
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(8, 0, 0, 0)
            row.addWidget(radio)
            row.addStretch(1)
            lay.addLayout(row)
        self.zone_list = QtWidgets.QListWidget()
        self.zone_list.setObjectName("SWSectionZones")
        self.zone_list.setToolTip("Zones to remove: tick them, or click a zone of the model in the view")
        self.zone_list.setFixedHeight(90)
        lay.addWidget(self.zone_list)
        # Section Options rows
        self.graphics = QtWidgets.QCheckBox("Graphics-only section")
        self.graphics.setObjectName("SWSectionGraphicsOnly")
        self.graphics.setToolTip("Quick display clip. Off: the cut is worked out from the solids.")
        self.cosmetic = QtWidgets.QCheckBox("Show cosmetic threads")
        self.cosmetic.setObjectName("SWSectionCosmetic")
        opts = panel.options.layout()
        opts.addWidget(self.graphics)
        opts.addWidget(self.cosmetic)       # shown only when the model has cosmetic threads (show())
        self.save = QtWidgets.QPushButton("Save...")
        self.save.setObjectName("SWSectionSave")
        self.save.setToolTip("Saves this section as a named view: View Orientation lists it, and going to it "
                             "shows the section again")
        self.save.clicked.connect(lambda checked=False: self.save_named())
        opts.addWidget(self.save)
        # Section 2 / Section 3
        self.sections = []
        for i, sec in enumerate(s.extra, 2):
            self.sections.append(self._section_box(i, sec))

        self.in_assembly = _assembly(App.ActiveDocument) is not None
        group = "Section by Component" if self.in_assembly else "Section by Body"
        self.bodies_box = QtWidgets.QWidget()
        self.bodies_box.setWindowTitle(group)
        self.bodies_box.setObjectName("SWSectionBodies")
        lay = QtWidgets.QVBoxLayout(self.bodies_box)
        self.by_body = QtWidgets.QCheckBox(group)
        self.by_body.setObjectName("SWSectionByBodyOn")        # pmlayout moves it into the header
        lay.addWidget(self.by_body)
        self.exclude = QtWidgets.QRadioButton("Exclude selected")
        self.include = QtWidgets.QRadioButton("Include selected")
        self.body_list = QtWidgets.QListWidget()
        self.body_list.setObjectName("SWSectionBodyList")
        self.body_list.setFixedHeight(60)
        self.body_list.setToolTip("Click here, then click %s in the view (a second click takes one out)"
                                  % ("components" if self.in_assembly else "bodies"))
        self.body_list.setStyleSheet("QListWidget { background: #cce4f7; }")
        self.body_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.body_list.customContextMenuRequested.connect(self._body_menu)
        self.body_list.viewport().installEventFilter(_Focus(self, "bodies"))
        panel.ref_field.installEventFilter(_Focus(self, 0))
        body_row = QtWidgets.QHBoxLayout()
        body_icon = QtWidgets.QLabel()
        body_icon.setFixedSize(22, 22)
        body_icon.setAlignment(QtCore.Qt.AlignTop)
        try:
            body_icon.setPixmap(_list_icon(self.in_assembly).pixmap(18, 18))
        except Exception as _fw_err:
            _fw_log("sectionmore.py:bodyicon", _fw_err)
        body_row.addWidget(body_icon, 0, QtCore.Qt.AlignTop)
        body_row.addWidget(self.body_list, 1)
        lay.addLayout(body_row)
        for radio in (self.exclude, self.include):
            lay.addWidget(radio)
        self.trans_box = self._trans_box() if self.in_assembly else None
        self.show()
        self.by_body.toggled.connect(self._changed)
        for w in (self.planar, self.zonal, self.graphics, self.cosmetic, self.exclude, self.include):
            w.toggled.connect(self._changed)
        self.zone_list.itemChanged.connect(self._zones_changed)
        panel.form = [self.label_box, self.method_box] + list(panel.form) + [b["widget"] for b in self.sections] + [self.bodies_box]
        if self.trans_box is not None:
            panel.form.append(self.trans_box)

    def _trans_box(self):
        ""


        box = QtWidgets.QWidget()
        box.setWindowTitle(TRANS_GROUP)
        box.setObjectName("SWSectionTrans")
        lay = QtWidgets.QVBoxLayout(box)
        self.trans_on = QtWidgets.QCheckBox(TRANS_GROUP)
        self.trans_on.setObjectName("SWSectionTransOn")        # pmlayout moves it into the header
        lay.addWidget(self.trans_on)
        self.trans_list = QtWidgets.QListWidget()
        self.trans_list.setObjectName("SWSectionTransList")
        self.trans_list.setFixedHeight(60)
        self.trans_list.setToolTip("Components or bodies to include or exclude from the transparent sectioning")
        self.trans_list.setStyleSheet("QListWidget { background: #f9d3e6; }")
        self.trans_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.trans_list.customContextMenuRequested.connect(self._trans_menu)
        self.trans_list.viewport().installEventFilter(_Focus(self, "trans"))
        row = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setFixedSize(22, 22)
        icon.setAlignment(QtCore.Qt.AlignTop)
        try:
            icon.setPixmap(_list_icon(True).pixmap(18, 18))
        except Exception as _fw_err:
            _fw_log("sectionmore.py:transicon", _fw_err)
        row.addWidget(icon, 0, QtCore.Qt.AlignTop)
        row.addWidget(self.trans_list, 1)
        lay.addLayout(row)
        self.trans_exclude = QtWidgets.QRadioButton("Exclude selected")
        self.trans_include = QtWidgets.QRadioButton("Include selected")
        group = QtWidgets.QButtonGroup(box)         # its own pair, apart from Section by Component's
        group.addButton(self.trans_exclude)
        group.addButton(self.trans_include)
        lay.addWidget(self.trans_exclude)
        lay.addWidget(self.trans_include)
        value = QtWidgets.QHBoxLayout()
        self.trans_spin = QtWidgets.QDoubleSpinBox()
        self.trans_spin.setObjectName("SWSectionTransValue")
        self.trans_spin.setRange(0.0, 1.0)
        self.trans_spin.setSingleStep(0.1)
        self.trans_spin.setDecimals(2)
        self.trans_spin.setToolTip("Transparency of the cut-away part")
        self.trans_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.trans_slider.setObjectName("SWSectionTransSlider")
        self.trans_slider.setRange(0, 100)
        value.addWidget(self.trans_spin)
        value.addWidget(self.trans_slider, 1)
        lay.addLayout(value)
        self.trans_on.toggled.connect(self._changed)
        self.trans_include.toggled.connect(self._changed)
        self.trans_spin.valueChanged.connect(self._trans_value)
        self.trans_slider.valueChanged.connect(lambda v: self.trans_spin.setValue(v / 100.0))
        return box

    def _trans_value(self, v):
        self.trans_slider.blockSignals(True)
        self.trans_slider.setValue(int(round(v * 100)))
        self.trans_slider.blockSignals(False)
        s = self.panel.settings
        if abs(s.trans_value - v) > 1e-9:
            s.trans_value = v
            if s.trans_on:
                self.panel.controller.changed()

    def _trans_menu(self, pos):
        menu = QtWidgets.QMenu(self.trans_list)
        menu.addAction("Clear Selections", self.clear_trans)
        menu.exec_(self.trans_list.viewport().mapToGlobal(pos))

    def clear_trans(self):
        self.panel.settings.trans_comps = []
        self.show()
        self.panel.controller.changed()

    def pick_trans(self, doc_name, obj, sub=""):
        s = self.panel.settings
        asm = _assembly(App.getDocument(doc_name)) if doc_name in App.listDocuments() else None
        comp = component_of(asm, obj, sub) if asm is not None else None
        if comp is None:
            return
        key = (doc_name, comp.Name)
        s.trans_on = True           # a component picked into the box: the group is on
        if key in [tuple(b) for b in s.trans_comps]:
            s.trans_comps = [b for b in s.trans_comps if tuple(b) != key]
        else:
            s.trans_comps = list(s.trans_comps) + [key]
        self.show()
        self.panel.controller.changed()

    def save_named(self, name=None):
        doc = App.ActiveDocument
        if doc is None:
            return None
        if name is None:
            n = 1
            while "Section View %d" % n in saved(doc):
                n += 1
            name, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Save Section View", "Name:",
                                                      text="Section View %d" % n)
            if not ok or not name.strip():
                return None
        view = self.panel.controller.section.view if self.panel.controller.section is not None else None
        return save_view(doc, self.panel.settings, name.strip(), view)

    def _section_box(self, number, sec):
        from . import sectionview as sv
        w = QtWidgets.QWidget()
        w.setWindowTitle("Section %d" % number)
        w.setObjectName("SWSection%d" % number)
        lay = QtWidgets.QVBoxLayout(w)
        on = QtWidgets.QCheckBox("Section %d" % number)
        on.setObjectName("SWSection%dOn" % number)
        lay.addWidget(on)
        planes = QtWidgets.QHBoxLayout()
        buttons = {}
        for name in ("Front", "Top", "Right"):
            b = QtWidgets.QToolButton()
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setIcon(sv._painted(name))
            b.setIconSize(QtCore.QSize(22, 22))
            b.setToolTip(name)
            b.setObjectName("SWSection%d%s" % (number, name))
            planes.addWidget(b)
            buttons[name] = b
        planes.addStretch(1)
        lay.addLayout(planes)
        row = QtWidgets.QHBoxLayout()
        rev = QtWidgets.QToolButton()
        rev.setCheckable(True)
        rev.setIcon(sv._painted("reverse"))
        rev.setToolTip("Reverse Section Direction")
        ref = QtWidgets.QLineEdit()
        ref.setReadOnly(True)
        ref.setObjectName("SWSection%dReference" % number)
        ref.setStyleSheet("QLineEdit { background: #cce4f7; color: black; border: 1px solid #7eb4ea; }")
        ref.setToolTip("Click here, then click a plane or a flat face")
        ref.installEventFilter(_Focus(self, number - 1))
        row.addWidget(rev)
        row.addWidget(ref, 1)
        lay.addLayout(row)
        spins = {}

        # sections' rows look the same)
        for key, tip, unit, rng in (("offset", "Offset Distance", "mm", 1e7), ("rx", "X Rotation", "°", 360),
                                    ("ry", "Y Rotation", "°", 360)):
            line = QtWidgets.QHBoxLayout()
            line.setSpacing(6)
            picture = QtWidgets.QLabel()
            picture.setFixedSize(22, 22)
            picture.setPixmap(sv._painted(key).pixmap(20, 20))
            picture.setToolTip(tip)
            sp = QtWidgets.QDoubleSpinBox()
            sp.setRange(-rng, rng)
            sp.setDecimals(2)
            sp.setSuffix(unit)
            sp.setToolTip(tip)
            sp.setObjectName("SWSection%d_%s" % (number, key))
            line.addWidget(picture)
            line.addWidget(sp, 1)
            lay.addLayout(line)
            spins[key] = sp
        box = {"widget": w, "on": on, "buttons": buttons, "reverse": rev, "ref": ref, "spins": spins, "sec": sec}
        on.toggled.connect(lambda v, b=box: self._section_changed(b))
        rev.toggled.connect(lambda v, b=box: self._section_changed(b))
        for name, b in buttons.items():
            b.clicked.connect(lambda checked=False, bx=box, n=name: self.pick_standard(bx, n))
        for sp in spins.values():
            sp.valueChanged.connect(lambda v, b=box: self._section_changed(b))
        return box

    # --- show
    def show(self):
        s = self.panel.settings
        widgets = [self.planar, self.zonal, self.graphics, self.cosmetic, self.exclude, self.include, self.by_body]
        for b in self.sections:
            widgets += [b["on"], b["reverse"]] + list(b["spins"].values())
        for w in widgets:
            w.blockSignals(True)
        self.planar.setChecked(s.method != "zonal")
        self.zonal.setChecked(s.method == "zonal")
        self.graphics.setChecked(s.graphics_only)
        self.cosmetic.setChecked(s.cosmetic)
        self.include.setChecked(s.include_bodies)
        self.exclude.setChecked(not s.include_bodies)
        self.by_body.setChecked(bool(s.by_body))
        for w in (self.body_list, self.exclude, self.include):
            w.setEnabled(bool(s.by_body))
        self.cosmetic.setVisible(has_threads(App.ActiveDocument))
        for b in self.sections:
            sec = b["sec"]
            b["on"].setChecked(sec.enabled)
            b["reverse"].setChecked(sec.reverse)
            b["ref"].setText(sec.ref_name)
            for name, btn in b["buttons"].items():
                btn.setChecked(sec.ref == ("std", name))
            for key, sp in b["spins"].items():
                sp.setValue(getattr(sec, key))
            for child in b["widget"].findChildren(QtWidgets.QWidget):
                if child is not b["on"]:
                    child.setEnabled(sec.enabled)
        for w in widgets:
            w.blockSignals(False)
        self._sync_header(bool(s.by_body))
        if self.trans_box is not None:
            tw = [self.trans_on, self.trans_include, self.trans_exclude, self.trans_spin, self.trans_slider]
            for w in tw:
                w.blockSignals(True)
            self.trans_on.setChecked(bool(s.trans_on))
            self.trans_include.setChecked(bool(s.trans_include))
            self.trans_exclude.setChecked(not s.trans_include)
            self.trans_spin.setValue(s.trans_value)
            self.trans_slider.setValue(int(round(s.trans_value * 100)))
            for w in (self.trans_list, self.trans_include, self.trans_exclude, self.trans_spin, self.trans_slider):
                w.setEnabled(bool(s.trans_on))
            for w in tw:
                w.blockSignals(False)
            self._sync_header(bool(s.trans_on), self.trans_box)
            self.trans_list.clear()
            for doc_name, name in s.trans_comps:
                try:
                    self.trans_list.addItem(App.getDocument(doc_name).getObject(name).Label)
                except Exception:
                    self.trans_list.addItem(name)
        self.body_list.clear()
        for doc_name, name in s.bodies:
            try:
                self.body_list.addItem(App.getDocument(doc_name).getObject(name).Label)
            except Exception:
                self.body_list.addItem(name)
        self._fill_zones()

    def _fill_zones(self):
        s = self.panel.settings
        self.zone_list.setVisible(s.method == "zonal")
        self.zone_list.blockSignals(True)
        self.zone_list.clear()
        if s.method == "zonal":
            n = len(active_frames(s))
            picked = set(s.zones or [(1 << n) - 1])
            for bits in range(1 << n):
                sides = ", ".join(("cut side of %d" if bits & (1 << i) else "kept side of %d") % (i + 1) for i in range(n))
                item = QtWidgets.QListWidgetItem("Zone %d (%s)" % (bits + 1, sides))
                item.setData(QtCore.Qt.UserRole, bits)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if bits in picked else QtCore.Qt.Unchecked)
                self.zone_list.addItem(item)
        self.zone_list.blockSignals(False)

    # --- changes
    def _changed(self, *args):
        s = self.panel.settings
        s.method = "zonal" if self.zonal.isChecked() else "planar"
        s.graphics_only = self.graphics.isChecked()
        s.cosmetic = self.cosmetic.isChecked()
        s.include_bodies = self.include.isChecked()
        s.by_body = self.by_body.isChecked()
        if self.trans_box is not None:
            s.trans_on = self.trans_on.isChecked()
            s.trans_include = self.trans_include.isChecked()
        self.show()
        self.panel.controller.changed()

    def _zones_changed(self, item):
        s = self.panel.settings
        s.zones = [self.zone_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.zone_list.count())
                   if self.zone_list.item(i).checkState() == QtCore.Qt.Checked]
        self.panel.controller.changed()

    def toggle_zone(self, bits):
        s = self.panel.settings
        n = len(active_frames(s))
        zones_now = set(s.zones or [(1 << n) - 1])
        zones_now ^= {bits}
        s.zones = sorted(zones_now)
        self._fill_zones()
        self.panel.controller.changed()

    def _section_changed(self, box):
        sec = box["sec"]
        sec.enabled = box["on"].isChecked()
        sec.reverse = box["reverse"].isChecked()
        for key, sp in box["spins"].items():
            setattr(sec, key, sp.value())
        self.panel.settings.zones = []
        self.show()
        self.panel.controller.changed()

    def pick_standard(self, box, name):
        sec = box["sec"]
        sec.ref, sec.ref_name, sec.ref_place = ("std", name), name + " Plane", None
        sec.offset = sec.rx = sec.ry = 0.0
        sec.enabled = True
        self.show()
        self.panel.controller.changed()

    def pick_reference(self, index, ref, name, place):
        box = self.sections[index - 1]
        sec = box["sec"]
        sec.ref, sec.ref_name, sec.ref_place = ref, name, place
        sec.offset = sec.rx = sec.ry = 0.0
        sec.enabled = True
        self.show()
        self.panel.controller.changed()

    def _sync_header(self, on, box=None):
        """The group's header tick (pmlayout) follows a pick that turned the box on (the inner tick was
        set with its signals blocked, so the header did not hear it)."""
        box = box or self.bodies_box
        try:
            name = "SWStyle_HeaderCheck_" + box.windowTitle().replace(" ", "")
            top = box.window()
            for cb in top.findChildren(QtWidgets.QCheckBox, name) if top is not None else ():
                if cb.isChecked() != on:
                    cb.blockSignals(True)
                    cb.setChecked(on)
                    cb.blockSignals(False)
        except Exception as _fw_err:
            _fw_log("sectionmore.py:header", _fw_err)

    def pick_body(self, doc_name, obj, sub=""):
        s = self.panel.settings
        body = obj
        asm = _assembly(App.getDocument(doc_name)) if doc_name in App.listDocuments() else None
        if asm is not None:
            body = component_of(asm, obj, sub)      # Section by Component: the top component picked
            if body is None:
                return
        try:
            parent = obj.getParentGeoFeatureGroup()
            if asm is None and parent is not None and parent.TypeId == "PartDesign::Body":
                body = parent
        except Exception as _fw_err:
            _fw_log("sectionmore.py:597", _fw_err)
        key = [doc_name, body.Name]
        s.by_body = True            # a body picked into the box: Section by Body is on
        if key in [list(b) for b in s.bodies]:
            s.bodies = [b for b in s.bodies if list(b) != key]
        else:
            s.bodies = list(s.bodies) + [tuple(key)]
        self.show()
        self.panel.controller.changed()

    def _body_menu(self, pos):
        menu = QtWidgets.QMenu(self.body_list)
        menu.addAction("Clear Selections", self.clear_bodies)
        menu.exec_(self.body_list.viewport().mapToGlobal(pos))

    def clear_bodies(self):
        self.panel.settings.bodies = []
        self.show()
        self.panel.controller.changed()


class _Focus(QtCore.QObject):
    """A click in a selection box makes it the one picks go to."""

    def __init__(self, boxes, target):
        super().__init__(boxes.body_list if hasattr(boxes, "body_list") else None)
        self.boxes, self.target = boxes, target

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.FocusIn):
            self.boxes.target = self.target
        return False


def picked(controller, doc, obj, sub, pnt=None):
    ""
    panel = controller.panel
    boxes = getattr(panel, "extra_boxes", None)
    if boxes is None:
        return False
    s = panel.settings
    if boxes.target == "bodies":
        boxes.pick_body(doc, obj, sub)
        return True
    if boxes.target == "trans" and getattr(boxes, "trans_box", None) is not None:
        boxes.pick_trans(doc, obj, sub)
        return True
    found = controller._reference(doc, obj, sub)
    if s.method == "zonal" and pnt is not None and not (found and found[0][0] in ("std", "plane")):
        boxes.toggle_zone(zone_at(s, App.Vector(*pnt)))
        return True
    if isinstance(boxes.target, int) and boxes.target > 0 and found is not None:
        ref, name, place = found
        if ref[0] == "std":
            boxes.pick_standard(boxes.sections[boxes.target - 1], ref[1])
        else:
            boxes.pick_reference(boxes.target, ref, name, place)
        return True
    return False


# --------------------------------------------------------------------------- Save (a named view)
SAVED = "SWSectionViews"
_KEYS = ("ref", "ref_name", "offset", "rx", "ry", "reverse", "offset_selected", "show_cap", "keep_cap_color",
         "color", "method", "graphics_only", "cosmetic", "zones", "bodies", "include_bodies", "enabled", "by_body",
         "trans_on", "trans_comps", "trans_include", "trans_value")


def _pack(s):
    out = {k: getattr(s, k) for k in _KEYS if hasattr(s, k)}
    place = getattr(s, "ref_place", None)
    if place is not None:
        out["ref_place"] = [list(place.Base), list(place.Rotation.Q)]
    if hasattr(s, "extra"):
        out["extra"] = [_pack(e) for e in s.extra]
    return out


def _unpack(data, s):
    for k in _KEYS:
        if k in data:
            v = data[k]
            if k in ("ref", "color"):
                v = tuple(v)
            elif k in ("bodies", "trans_comps"):
                v = [tuple(b) for b in v]
            setattr(s, k, v)
    if "bodies" in data and "by_body" not in data:
        s.by_body = bool(data["bodies"])          # saved before Section by Body had its header tick
    rp = data.get("ref_place")
    s.ref_place = App.Placement(App.Vector(*rp[0]), App.Rotation(*rp[1])) if rp else None
    if "extra" in data:
        defaults(s)
        for e, d in zip(s.extra, data["extra"]):
            _unpack(d, e)
    return s


def saved(doc):
    try:
        return json.loads(dict(doc.Meta).get(SAVED, "{}"))
    except Exception:
        return {}


def save_view(doc, settings, name=None, view=None):
    """Save: the section and the camera as a named view (View Orientation lists it; going to it
    turns the section back on)."""
    from . import namedviews
    have = saved(doc)
    if not name:
        n = 1
        while "Section View %d" % n in have or any(v[0] == "Section View %d" % n for v in namedviews.views(doc)):
            n += 1
        name = "Section View %d" % n
    if not namedviews.new_view(name, doc, view):
        return None
    have[name] = _pack(settings)
    meta = dict(doc.Meta)
    meta[SAVED] = json.dumps(have)
    doc.Meta = meta
    return name


def on_named_view(doc, name):
    """namedviews.go went to a view: a saved section view shows its section again."""
    data = saved(doc).get(name)
    if data is None:
        return False
    from . import sectionview as sv
    c = sv.controller()
    if c.panel is not None:
        return False
    _unpack(data, c.settings)
    view = sv._active_3d_view()
    if view is None:
        return False
    c._attach(view, c.settings)
    c.section.set_editing(False)
    c.sync_button()
    return True
