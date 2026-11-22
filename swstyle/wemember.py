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
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, paths
from . import pmboxes

COMMAND = "SWStyle_WEStructuralMember"
WELDMENT_COMMAND = "SWStyle_WEWeldment"
TITLE = "Structural Member"
LABEL = "Structural Member"
PARAMS = paths.PARAM_PATH + "/Weldments"
CORNERS = ("End Miter", "End Butt1", "End Butt2")
BUTT_CUTS = ("Simple cut", "Coped cut")      # how a butting member's end meets the member it ends on


def _coped(group):
    """True when the group's butting ends are coped (fitted to the other member's shape), not cut flat.
    A group saved before the choice existed keeps its flat cut."""
    return group.get("cut", "Simple cut") == "Coped cut"


def _protrude(group):
    """Allow protrusion: at an End Butt corner the through member runs on past the path's end to cover the
    butting member (on, the default); off, it stops at the end of its path segment."""
    return bool(group.get("protrude", True))
NOT_YET = "Not available: FrameForge has no equivalent yet"
MESSAGE = "Select a profile type and size for the Structural Member."
MESSAGE_PATH = "Select sketch segments for defining path. You can rotate the profile by a specified angle."

ISO_TYPES = (("angle iron", ("Equal Leg Angles", "Unequal Leg Angles")),
             ("c channel", ("UPN", "UPE")),
             ("pipe", ("Pipe",)),
             ("rectangular tube", ("Rectangular Hollow",)),
             ("sb beam", ("IPE", "HEA", "HEB", "HEM")),
             ("s section", ("IPN",)),
             ("square tube", ("Square Hollow",)),
             ("flat bar", ("Flat Sections",)),
             ("square bar", ("Square",)),
             ("round bar", ("Round Bar",)))
DEFAULT = ("ansi inch", "square tube", "2 x 2 x 0.25")
GROUP = "Structural Member"
TOL = 1e-6
# FrameForge's table materials as FreeCAD library materials (Transfer material from profile)
PROFILE_MATERIALS = {"Metal": "Steel", "Aluminium extrusion": "Aluminum-Generic", "Aluminium": "Aluminum-Generic",
                     "Wood": "SoftWood", "Aluminium_extrusion": "Aluminum-Generic", "Ansi_inch": "Steel"}
NO_MATERIAL = "Material <not specified>"


def _weicon(name):
    from . import weprofile
    return weprofile.icon(name)



_tables = {}
_legacy = {}      # profiles no longer listed that older members use: {(standard, type): rows}
CUSTOM = "Custom"           # a row's material for a profile from the Weldment Profiles folder (family: its file)
PROFILES_FOLDER = "Weldment Profiles"
# Pierce Point names of the anchors (x: left, centre, right; y: bottom, centre, top)
PIERCE_NAMES = {(1, 1): "Center", (1, 2): "Top Center", (1, 0): "Bottom Center", (0, 2): "Top Left",
                (2, 2): "Top Right", (0, 1): "Center Left", (2, 1): "Center Right", (0, 0): "Bottom Left",
                (2, 0): "Bottom Right"}
PIERCE_PROPERTY = "PiercePoints"


def profiles_folder():
    folder = App.ParamGet(PARAMS).GetString("WeldmentProfiles", "")
    return folder or os.path.join(App.getUserAppDataDir(), "FreeWorks", PROFILES_FOLDER)


def _folder_profiles():
    """{standard: {type: [rows]}} of the Weldment Profiles folder."""
    out = {}
    root = profiles_folder()
    try:
        standards = sorted(os.listdir(root))
    except OSError as _fw_err:
        _fw_log("wemember.py:102", _fw_err)
        return out
    for std in standards:
        sdir = os.path.join(root, std)
        if not os.path.isdir(sdir):
            continue
        for kind in sorted(os.listdir(sdir)):
            kdir = os.path.join(sdir, kind)
            if not os.path.isdir(kdir):
                continue
            rows = [(os.path.splitext(f)[0], CUSTOM, os.path.join(kdir, f), os.path.splitext(f)[0])
                    for f in sorted(os.listdir(kdir)) if f.lower().endswith(".fcstd")]
            if rows:
                out.setdefault(std, {})[kind] = rows
    return out


FAVORITES = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Weldments"


def favorites():
    ""
    try:
        return [tuple(x) for x in json.loads(App.ParamGet(FAVORITES).GetString("ProfileFavorites", "[]"))]
    except Exception:
        return []


def set_favorites(rows):
    App.ParamGet(FAVORITES).SetString("ProfileFavorites", json.dumps([list(r) for r in rows]))


def favorite_name(row):
    return "%s / %s / %s" % row


def favorites_row(panel, form, label=True):
    """Favorites (a list of profiles) with Add Favorite and Remove Favorite, under Standard/Type/Size.
    Picking one sets the three boxes; panel needs standard, kind, size, busy, _fill_types and _changed."""
    combo = QtWidgets.QComboBox()
    combo.setObjectName("SWWEFavorites")
    combo.setToolTip("Favorites: profiles you use often")
    add = QtWidgets.QPushButton("Add Favorite")
    add.setObjectName("SWWEFavoriteAdd")
    add.setToolTip("Adds the Standard, Type and Size above to the favorites")
    remove = QtWidgets.QPushButton("Remove Favorite")
    remove.setObjectName("SWWEFavoriteRemove")
    row = QtWidgets.QHBoxLayout()
    row.addWidget(add)
    row.addWidget(remove)

    def fill(select=None):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("")
        for r in favorites():
            combo.addItem(favorite_name(r), list(r))
        combo.setCurrentIndex(max(0, combo.findText(select)) if select else 0)
        combo.blockSignals(False)
        remove.setVisible(combo.currentIndex() > 0)    # shown once a favorite is picked: never greyed

    def picked(k):
        remove.setVisible(k > 0)
        data = combo.itemData(k)
        if not data:
            return
        std, kind, size = data
        if std not in catalog() or kind not in catalog()[std]:
            return
        panel.busy = True
        try:
            panel.standard.setCurrentText(std)
            panel._fill_types(kind, size)
        finally:
            panel.busy = False
        panel._changed()

    def do_add():
        r = (panel.standard.currentText(), panel.kind.currentText(), panel.size.currentText())
        if not all(r):
            return
        rows = favorites()
        if r not in rows:
            rows.append(r)
            set_favorites(rows)
        fill(favorite_name(r))

    def do_remove():
        data = combo.itemData(combo.currentIndex())
        if data:
            set_favorites([r for r in favorites() if list(r) != list(data)])
        fill()

    combo.currentIndexChanged.connect(picked)
    add.clicked.connect(do_add)
    remove.clicked.connect(do_remove)
    fill()
    if label:
        form.addRow("Favorites:", combo)
    else:
        form.addRow(QtWidgets.QLabel("Favorites:"))
        form.addRow(combo)
    form.addRow(row)
    panel.favorites = combo
    return combo


def catalog():
    """{standard: {type: [(size label, material, family, size)]}} from FrameForge's tables and the Weldment
    Profiles folder."""
    out = {std: dict(kinds) for std, kinds in _frameforge_catalog().items()}
    for std, kinds in _folder_profiles().items():
        out.setdefault(std, {}).update(kinds)
    return out


def _spaced(label):
    ""
    import re
    return re.sub(r"(?<=[\d.])\s*x\s*(?=[\d.])", " x ", label)


def _plain(label):
    """A size label reduced to its numbers and words, so an older label (20x2.0, C3 x 4.1, 12 in sch 40) finds its row."""
    import re
    toks = re.findall(r"\d+(?:\.\d+)?|[a-z]+", str(label).lower())
    return tuple(("%g" % float(t)) if t[0].isdigit() else t for t in toks if t not in ("in", "c", "s", "w"))


def _iso_label(fam, key, dims):
    ""
    try:
        if fam == "Square Hollow":
            return "%g x %g x %g" % (dims["Width"], dims["Height"], dims["Thickness"])
        if fam == "Pipe" and dims.get("Height"):
            wall = dims["Thickness"]
            return "%g x %s" % (dims["Height"], ("%.1f" % wall) if float(wall).is_integer() else ("%g" % wall))
    except Exception as _fw_err:
        _fw_log("wemember.py:iso_label", _fw_err)
    return _spaced(key)


def _ansi_label(kind, key):
    ""
    import re
    if kind in ("c channel", "s section"):
        return re.sub(r"^[A-Za-z]+(?=\d)", "", key)
    if kind == "pipe":
        m = re.match(r"^([\d.]+) in (sch \d+)$", key)
        if m:
            nominal = float(m.group(1))
            return "%s %s" % (("%.1f" % nominal) if nominal.is_integer() else ("%g" % nominal), m.group(2))
    return key


def _frameforge_catalog():
    ""

    if _tables:
        return _tables
    from . import weprofile
    data = weprofile.tables()
    metal = data.pop("metal", {})
    iso = {}
    for sw_type, families in ISO_TYPES:
        families = [fam for fam in families if fam in metal]
        rows = []
        for fam in families:
            for size in metal[fam]["sizes"]:
                label = _iso_label(fam, size, metal[fam]["sizes"][size])      # extapps117
                if len(families) > 1 and sw_type != "angle iron":        # equal and unequal angles never share a size text
                    label = "%s %s" % (fam, label)
                rows.append((label, "Metal", fam, size))
        if rows:
            iso[sw_type] = rows
    _tables["iso"] = iso
    for material, families in data.items():
        std = material.replace("_", " ")
        _tables[std] = {
            fam.lower(): [(_ansi_label(fam.lower(), size) if std == "ansi inch" else size, material.capitalize(), fam, size)
                          for size in spec["sizes"]]
            for fam, spec in families.items()
            if not (std == "ansi inch" and fam.lower() == "sb beam")}
        if std == "ansi inch" and "sb beam" in {f.lower() for f in families}:
            fam = next(f for f in families if f.lower() == "sb beam")      # not listed, but a member made with one still builds
            _legacy[(std, "sb beam")] = [(size, material.capitalize(), fam, size) for size in families[fam]["sizes"]]
    return _tables


_custom = {}


def custom_profile(path):
    """(the profile face in its sketch's own coordinates, {pierce point name: (x, y)}) of a profile part:
    its sketch with predefined pierce points, else its first closed sketch."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        raise ValueError("The profile %s is gone." % path)
    hit = _custom.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1], dict(hit[2])
    active = App.ActiveDocument
    doc = App.openDocument(path, hidden=True)
    try:
        sketches = [o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject"]
        sketches.sort(key=lambda o: PIERCE_PROPERTY not in o.PropertiesList)
        face, points = None, {}
        for sk in sketches:
            wires = [w for w in sk.Shape.Wires if w.isClosed()]
            if not wires:
                continue
            local = sk.getGlobalPlacement().inverse()
            wires = [w.copy() for w in wires]
            for w in wires:
                w.transformShape(local.toMatrix())
            wires.sort(key=lambda w: -w.BoundBox.DiagonalLength)
            face = Part.Face(wires[0])
            for w in wires[1:]:
                face = face.cut(Part.Face(w)) if face.BoundBox.isInside(w.BoundBox) else face.fuse(Part.Face(w))
            if face.ShapeType != "Face":
                face = face.Faces[0] if len(face.Faces) == 1 else Part.Face(wires[0])
            try:
                points = {k: tuple(v) for k, v in json.loads(getattr(sk, PIERCE_PROPERTY, "") or "{}").items()}
            except Exception:
                points = {}
            break
        if face is None:
            raise ValueError("The profile %s has no closed sketch." % os.path.basename(path))
    finally:
        App.closeDocument(doc.Name)
        if active is not None and active.Name in App.listDocuments():
            App.setActiveDocument(active.Name)
    _custom[path] = (stamp, face, points)
    return face, dict(points)


def pierce_point(face, points, anchor):
    """Where the path runs through a custom profile: the predefined point of that name, else the sketch's
    origin for Center, else that spot of the profile's box."""
    ax, ay = anchor
    name = PIERCE_NAMES.get((ax, ay), "Center")
    if name in points:
        return App.Vector(points[name][0], points[name][1], 0)
    if (ax, ay) == (1, 1):
        return App.Vector()
    b = face.BoundBox
    return App.Vector(b.XMin + b.XLength * ax / 2, b.YMin + b.YLength * ay / 2, 0)


def _spec(material, family, size):
    if material == CUSTOM:
        face, _points = custom_profile(family)
        b = face.BoundBox
        return {"Width": b.XLength, "Height": b.YLength}, False
    from . import weprofile
    table = weprofile.tables()[material.lower().replace(" ", "_")][family]
    return table["sizes"][size], table.get("fillet", False)


def find_size(standard, kind, label):
    rows = catalog().get(standard, {}).get(kind, []) or _legacy.get((standard, kind), [])
    for row in rows:
        if row[0] == label:
            return row
    for row in rows:        # extapps117: a member made with an older size text (20x2.0, C3 x 4.1) finds its row
        if row[3] == label or _plain(row[3]) == _plain(label):
            return row
    return None


# ---------------------------------------------------------------- geometry
def _ends(sketch, edge):
    e = sketch.Shape.getElement(edge)
    return e.Vertexes[0].Point, e.Vertexes[-1].Point


def corners(segments, tol=1e-6):
    """Connected pairs (i, j, end_i, end_j, point): end 0 = the segment's start, 1 = its end."""
    out = []
    ends = [_ends(s, e) for s, e in segments]
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            for a in (0, 1):
                for b in (0, 1):
                    if ends[i][a].distanceToPoint(ends[j][b]) < tol:
                        out.append((i, j, a, b, ends[i][a]))
    return out


def _outer_face(shape, point, outward):
    ""


    best, best_d = None, None
    for strict in (True, False):
        for i, f in enumerate(shape.Faces, 1):
            if f.Surface.TypeId != "Part::GeomPlane":
                continue
            c = abs(f.normalAt(0, 0).dot(outward))
            if (abs(c - 1) > 1e-6) if strict else (c < 0.5):
                continue
            d = (f.CenterOfMass - point).dot(outward)
            if best_d is None or d > best_d:
                best, best_d = "Face%d" % i, d
        if best is not None:
            return best
    return best


_GLOBAL = {"App::PropertyLink": "App::PropertyLinkGlobal", "App::PropertyLinkSub": "App::PropertyLinkSubGlobal",
           "App::PropertyLinkList": "App::PropertyLinkListGlobal",
           "App::PropertyLinkSubList": "App::PropertyLinkSubListGlobal"}


def globalize_links(obj):
    ""


    for prop in list(obj.PropertiesList):
        try:
            kind = obj.getTypeIdOfProperty(prop)
            if kind not in _GLOBAL or prop not in obj.PropertiesList:
                continue
            if "Dynamic" not in obj.getPropertyStatus(prop):
                continue                        # a built-in property (AttachmentSupport is global already)
            value = getattr(obj, prop)
            group, doc_ = obj.getGroupOfProperty(prop), obj.getDocumentationOfProperty(prop)
            mode = obj.getEditorMode(prop)
            obj.removeProperty(prop)
            try:
                obj.addProperty(_GLOBAL[kind], prop, group, doc_)
            except Exception:
                obj.addProperty(kind, prop, group, doc_)        # put back as it was
            setattr(obj, prop, value)
            if mode:
                obj.setEditorMode(prop, mode)
        except Exception as error:
            App.Console.PrintLog("FreeCAD member link %s.%s: %s\n" % (obj.Name, prop, error))


def _filled(doc, member, axis):
    """The member's outline solid along axis (a tube with its hollow filled): what a coped end is fitted to, so
    nothing of the coped member is left inside the other's hollow."""
    doc.recompute([member])
    shape = member.Shape
    axis = App.Vector(axis).normalize()
    ends = [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(axis)) - 1) < 1e-6]
    proj = [v.Point.dot(axis) for v in shape.Vertexes]
    out = member
    if ends and proj:
        # the whole end face (a coped end leaves small flat wall pieces across the axis too: in a closed
        # frame of End Butt corners the fill was one wall strip, so a butting member was not cut at all)
        start = max(ends, key=lambda f: (round(f.Area, 6), -f.CenterOfMass.dot(axis)))
        at = start.CenterOfMass.dot(axis)
        length = max(proj) - min(proj)
        try:
            outline = Part.Face(start.OuterWire)
            outline.translate(axis * (min(proj) - at))
            solid = outline.extrude(axis * length)
            out = doc.addObject("Part::Feature", "MemberFill")
            out.Shape = solid
            if App.GuiUp:
                out.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("wemember.py:_filled", _fw_err)
    return out


def _flat_end(doc, member, point, direction, gap=0.0):
    """A flat face across direction where member reaches farthest that way from point (plus gap): the
    flat cut against a member with no flat face across (a pipe, or a round bar)."""
    doc.recompute([member])
    far = 10.0 * (member.Shape.BoundBox.DiagonalLength + (member.Shape.BoundBox.Center - point).Length + 1.0)
    probe = Part.makePlane(4 * far, 4 * far, App.Vector(-2 * far, -2 * far, 0))
    probe.Placement = App.Placement(point + direction * far, App.Rotation(App.Vector(0, 0, 1), direction))
    reach = far - member.Shape.distToShape(probe)[0] + gap      # its farthest point that way, exactly
    face = doc.addObject("Part::Feature", "MemberEnd")
    face.Shape = Part.makePlane(1000, 1000)
    face.Placement = App.Placement(point + direction * reach, App.Rotation(App.Vector(0, 0, 1), direction)) \
        .multiply(App.Placement(App.Vector(-500, -500, 0), App.Rotation()))
    if App.GuiUp:
        face.ViewObject.Visibility = False
    return face


def _profile(doc, sketch, edge, row, group, off_start, off_end):
    from . import weprofile
    _label, material, family, size = row
    Profile, ViewProviderProfile = weprofile.profile_classes(material if material != CUSTOM else "metal")
    dims, fillet = _spec(material, family, size)
    g = lambda k: float(dims.get(k, 0) or 0)
    obj = doc.addObject("Part::FeaturePython", "Member")
    obj.addExtension("Part::AttachExtensionPython")
    obj.MapMode = "NormalToEdge"
    obj.AttachmentSupport = (sketch, edge)
    obj.MapPathParameter = 1
    ax, ay = group.get("anchor", (1, 1))
    mirror = group.get("mirror", "")
    if material == CUSTOM:
        return _custom_member(doc, obj, sketch, edge, row, group, off_start, off_end)
    # FrameForge's OffsetA extends the path's end, OffsetB its start
    Profile(obj, g("Width"), g("Height"), g("Thickness"), g("Flange Thickness"), g("Radius1"), g("Radius2"), 0.0,
            g("Weight"), 0.0, bool(fillet), ax, ay, material, family, size, False, (sketch, edge),
            init_mirror_h=mirror == "Horizontal", init_mirror_v=mirror == "Vertical",
            init_rotation=float(group.get("rotation", 0.0)), init_offset_a=off_end, init_offset_b=off_start)
    globalize_links(obj)
    if App.GuiUp:
        ViewProviderProfile(obj.ViewObject)
    return obj


def _custom_member(doc, obj, sketch, edge, row, group, off_start, off_end):
    """A member of a profile from the Weldment Profiles folder: a FrameForge custom profile on a hidden copy of
    the profile, moved so its pierce point is on the path."""
    from .weprofile import Profile, ViewProviderProfile
    label, _material, path, size = row
    face, points = custom_profile(path)
    face = face.copy()
    face.translate(pierce_point(face, points, tuple(group.get("anchor", (1, 1)))) * -1)
    src = doc.addObject("Part::Feature", "MemberProfile")
    src.Shape = face
    src.Label = "%s (%s)" % (label, src.Name)
    if App.GuiUp:
        src.ViewObject.Visibility = False
        if "ShowInTree" in src.ViewObject.PropertiesList:
            src.ViewObject.ShowInTree = False
    b = face.BoundBox
    mirror = group.get("mirror", "")
    Profile(obj, b.XLength, b.YLength, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, 1, 1, "", "Custom Profile", size,
            False, (sketch, edge), custom_profile=src, init_mirror_h=mirror == "Horizontal",
            init_mirror_v=mirror == "Vertical", init_rotation=float(group.get("rotation", 0.0)),
            init_offset_a=off_end, init_offset_b=off_start)
    globalize_links(obj)
    if App.GuiUp:
        ViewProviderProfile(obj.ViewObject)
    return obj


def _sweep_profiles(doc):
    """Removes the hidden profile copies no member uses any more."""
    used = {getattr(o, "CustomProfile", None) for o in doc.Objects if hasattr(o, "CustomProfile")}
    for o in list(doc.Objects):
        if o.Name.startswith("MemberProfile") and o.TypeId == "Part::Feature" and o not in used:
            try:
                doc.removeObject(o.Name)
            except Exception as _fw_err:
                _fw_log("wemember.py:451", _fw_err)


def _trim(doc, body, boundary, kind, cut="Perfect fit"):
    from .weprofile import TrimmedProfile, ViewProviderTrimmedProfile
    obj = doc.addObject("Part::FeaturePython", "MemberTrim")
    TrimmedProfile(obj)
    if App.GuiUp:
        ViewProviderTrimmedProfile(obj.ViewObject)
    obj.TrimmedBody = body
    obj.TrimmingBoundary = boundary
    obj.TrimmedProfileType = kind
    if kind == "End Trim":
        obj.CutType = cut
    return obj


def _size_of(row):
    dims, _fillet = _spec(*row[1:])
    return max(float(dims.get("Width", 0) or 0), float(dims.get("Height", 0) or 0), 1.0)


class MergedMembers:
    """Merge miter trimmed bodies: the members of a mitered chain as one body."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkList", "Parts", GROUP, "The mitered members merged")
        obj.addProperty("App::PropertyLink", "TrimmedBody", GROUP, "The first of them (for its path)")
        obj.addProperty("App::PropertyBool", "Merged", GROUP, "Made by Merge miter trimmed bodies")
        obj.Merged = True
        obj.Proxy = self

    def execute(self, obj):
        shapes = [p.Shape for p in obj.Parts if not p.Shape.isNull()]
        if not shapes:
            return
        shape = shapes[0].fuse(shapes[1:]) if len(shapes) > 1 else shapes[0].copy()
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("wemember.py:491", _fw_err)
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ArcMember:
    """A structural member on an arc: the profile swept along the arc (FrameForge makes straight members only).
    Source is the FrameForge profile placed at the arc's start; its end face there is swept."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Source", GROUP, "The profile at the arc's start")
        obj.addProperty("App::PropertyLinkSub", "Path", GROUP, "The arc")
        obj.Proxy = self

    def execute(self, obj):
        src, path = obj.Source, obj.Path
        if src is None or src.Shape.isNull() or not path:
            return
        edge = path[0].Shape.getElement(path[1][0])
        # FrameForge stands the profile at one end of the arc (pointing along its tangent there): sweep that
        # end face along the arc from that end
        best = None
        for p, t, spine_edge in ((edge.Vertexes[0].Point, edge.tangentAt(edge.FirstParameter), edge),
                                 (edge.Vertexes[-1].Point, edge.tangentAt(edge.LastParameter), edge.reversed())):
            t = t.normalize()
            for f in src.Shape.Faces:
                if f.Surface.TypeId != "Part::GeomPlane" or abs(abs(f.normalAt(0, 0).dot(t)) - 1) > 1e-6:
                    continue
                d = abs((f.CenterOfMass - p).dot(t)) + (f.CenterOfMass - p).Length * 1e-3
                if best is None or d < best[0]:
                    best = (d, f, spine_edge)
        if best is None:
            raise RuntimeError("Arc member: the profile has no end face across the arc")
        _d, face, spine_edge = best
        edge = spine_edge
        spine = Part.Wire([edge])
        try:
            solid = spine.makePipe(face)
        except Exception:
            solid = None
        if solid is None or solid.isNull() or not solid.Solids:
            # sweep each wire of the profile (Frenet: a planar arc keeps the profile square to it)
            shells = [spine.makePipeShell([w], True, True) for w in face.Wires]
            solid = shells[0]
            for inner in shells[1:]:
                solid = solid.cut(inner)
        obj.Shape = solid

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_arc(sketch, edge):
    try:
        return sketch.Shape.getElement(edge).Curve.TypeId == "Part::GeomCircle"
    except Exception as _fw_err:
        _fw_log("wemember.py:557", _fw_err)
        return False


def _arc_member(doc, profile, sketch, edge):
    obj = doc.addObject("Part::FeaturePython", "ArcMember")
    ArcMember(obj)
    obj.Source = profile
    obj.Path = (sketch, [edge])
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
        profile.ViewObject.Visibility = False
    return obj


def _merge(doc, parts):
    obj = doc.addObject("Part::FeaturePython", "MergedMember")
    MergedMembers(obj)
    obj.Parts = parts
    obj.TrimmedBody = parts[0]
    if App.GuiUp:
        obj.ViewObject.Proxy = 0
    return obj


def _ensure(obj):
    """Properties added since the feature was first made."""
    if "TransferMaterial" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "TransferMaterial", GROUP, "Transfer material from profile")
        obj.TransferMaterial = True


def material_of(sm, base):
    ""

    if sm is not None and not getattr(sm, "TransferMaterial", True):
        return NO_MATERIAL
    raw = str(getattr(base, "Material", "") or "")
    return PROFILE_MATERIALS.get(raw, raw)


def _library(name):
    try:
        import Materials
        manager = Materials.MaterialManager()
        return next((m for m in manager.Materials.values() if m.Name == name), None)
    except Exception:
        return None


def _align_direction(doc, align):
    """The direction a group's Alignment pick gives (along an edge, square to a plane or face)."""
    if not align:
        return None
    obj = doc.getObject(align[0])
    if obj is None:
        return None
    from .westructure import direction_of
    try:
        return direction_of(obj, align[1] if len(align) > 1 else "")
    except Exception:
        return None


def rebuild(obj):
    """Recreates the weldment's members and trims (see refresh)."""
    refresh(obj.Document)


def structural_members(doc):
    return [o for o in doc.Objects if is_structural_member(o)]


_REFRESHING = [0]


def refreshing():
    """True while refresh rebuilds the members: a feature on them (Gusset, End Cap) that recomputes
    then may find its member gone for a moment and must not fail (pkg123: Gusset1 "a supporting face
    is gone" and the Stop and Repair box each time End Cap or Trim/Extend opened)."""
    return _REFRESHING[0] > 0


def refresh(doc):
    """Rebuilds every Structural Member, then every Trim/Extend, in tree order: a Trim/Extend works on
    the bodies as the features before it left them."""
    _REFRESHING[0] += 1
    try:
        _refresh(doc)
    finally:
        _REFRESHING[0] -= 1


def _refresh(doc):
    from . import wetrim
    wetrim.clear_all(doc)
    for sm in structural_members(doc):
        _rebuild_members(sm)
    _sweep_profiles(doc)
    doc.recompute()
    wetrim.build_all(doc)
    finish(doc)


def finish(doc):
    """Names and shows each body's newest shape (Structural Member1[1]...); the shapes it was made
    from are hidden and left out of the tree."""
    from . import wetrim
    made = []
    final = []
    for sm in structural_members(doc):
        made.extend(sm.Members)
        for k in range(len(sm.Bodies)):
            final.append((sm, k, wetrim.current_tip(doc, "%s:%d" % (sm.Name, k))))
    for te in wetrim.chain(doc):
        made.extend(te.Created)
    tips = [t for _sm, _k, t in final]
    for m in made:
        if m not in tips:
            m.Label = "%s (%s)" % (LABEL, m.Name)
    for sm, k, t in final:
        if t is not None:
            t.Label = "%s[%d]" % (sm.Label, k + 1)
            _transfer(sm, t)
    for m in made:
        try:
            vo = m.ViewObject
            vo.Visibility = m in tips
            if "ShowInTree" in vo.PropertiesList:
                vo.ShowInTree = m in tips
            if m.TypeId != "Part::FeaturePython" or hasattr(m, "TrimmedBody") or hasattr(m, "Target"):
                vo.Transparency = 0
                vo.ShapeColor = (0.62, 0.65, 0.70)
        except Exception as _fw_err:
            _fw_log("wemember.py:688", _fw_err)
    from . import wecutlist
    wecutlist.update(doc)


def _transfer(sm, body):
    """Transfer material from profile: the body takes the profile's material from FreeCAD's library."""
    if not getattr(sm, "TransferMaterial", True) or "ShapeMaterial" not in body.PropertiesList:
        return
    from . import wetrim
    mat = _library(material_of(sm, wetrim.base_of(body)))
    try:
        if mat is not None and body.ShapeMaterial.UUID != mat.UUID:
            body.ShapeMaterial = mat
    except Exception as _fw_err:
        _fw_log("wemember.py:703", _fw_err)


def _rebuild_members(obj):
    """Recreates one Structural Member's members: profiles on every segment, then the corner trims."""
    if type(obj.Proxy).__name__ in ("PrimaryMember", "SecondaryMember"):
        from . import westructure
        return westructure.rebuild(obj)
    doc = obj.Document
    _ensure(obj)
    for m in reversed(list(obj.Members)):
        try:
            doc.removeObject(m.Name)
        except Exception as _fw_err:
            _fw_log("wemember.py:717", _fw_err)
    row = find_size(obj.Standard, obj.Type, obj.Size)
    members, tips = [], []
    if row is None:
        obj.Members = obj.Bodies = []
        return
    extend = 2 * _size_of(row)
    from .wetrim import _trim_plane
    built = []          # per group: (group, segments, profiles, tip, miter pairs)
    for group in groups(obj):
        segments = [(doc.getObject(s), e) for s, e in group["segments"]]
        segments = [(s, e) for s, e in segments if s is not None]
        corner = group.get("corner", "End Miter") if group.get("kind", "Planar") != "Parallel" else ""
        arcs = {k for k, (s, e) in enumerate(segments) if is_arc(s, e)}
        touching = corners(segments)
        pairs = [p for p in touching if p[0] not in arcs and p[1] not in arcs] if corner else []
        off = {}
        for i, j, a, b, _p in pairs:
            if corner == "End Miter":
                off[(i, a)] = off[(j, b)] = extend
            else:
                through = i if corner == "End Butt1" else j
                if _protrude(group):
                    off[(through, a if through == i else b)] = extend
                if _coped(group):        # the butting member reaches into the other, then is cut to its shape
                    off[(j if through == i else i, b if through == i else a)] = extend
        profiles = [_profile(doc, s, e, row, group, off.get((k, 0), 0.0), off.get((k, 1), 0.0))
                    for k, (s, e) in enumerate(segments)]
        members.extend(profiles)
        if arcs:
            doc.recompute([profiles[k] for k in arcs])
            for k in sorted(arcs):
                a = _arc_member(doc, profiles[k], *segments[k])
                members.append(a)
                profiles[k] = a
        tip = list(profiles)
        gap_in = float(group.get("gap_in", 0.0) or 0.0)
        direction = _align_direction(doc, group.get("align"))
        if pairs or direction is not None:
            doc.recompute(profiles)
        if direction is not None:           # Alignment: the profile's axis lines up with the pick
            from .westructure import _align
            _align(profiles, direction, "VerticalAxis" if group.get("align_axis") == "Vertical" else "HorizontalAxis",
                   float(group.get("rotation", 0.0)))
            doc.recompute(profiles)
        miters = []
        for i, j, a, b, point in pairs:
            if corner == "End Miter":
                if gap_in > TOL:            # Gap within group: each mitered end stands back half the gap
                    pi = _trim_plane(doc, "miter", A=profiles[i], B=profiles[j], Gap=gap_in / 2, Keep=profiles[i])
                    pj = _trim_plane(doc, "miter", A=profiles[i], B=profiles[j], Gap=gap_in / 2, Keep=profiles[j])
                    doc.recompute([pi, pj])
                    ti = _trim(doc, tip[i], [(pi, ["Face1"])], "End Trim", "Simple fit")
                    tj = _trim(doc, tip[j], [(pj, ["Face1"])], "End Trim", "Simple fit")
                    members.extend((pi, pj))
                else:
                    ti = _trim(doc, tip[i], [(profiles[j], ["Edge1"])], "End Miter")
                    tj = _trim(doc, tip[j], [(profiles[i], ["Edge1"])], "End Miter")
                tip[i], tip[j] = ti, tj
                members.extend((ti, tj))
                miters.append((i, j))
                continue
            through, butt = (i, j) if corner == "End Butt1" else (j, i)
            end = a if through == i else b
            s, e = segments[through]
            p0, p1 = _ends(s, e)
            outward = (p1 - p0).normalize() if end == 1 else (p0 - p1).normalize()
            if _protrude(group):
                face = _outer_face(profiles[butt].Shape, point, outward)
                if face is not None:
                    tt = _trim(doc, tip[through], [(profiles[butt], [face])], "End Trim", "Simple fit")
                else:                       # a round member has no flat face across: stop at its far side
                    far = _flat_end(doc, profiles[butt], point, outward)
                    tt = _trim(doc, tip[through], [(far, ["Face1"])], "End Trim", "Simple fit")
                    members.append(far)
                members.append(tt)
            else:
                tt = tip[through]           # no protrusion: it ends where its path segment ends
            if _coped(group):
                fill = _filled(doc, tt, p1 - p0)
                tb = _trim(doc, tip[butt], [(fill, ["Face1"])], "End Trim", "Perfect fit")   # coped to its shape
                tip[through], tip[butt] = tt, tb
                members.extend((fill, tb) if fill is not tt else (tb,))
                continue
            from .wetrim import _trim_plane      # the butting member stops flat on the other's face
            s2, e2 = segments[butt]
            q0, q1 = _ends(s2, e2)
            away = (q1 - q0).normalize() if (q0 - point).Length < (q1 - point).Length else (q0 - q1).normalize()
            if _outer_face(profiles[through].Shape, point, away) is None:
                # a round member has no flat face: the flat cut touches its side (less the gap)
                plane = _flat_end(doc, profiles[through], point, away, gap_in)
            else:
                plane = _trim_plane(doc, "near", Body=profiles[through], Trimmed=profiles[butt],
                                    End=b if through == i else a, Unbounded=True, Gap=gap_in, Keep=profiles[butt])
                doc.recompute([plane])
            tb = _trim(doc, tip[butt], [(plane, ["Face1"])], "End Trim", "Simple fit")
            tip[through], tip[butt] = tt, tb
            members.extend((plane, tb))
        if group.get("merge_arcs") and arcs:
            # Merge arc segment bodies: an arc and the members it touches become one body
            arc_pairs = [(i, j) for i, j, _a, _b, _p in touching if i in arcs or j in arcs]
            group = dict(group, _arc_pairs=arc_pairs)
        built.append((group, segments, profiles, tip, miters))
    # members of a later group that end on (or in) a member of an earlier group stop at its face, less the

    reach = _size_of(row) / 2
    for gi, (group, segments, profiles, tip, _m) in enumerate(built):
        gap_out = float(group.get("gap_out", 0.0) or 0.0)
        for k, (s, e) in enumerate(segments):
            if is_arc(s, e):
                continue            # an arc member is a sweep: not trimmed between groups
            ends = _ends(s, e)
            for end in (0, 1):
                hit = None
                for _g, other_segments, other_profiles, _t, _mm in built[:gi]:
                    for n, (os_, oe) in enumerate(other_segments):
                        a0, a1 = _ends(os_, oe)
                        if Part.LineSegment(a0, a1).toShape().distToShape(Part.Vertex(ends[end]))[0] <= reach:
                            hit = other_profiles[n]         # it ends on (or in) that member
                            hit_axis = a1 - a0
                            break
                    if hit is not None:
                        break
                if hit is None:
                    continue
                if _coped(group) and gap_out <= TOL:
                    # coped: the member's end is fitted to the shape of the member it ends on
                    doc.recompute([tip[k]])
                    fill = _filled(doc, hit, hit_axis)
                    t = _trim(doc, tip[k], [(fill, ["Face1"])], "End Trim", "Perfect fit")
                    tip[k] = t
                    members.extend((fill, t) if fill is not hit else (t,))
                    continue
                away = (ends[1 - end] - ends[end]).normalize()
                if _outer_face(hit.Shape, ends[end], away) is None:
                    plane = _flat_end(doc, hit, ends[end], away, gap_out)     # a round member: flat on its side
                else:
                    plane = _trim_plane(doc, "near", Body=hit, Trimmed=profiles[k], End=end, Unbounded=True,
                                        Gap=gap_out, Keep=profiles[k])
                    doc.recompute([plane])
                t = _trim(doc, tip[k], [(plane, ["Face1"])], "End Trim", "Simple fit")
                tip[k] = t
                members.extend((plane, t))
    for group, segments, profiles, tip, miters in built:
        joins = list(miters) if group.get("merge") and group.get("corner", "End Miter") == "End Miter" else []
        joins += group.get("_arc_pairs", [])
        if joins:
            # Merge miter trimmed bodies: each mitered chain becomes one body
            parent = list(range(len(tip)))

            def root(x):
                while parent[x] != x:
                    x = parent[x]
                return x
            for i, j in joins:
                parent[root(i)] = root(j)
            chains = {}
            for k in range(len(tip)):
                chains.setdefault(root(k), []).append(k)
            out = []
            for k in range(len(tip)):
                chain = chains[root(k)]
                if len(chain) == 1:
                    out.append(tip[k])
                elif k == chain[0]:
                    doc.recompute([tip[c] for c in chain])
                    merged = _merge(doc, [tip[c] for c in chain])
                    members.append(merged)
                    out.append(merged)
            tip = out
        tips.extend(tip)
    obj.Members = members
    obj.Bodies = tips


def groups(obj):
    try:
        return json.loads(obj.Groups or "[]")
    except Exception:
        return []


# ---------------------------------------------------------------- features
class Weldment:
    ""

    def __init__(self, obj):
        obj.addProperty("App::PropertyBool", "SWWeldment", "Weldment", "This part is a weldment").SWWeldment = True
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _empty_mode(vobj):
    ""
    from pivy import coin
    vobj.addDisplayMode(coin.SoGroup(), "Default")


class ViewProviderWeldment:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        _empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            return _weicon("metalwb.svg")
        except Exception:
            return ""

    def dumps(self):
        return None

    def loads(self, state):
        return None


def weldment(doc, create=True):
    found = next((o for o in doc.Objects if "SWWeldment" in o.PropertiesList), None)
    if found is None and create:
        from . import wecutlist
        wecutlist.folder(doc, create=True)          # Cut list sits above the weldment's features
        found = doc.addObject("App::FeaturePython", "Weldment")
        Weldment(found)
        if App.GuiUp:
            ViewProviderWeldment(found.ViewObject)
        found.Label = "Weldment"
        try:
            from . import weldprops
            weldprops.on_new_weldment(doc)      # Document Properties > Weldments: derived configurations
        except Exception as error:
            App.Console.PrintLog("FreeCAD: %s\n" % error)
    return found


class StructuralMember:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyString", "Standard", GROUP, "Profile standard")
        add("App::PropertyString", "Type", GROUP, "Profile type")
        add("App::PropertyString", "Size", GROUP, "Profile size")
        add("App::PropertyString", "Groups", GROUP, "Groups: segments and settings (JSON)")
        add("App::PropertyLinkList", "Members", GROUP, "FrameForge objects made by this feature")
        add("App::PropertyLinkList", "Bodies", GROUP, "The member bodies")
        add("App::PropertyLinkListGlobal", "PathSketches", GROUP, "Sketches holding the path segments")
        _ensure(obj)
        for name in ("Groups", "Members", "Bodies"):
            obj.setEditorMode(name, 2)
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderStructuralMember:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        _empty_mode(vobj)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        try:
            return _weicon("profile.svg")
        except Exception:
            return ""

    def tips(self):
        from . import wetrim
        obj = self.Object
        tips = [wetrim.current_tip(obj.Document, "%s:%d" % (obj.Name, k)) for k in range(len(obj.Bodies))]
        return [t for t in tips if t is not None]

    def claimChildren(self):
        if not hasattr(self, "Object"):     # asked before attach() on a reopened file (pkg123)
            return []
        from . import wecutlist
        return [] if wecutlist.folder(self.Object.Document) is not None else self.tips()

    def onChanged(self, vobj, prop):
        if prop == "Visibility":        # Hide/Show on the feature hides/shows its bodies
            try:
                if vobj.Object.Document.Restoring or vobj.Object.isRestoring():
                    return          # reopening: each body keeps the visibility it was saved with
            except Exception:
                pass
            for b in self.tips():
                try:
                    b.ViewObject.Visibility = vobj.Visibility
                except Exception as _fw_err:
                    _fw_log("wemember.py:992", _fw_err)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + TITLE)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def onDelete(self, vobj, subelements):
        from . import wetrim
        doc = vobj.Object.Document
        wetrim.clear_all(doc)
        for m in reversed(list(vobj.Object.Members)):
            try:
                doc.removeObject(m.Name)
            except Exception as _fw_err:
                _fw_log("wemember.py:1017", _fw_err)
        if wetrim.chain(doc):        # the other bodies' trims come back once it is gone
            QtCore.QTimer.singleShot(0, lambda: wetrim._refresh_later(doc))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_structural_member(obj):
    """A Structural Member, or a Structure System's Primary Member (built the same way)."""
    return type(getattr(obj, "Proxy", None)).__name__ in ("StructuralMember", "PrimaryMember", "SecondaryMember")


def make(doc):
    doc.openTransaction(TITLE)
    try:
        weldment(doc)
        obj = doc.addObject("App::FeaturePython", "StructuralMember")
        StructuralMember(obj)
        if App.GuiUp:
            ViewProviderStructuralMember(obj.ViewObject)
        p = App.ParamGet(PARAMS)
        obj.Standard = p.GetString("Standard", DEFAULT[0])
        obj.Type = p.GetString("Type", DEFAULT[1])
        obj.Size = p.GetString("Size", DEFAULT[2])
        if find_size(obj.Standard, obj.Type, obj.Size) is None:
            obj.Standard, obj.Type, obj.Size = DEFAULT
            if find_size(*DEFAULT) is None:
                std = next(iter(catalog()))
                kind = next(iter(catalog()[std]))
                obj.Standard, obj.Type, obj.Size = std, kind, catalog()[std][kind][0][0]
        obj.Groups = json.dumps([new_group()])
        obj.Label = naming.next_label(doc, LABEL)
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


def new_group():
    return {"segments": [], "kind": "Planar", "corner": "End Miter", "mirror": "", "rotation": 0.0, "anchor": [1, 1], "merge": False,
            "merge_arcs": False, "cut": "Coped cut", "protrude": True, "gap_in": 0.0, "gap_out": 0.0, "align": None, "align_axis": "Horizontal"}


# ---------------------------------------------------------------- PropertyManager
def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


def _box_visible(box, on):
    """Show or hide a page's group with its header (FreeCAD wraps each form widget in a task box)."""
    def apply():
        try:
            w = box
            while w is not None and w.metaObject().className() not in ("Gui::TaskView::TaskBox", "QSint::ActionGroup"):
                w = w.parentWidget()
            if w is None:
                box.setVisible(on)
            else:
                box.setVisible(True)            # hidden by a call made before the page was wrapped
                w.setVisible(on)
        except RuntimeError:
            return
    apply()
    QtCore.QTimer.singleShot(0, apply)          # the page may not be shown (wrapped) yet


def _radio(name, text):
    b = QtWidgets.QRadioButton(text)
    b.setObjectName(name)
    return b


class Panel:
    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = True
        _ensure(obj)
        self.groups = groups(obj) or [new_group()]
        for g in self.groups:
            for k, v in new_group().items():
                g.setdefault(k, v)
        self.current = 0
        self.active = "segments"

        message = _box("Message")
        hint = QtWidgets.QLabel(MESSAGE)
        self.hint = hint
        hint.setObjectName("SWWEMessage")
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel { background: #fff8c4; color: #000; padding: 4px; }")
        message.layout().addRow(hint)

        selections = _box("Selections")
        f = selections.layout()
        self.standard = QtWidgets.QComboBox()
        self.standard.setObjectName("SWWEStandard")
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("SWWEType")
        self.size = QtWidgets.QComboBox()
        self.size.setObjectName("SWWESize")
        self.standard.addItems(list(catalog()))
        self.standard.setCurrentText(obj.Standard)
        self._fill_types(obj.Type, obj.Size)
        f.addRow("Standard:", self.standard)
        f.addRow("Type:", self.kind)
        f.addRow("Size:", self.size)
        favorites_row(self, f)
        self.transfer = QtWidgets.QCheckBox("Transfer Material from Profile")
        self.transfer.setObjectName("SWWETransfer")
        self.transfer.setChecked(bool(obj.TransferMaterial))
        self.transfer.setToolTip("The members take the profile's material (cut list and mass)")
        f.addRow(self.transfer)

        groups_box = _box("Groups")
        f = groups_box.layout()
        self.group_list = QtWidgets.QListWidget()
        self.group_list.setObjectName("SWWEGroups")
        self.group_list.setMaximumHeight(70)
        f.addRow(self.group_list)
        self.new_group = QtWidgets.QPushButton("New Group")
        self.new_group.setObjectName("SWWENewGroup")
        f.addRow(self.new_group)

        # group's segments are parallel to each other and get no corner treatment
        self.kinds = QtWidgets.QButtonGroup(groups_box)
        row = QtWidgets.QHBoxLayout()
        for i, text in enumerate(("Planar group", "Parallel group")):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWE" + text.replace(" ", ""))
            b.setText(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            self.kinds.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)

        settings = _box("Settings")
        self.settings_box = settings
        f = settings.layout()
        f.addRow(QtWidgets.QLabel("Path segments:"))
        self.segments = QtWidgets.QListWidget()
        self.segments.setObjectName("SWWESegments")
        self.segments.setMaximumHeight(90)
        pmboxes.mark(self.segments, True)
        self.segments.setToolTip("Sketch segments of this group. Delete removes one.")
        self.segments.installEventFilter(self._delete_filter())
        self.segments.installEventFilter(self._focus_filter("segments"))
        f.addRow(self.segments)

        self.corner_on = QtWidgets.QCheckBox("Apply corner treatment")
        self.corner_on.setObjectName("SWWECornerOn")
        f.addRow(self.corner_on)
        self.corners = QtWidgets.QButtonGroup(settings)
        row = QtWidgets.QHBoxLayout()
        for i, text in enumerate(CORNERS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWECorner" + text.replace(" ", ""))
            b.setText(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            from . import pmpics
            pmpics.picture(b, "corner", text)
            self.corners.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)

        # protrusion
        self.cuts = QtWidgets.QButtonGroup(settings)
        self.cut_row = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.cut_row)
        row.setContentsMargins(0, 0, 0, 0)
        for i, text in enumerate(BUTT_CUTS):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWWE" + text.replace(" ", ""))
            b.setText(text)
            b.setToolTip(text + (": the end is cut flat on the face it meets" if i == 0 else
                                 ": the end is fitted to the shape of the member it meets"))
            b.setCheckable(True)
            b.setAutoRaise(True)
            self.cuts.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self.protrude = QtWidgets.QCheckBox("Allow protrusion")
        self.protrude.setObjectName("SWWEProtrude")
        self.protrude.setToolTip("At an End Butt corner the through member runs past the end of its path to cover "
                                 "the butting member; off, it stops at the end of its path")
        self.merge = QtWidgets.QCheckBox("Merge miter trimmed bodies")
        self.merge.setObjectName("SWWEMerge")
        self.merge.setToolTip("Each mitered chain of members becomes one body")
        f.addRow(self.merge)
        self.merge_arcs = QtWidgets.QCheckBox("Merge arc segment bodies")
        self.merge_arcs.setObjectName("SWWEMergeArcs")
        self.merge_arcs.setToolTip("An arc segment's body and the members it touches become one body")
        f.addRow(self.merge_arcs)
        self.gap_in = QtWidgets.QDoubleSpinBox()
        self.gap_in.setObjectName("SWWEGapIn")
        self.gap_out = QtWidgets.QDoubleSpinBox()
        self.gap_out.setObjectName("SWWEGapOut")
        for w in (self.gap_in, self.gap_out):
            w.setKeyboardTracking(False)     # rebuilt on Enter / Tab, so "0.5in" is read whole
            w.setSuffix(" mm")
            w.setRange(0.0, 1000.0)
            w.setDecimals(2)
        self.gap_in.setToolTip("Gap within group: the gap left at the corners between this group's members")
        self.gap_out.setToolTip("Gap with other groups: the gap left where this group's members end on another group's")
        f.addRow(self.cut_row)
        f.addRow("Gap within group", self.gap_in)
        f.addRow("Gap with other groups", self.gap_out)
        f.addRow(self.protrude)
        self.mirror = QtWidgets.QCheckBox("Mirror Profile")
        self.mirror.setObjectName("SWWEMirror")
        f.addRow(self.mirror)
        self.mirror_axes = QtWidgets.QButtonGroup(settings)
        for i, (text, value) in enumerate((("Horizontal axis", "Horizontal"), ("Vertical axis", "Vertical"))):
            b = _radio("SWWEMirror" + value, text)
            self.mirror_axes.addButton(b, i)
            f.addRow(b)
        self.align = QtWidgets.QListWidget()
        self.align.setObjectName("SWWEAlign")
        self.align.setMaximumHeight(28)
        self.align.setToolTip("Alignment: an edge, axis, plane or face the profile lines up with. Delete clears it.")
        self.align.installEventFilter(self._focus_filter("align"))
        f.addRow("Alignment", self.align)
        self.align_axes = QtWidgets.QButtonGroup(settings)
        for i, (text, value) in enumerate((("Align horizontal axis", "Horizontal"), ("Align vertical axis", "Vertical"))):
            b = _radio("SWWEAlign" + value, text)
            self.align_axes.addButton(b, i)
            f.addRow(b)
        self.rotation = QtWidgets.QDoubleSpinBox()
        self.rotation.setObjectName("SWWERotation")
        self.rotation.setRange(-360.0, 360.0)
        self.rotation.setKeyboardTracking(False)
        self.rotation.setSuffix(" deg")
        self.rotation.setSingleStep(90.0)
        f.addRow("Rotation Angle", self.rotation)
        self.locate = QtWidgets.QPushButton("Locate Profile")
        self.locate.setObjectName("SWWELocate")
        self.locate.setCheckable(True)
        f.addRow(self.locate)
        self.anchor_box = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.anchor_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.anchors = QtWidgets.QButtonGroup(self.anchor_box)
        for ay in range(3):
            for ax in range(3):
                b = _radio("SWWEAnchor%d%d" % (ax, ay), "")
                b.setToolTip("Path through the profile's %s %s" % (("bottom", "centre", "top")[ay],
                                                                   ("left", "centre", "right")[ax]))
                self.anchors.addButton(b, ay * 3 + ax)
                grid.addWidget(b, 2 - ay, ax)
        f.addRow(self.anchor_box)
        self.anchor_box.setVisible(False)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWWEError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        f.addRow(self.error)

        message.setProperty("swstyle_pm_title", TITLE)
        message.setProperty("swstyle_pm_icon", "SWStyle_WEStructuralMember")
        self.form = [message, selections, groups_box, settings]
        self._show_groups()
        self._show_group()
        self.set_active("segments")

        self.standard.currentIndexChanged.connect(self._standard_changed)
        self.kind.currentIndexChanged.connect(self._type_changed)
        self.size.currentIndexChanged.connect(self._changed)
        self.new_group.clicked.connect(self._add_group)
        pmboxes.bind(self.group_list, remove=self._drop_group)
        self.group_list.currentRowChanged.connect(self._group_picked)
        self.corner_on.toggled.connect(self._settings_changed)
        self.kinds.buttonClicked.connect(self._kind_changed)
        self.corners.buttonClicked.connect(self._settings_changed)
        self.cuts.buttonClicked.connect(self._settings_changed)
        self.protrude.toggled.connect(self._settings_changed)
        self.mirror.toggled.connect(self._settings_changed)
        self.mirror_axes.buttonClicked.connect(self._settings_changed)
        self.rotation.valueChanged.connect(self._settings_changed)
        self.anchors.buttonClicked.connect(self._settings_changed)
        self.locate.toggled.connect(self.anchor_box.setVisible)
        self.transfer.toggled.connect(self._changed)
        self.merge.toggled.connect(self._settings_changed)
        self.merge_arcs.toggled.connect(self._settings_changed)
        self.gap_in.valueChanged.connect(self._settings_changed)
        self.gap_out.valueChanged.connect(self._settings_changed)
        self.align_axes.buttonClicked.connect(self._settings_changed)
        self.busy = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def _delete_filter(self):
        panel = self

        class _Keys(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Delete:
                    panel.remove_current()
                    return True
                return False
        self._keys = _Keys()
        return self._keys

    def _focus_filter(self, which):
        panel = self

        class _Focus(QtCore.QObject):
            def eventFilter(self, watched, event):
                if not isinstance(event, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                t = event.type()
                if t in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                    panel.set_active(which)
                elif which == "align" and t == QtCore.QEvent.KeyPress and event.key() in (
                        QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
                    panel.groups[panel.current]["align"] = None
                    panel._show_group()
                    panel._changed()
                    return True
                return False
        f = _Focus()
        self.__dict__.setdefault("_focus", []).append(f)
        return f

    def set_active(self, which):
        ""
        self.active = which
        for name, w in (("segments", self.segments), ("align", self.align)):
            pmboxes.mark(w, name == which)

    def _fill_types(self, kind=None, size=None):
        busy, self.busy = self.busy, True
        types = catalog().get(self.standard.currentText(), {})
        self.kind.clear()
        self.kind.addItems(list(types))
        if kind in types:
            self.kind.setCurrentText(kind)
        self._fill_sizes(size)
        self.busy = busy

    def _fill_sizes(self, size=None):
        busy, self.busy = self.busy, True
        rows = catalog().get(self.standard.currentText(), {}).get(self.kind.currentText(), [])
        self.size.clear()
        self.size.addItems([r[0] for r in rows])
        if size in [r[0] for r in rows]:
            self.size.setCurrentText(size)
        self.busy = busy

    def _show_groups(self):
        busy, self.busy = self.busy, True
        self.group_list.clear()
        for i in range(len(self.groups)):
            self.group_list.addItem("Group%d" % (i + 1))
        self.group_list.setCurrentRow(self.current)
        self.busy = busy

    def _show_group(self):
        busy, self.busy = self.busy, True
        g = self.groups[self.current]
        self.segments.clear()
        for s, e in g["segments"]:
            sk = self.obj.Document.getObject(s)
            self.segments.addItem("%s@%s" % (e.replace("Edge", "Line"), sk.Label if sk else s))

        has_path = any(gr["segments"] for gr in self.groups)
        self.hint.setText(MESSAGE_PATH if has_path else MESSAGE)
        _box_visible(self.settings_box, has_path)
        parallel = g.get("kind", "Planar") == "Parallel"
        self.kinds.button(1 if parallel else 0).setChecked(True)
        corner = g.get("corner", "End Miter") if not parallel else ""
        self.corner_on.setChecked(bool(corner))
        from . import smlive            # no greyed boxes: what does not apply is hidden (drawings-land281)
        smlive.row(self.corner_on, not parallel)
        for i, text in enumerate(CORNERS):
            self.corners.button(i).setChecked(text == (corner or "End Miter"))
            self.corners.button(i).setVisible(bool(corner))
        mirror = g.get("mirror", "")
        self.mirror.setChecked(bool(mirror))
        self.mirror_axes.button(0).setChecked(mirror != "Vertical")
        self.mirror_axes.button(1).setChecked(mirror == "Vertical")
        for b in self.mirror_axes.buttons():
            b.setVisible(bool(mirror))
        self.rotation.setValue(float(g.get("rotation", 0.0)))
        miter = (corner or "") == "End Miter"
        self.merge.setChecked(bool(g.get("merge")) and miter)
        smlive.row(self.merge, miter)
        arcs = any(is_arc(self.obj.Document.getObject(sn), e) for sn, e in g["segments"]
                   if self.obj.Document.getObject(sn) is not None)
        self.merge_arcs.setChecked(bool(g.get("merge_arcs")))
        smlive.row(self.merge_arcs, arcs)        # shown once the group has an arc
        self.gap_in.setValue(float(g.get("gap_in", 0.0) or 0.0))
        smlive.row(self.gap_in, bool(corner))
        self.gap_out.setValue(float(g.get("gap_out", 0.0) or 0.0))
        butt = (corner or "").startswith("End Butt")
        self.cuts.button(1 if _coped(g) else 0).setChecked(True)
        self.cut_row.setVisible(butt or len(self.groups) > 1)    # shown where a member's end butts on another
        self.protrude.setChecked(_protrude(g))
        smlive.row(self.protrude, butt)
        self.align.clear()
        align = g.get("align")
        if align:
            o = self.obj.Document.getObject(align[0])
            sub = align[1] if len(align) > 1 else ""
            label = o.Label if o else align[0]
            self.align.addItem("%s@%s" % (sub, label) if sub else label)
        self.align_axes.button(0).setChecked(g.get("align_axis", "Horizontal") != "Vertical")
        self.align_axes.button(1).setChecked(g.get("align_axis") == "Vertical")
        ax, ay = g.get("anchor", (1, 1))
        self.anchors.button(ay * 3 + ax).setChecked(True)
        self.busy = busy

    # ---------------------------------------------------------------- changes
    def _standard_changed(self, *args):
        if self.busy:
            return
        self._fill_types()
        self._changed()

    def _type_changed(self, *args):
        if self.busy:
            return
        self._fill_sizes()
        self._changed()

    def _add_group(self):
        self.groups.append(new_group())
        self.current = len(self.groups) - 1
        self._show_groups()
        self._show_group()

    def _group_picked(self, row):
        if self.busy or row < 0:
            return
        self.current = row
        self._show_group()

    def _drop_group(self, row):
        ""
        if len(self.groups) < 2 or not 0 <= row < len(self.groups):
            return
        del self.groups[row]
        self.current = min(self.current if self.current < row else max(0, self.current - 1), len(self.groups) - 1)
        self._show_groups()
        self._show_group()
        self._changed()

    def _kind_changed(self, *args):
        if self.busy:
            return
        problem = self._check_kind(self.groups[self.current]["segments"], self.kinds.checkedId() == 1)
        if problem:
            self.kinds.button(0).setChecked(True)
            self.error.setText(problem)
            self.error.show()
        self._settings_changed()

    def _check_kind(self, segments, parallel):
        """Why these segments cannot make the group type, else ""."""
        dirs = []
        for s, e in segments:
            sk = self.obj.Document.getObject(s)
            if sk is None:
                continue
            a, b = _ends(sk, e)
            if (b - a).Length > 1e-9:
                dirs.append((b - a).normalize())
        if parallel:
            if any(d.cross(dirs[0]).Length > 1e-6 for d in dirs[1:]):
                return "The segments of a parallel group must be parallel to each other."
            return ""

        # group, and the corner treatment works at each corner on the two members that meet there
        return ""

    def _settings_changed(self, *args):
        if self.busy:
            return
        g = self.groups[self.current]
        g["kind"] = "Parallel" if self.kinds.checkedId() == 1 else "Planar"
        if g["kind"] != "Parallel":
            g["corner"] = CORNERS[max(0, self.corners.checkedId())] if self.corner_on.isChecked() else ""
        g["mirror"] = ("Horizontal", "Vertical")[max(0, self.mirror_axes.checkedId())] if self.mirror.isChecked() else ""
        g["rotation"] = self.rotation.value()
        a = max(0, self.anchors.checkedId())
        g["anchor"] = [a % 3, a // 3]
        g["merge"] = self.merge.isChecked() and g["corner"] == "End Miter"
        g["merge_arcs"] = self.merge_arcs.isChecked()
        g["gap_in"] = self.gap_in.value()
        g["gap_out"] = self.gap_out.value()
        g["cut"] = BUTT_CUTS[max(0, self.cuts.checkedId())]
        g["protrude"] = self.protrude.isChecked()
        g["align_axis"] = ("Horizontal", "Vertical")[max(0, self.align_axes.checkedId())]
        self._show_group()
        self._changed()

    def _changed(self, *args):
        if self.busy:
            return
        obj = self.obj
        obj.Standard = self.standard.currentText()
        obj.Type = self.kind.currentText()
        obj.Size = self.size.currentText()
        obj.TransferMaterial = self.transfer.isChecked()
        obj.Groups = json.dumps(self.groups)
        sketches = []
        for g in self.groups:
            for s, _e in g["segments"]:
                sk = obj.Document.getObject(s)
                if sk is not None and sk not in sketches:
                    sketches.append(sk)
        obj.PathSketches = sketches
        try:
            rebuild(obj)
            self.error.hide()
        except Exception as error:
            self.error.setText(str(error))
            self.error.show()

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        if self.active == "align":
            QtCore.QTimer.singleShot(0, lambda: self._picked_align(doc, name, sub))
        elif sub.startswith("Edge"):
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub))

    def _picked_align(self, doc_name, name, sub):
        """Alignment: one straight edge, axis, plane or face; a second click on it takes it out."""
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wemember.py:1499", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        from .westructure import direction_of
        try:
            direction_of(picked, sub)
        except Exception:
            return              # not something with a direction
        g = self.groups[self.current]
        g["align"] = None if g.get("align") == [picked.Name, sub] else [picked.Name, sub]
        self._show_group()
        self._changed()

    def add_segments(self, sketch, edges):
        g = self.groups[self.current]
        known = {(s, e) for s, e in (tuple(x) for gg in self.groups for x in gg["segments"])}
        new = [e for e in edges if (sketch.Name, e) not in known]
        problem = self._check_kind(g["segments"] + [[sketch.Name, e] for e in new], g.get("kind") == "Parallel")
        if problem:
            self.error.setText(problem)
            self.error.show()
            return
        added = False
        for e in edges:
            if (sketch.Name, e) not in known:
                g["segments"].append([sketch.Name, e])
                added = True
        if added:
            self._show_group()
            self._changed()

    def _picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("wemember.py:1535", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        if not is_path_sketch(picked):
            target = getattr(picked, "Target", None)          # a member: its path
            if target is None:
                return
            picked, subs = target[0], list(target[1])
            sub = subs[0] if subs else sub
        self.add_segments(picked, [sub])

    def remove_current(self):
        row = self.segments.currentRow()
        if row < 0:
            return
        del self.groups[self.current]["segments"][row]
        self._show_group()
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("wemember.py:1563", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("wemember.py:1569", _fw_err)

    def accept(self):
        if not any(g["segments"] for g in self.groups):
            self.error.setText("Select sketch segments for the path of the member.")
            self.error.show()
            return False
        p = App.ParamGet(PARAMS)
        p.SetString("Standard", self.standard.currentText())
        p.SetString("Type", self.kind.currentText())
        p.SetString("Size", self.size.currentText())

        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        doc.abortTransaction()
        doc.recompute()
        self._close()
        return True


def is_path_sketch(obj):
    ""

    return obj is not None and (obj.TypeId == "Sketcher::SketchObject"
                                or getattr(getattr(obj, "Proxy", None), "Type", None) == "FreeWorksSketch3D")


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    picked = []
    for s in Gui.Selection.getSelectionEx():
        if is_path_sketch(s.Object):
            edges = [n for n in s.SubElementNames if n.startswith("Edge")]
            if not edges:
                edges = ["Edge%d" % (i + 1) for i in range(len(s.Object.Shape.Edges))]
            picked.append((s.Object, edges))
    obj = make(doc)
    panel = Panel(obj, True)
    Gui.Control.showDialog(panel)
    for sketch, edges in picked:
        panel.add_segments(sketch, edges)


def _engine_ready():
    ""
    return True


class Command:
    def GetResources(self):
        try:
            pixmap = _weicon("profile.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Structural Member",
                "ToolTip": "Places a standard profile along sketch segments."}

    def IsActive(self):
        if App.ActiveDocument is None or not _engine_ready():
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        start()


class WeldmentCommand:
    def GetResources(self):
        try:
            pixmap = _weicon("metalwb.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Weldment",
                "ToolTip": "Makes the part a weldment, with a cut list of its members."}

    def IsActive(self):
        return App.ActiveDocument is not None and weldment(App.ActiveDocument, create=False) is None

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Weldment")
        try:
            weldment(doc)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        doc.recompute()


def show_tips_only(doc):
    """A reopened weldment shows what was saved: each body's newest shape, not the shapes it was made from
    (FreeCAD showed every Member / MemberTrim again on open: 1.77M -> 9.08M mm3 visible, wf gate frame)."""
    try:
        sms = structural_members(doc)
    except Exception:
        return
    if not sms:
        return
    from . import wetrim
    made, tips = [], set()
    for sm in sms:
        made.extend(sm.Members)
        for k in range(len(sm.Bodies)):
            t = wetrim.current_tip(doc, "%s:%d" % (sm.Name, k))
            if t is not None:
                tips.add(t.Name)
    for te in wetrim.chain(doc):
        made.extend(te.Created)
    for m in made:
        try:
            if m.Name not in tips and m.ViewObject.Visibility:
                m.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("wemember.py:show_tips_only", _fw_err)


_HOOKED = []


def _reopened(doc, tries=8):
    """After open: the weldment objects' own classes may still be coming back; try again a little later."""
    name = doc.Name
    if not any(is_structural_member(o) for o in doc.Objects):
        if tries > 0:
            from PySide import QtCore
            def again():
                d = App.listDocuments().get(name)
                if d is not None:
                    _reopened(d, tries - 1)
            QtCore.QTimer.singleShot(250, again)
        return
    show_tips_only(doc)


def register():
    if not _HOOKED:
        try:
            from . import restorehook          # FreeCAD 1.1 sends no slotFinishRestoreDocument
            restorehook.on_restored(_reopened)
            _HOOKED.append(True)
        except Exception as _fw_err:
            _fw_log("wemember.py:register", _fw_err)
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
        Gui.addCommand(WELDMENT_COMMAND, WeldmentCommand())
