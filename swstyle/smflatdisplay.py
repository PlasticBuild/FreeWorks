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
import Part

PAGE = "Sheet Metal"
MBD = "Sheet Metal MBD"
GROUP = "Flat-Pattern"
HEM_ANGLE = 179.0       # a bend of 180° is a hem

_records = {}            # flat pattern name -> [(edge midpoints, "up"/"down", angle deg, inner radius)]


def _opt(doc, page, text, default):
    try:
        from . import optionspages
        return optionspages.doc_value(doc, page, text, default)
    except Exception:
        return default


def _rgb(text, default=(0.0, 0.0, 0.0)):
    try:
        t = text.lstrip("#")
        return tuple(int(t[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return default


# ------------------------------------------------------------------ unfold with each bend's direction
def _bundled_unfolder():
    """smcore's SheetMetalUnfolder (with FreeCAD's own fixes), loaded beside the SheetMetal add-on's when that
    add-on is the engine; None when smcore is already the engine (or is missing)."""
    if "m" not in _BUNDLED:
        mod = None
        try:
            import importlib.util
            import os
            import SheetMetalUnfolder
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "smcore",
                                "SheetMetalUnfolder.py")
            if os.path.isfile(path) and os.path.normcase(os.path.abspath(SheetMetalUnfolder.__file__)) != \
                    os.path.normcase(os.path.abspath(path)):
                spec = importlib.util.spec_from_file_location("fw_smcore_unfolder", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
        except Exception as _fw_err:
            _fw_log("smflatdisplay.bundled", _fw_err)
            mod = None
        _BUNDLED["m"] = mod
    return _BUNDLED["m"]


_BUNDLED = {}


def _unfold_with(module, k_lookup, tip, face, standard):
    tree = module.SheetTree
    original = tree.generateBendShell2
    made = []

    def recording(self, node):
        shell, wires = original(self, node)
        made.append((list(wires or []), node.bend_dir, math.degrees(abs(node.bend_angle or 0.0)),
                     node.innerRadius or 0.0))
        return shell, wires
    tree.generateBendShell2 = recording
    import SheetMetalUnfolder
    kept = None
    if module is not SheetMetalUnfolder:
        # the custom bend allowances smflatten puts on the engine's nodes apply to this one too
        kept = module.Simple_node.__dict__.get("k_Factor")
        module.Simple_node.k_Factor = SheetMetalUnfolder.Simple_node.__dict__.get("k_Factor", kept)
    try:
        result = module.getUnfold(k_lookup, tip, face, standard)
    finally:
        tree.generateBendShell2 = original
        if kept is not None:
            module.Simple_node.k_Factor = kept
    return result, made


def unfold(name, k_lookup, tip, face, standard):
    """SheetMetalUnfolder.getUnfold, also noting which way each bend goes (its fold lines, its angle).
    When the SheetMetal add-on's unfolder fails, the bundled one (smcore) tries again: it also
    finds a wall's other side when a flange or hem ending flush splits that face (features-398)."""
    import SheetMetalUnfolder
    try:
        result, made = _unfold_with(SheetMetalUnfolder, k_lookup, tip, face, standard)
        failed = result is None or result[0] is None
        error = None
    except Exception as e:
        failed, error, result, made = True, e, None, []
    if failed:
        bundled = _bundled_unfolder()
        if bundled is not None:
            try:
                again, made2 = _unfold_with(bundled, k_lookup, tip, face, standard)
                if again is not None and again[0] is not None:
                    result, made = again, made2
                    error = None
            except Exception as _fw_err:
                _fw_log("smflatdisplay.unfold.bundled", _fw_err)
        if error is not None:
            raise error
    rows = []
    for wires, way, angle, radius in made:       # the wires were moved into the flat in place
        mids = []
        for w in wires:
            for e in getattr(w, "Edges", []):
                mids.append(e.valueAt(0.5 * (e.FirstParameter + e.LastParameter)))
        rows.append((mids, way or "up", angle, radius))
    _records[name] = rows
    return result


def bend_of(fp, edge):
    """(way, angle, radius) of the bend a bend line belongs to, or None."""
    p = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    best, gap = None, 1e-3
    for mids, way, angle, radius in _records.get(fp.Name, []):
        for m in mids:
            d = (m - p).Length
            if d < gap:
                best, gap = (way, angle, radius), d
    return best


# ------------------------------------------------------------------ apply the Document Properties
def apply(fp):
    if not App.GuiUp or fp is None:
        return
    doc = fp.Document
    if not getattr(fp, "SWFlattened", False):
        hide(fp)
        return
    try:
        _colors(fp, doc)
        _notes(fp, doc)
        _fixed_face(fp, doc)
        _grain(fp, doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: flat pattern display: %s\n" % error)


def _colors(fp, doc):
    up = _rgb(_opt(doc, PAGE, "Bend Lines - Up Direction", "#0000FF"))
    down = _rgb(_opt(doc, PAGE, "Bend Lines - Down Direction", "#FF0000"))
    hem = _rgb(_opt(doc, PAGE, "Bend Lines - Hems", "#00FF00"))
    lines = getattr(fp, "BendLines", None)
    if lines is not None and lines.ViewObject is not None:
        cols = []
        for e in lines.Shape.Edges:
            b = bend_of(fp, e)
            if b is None:
                cols.append(up)
            elif b[1] >= HEM_ANGLE:
                cols.append(hem)
            else:
                cols.append(down if b[0] == "down" else up)
        vo = lines.ViewObject
        vo.LineColor = cols[0] if cols else up
        if cols and "LineColorArray" in vo.PropertiesList:
            vo.LineColorArray = cols
    edges = _rgb(_opt(doc, PAGE, "Model Edges", "#000000"))
    if fp.ViewObject is not None:
        fp.ViewObject.LineColor = edges
        forms = _form_edges(fp)
        if forms and "LineColorArray" in fp.ViewObject.PropertiesList:
            form = _rgb(_opt(doc, PAGE, "Form Features", "#808080"))
            fp.ViewObject.LineColorArray = [form if i in forms else edges for i in range(len(fp.Shape.Edges))]
    box = getattr(fp, "BoundingBox", None)
    if box is not None and box.ViewObject is not None:
        box.ViewObject.LineColor = _rgb(_opt(doc, PAGE, "Bounding Box", "#808080"))
    sketch = _rgb(_opt(doc, PAGE, "Flat Pattern Sketch Color", "#000000"))
    for obj in doc.Objects:
        if obj.TypeId == "Sketcher::SketchObject" and _on_flat(obj, fp) and obj.ViewObject is not None:
            obj.ViewObject.LineColor = sketch
            obj.ViewObject.PointColor = sketch


def _on_flat(sketch, fp):
    support = getattr(sketch, "AttachmentSupport", None) or getattr(sketch, "Support", None) or []
    try:
        return any(link[0] is fp for link in support)
    except Exception:
        return False


def _form_edges(fp):
    """Indices of the flat's edges inside a forming tool mark (rough: inside each form's box)."""
    boxes = []
    for obj in fp.Document.Objects:
        if "SWFormTool" in obj.PropertiesList or obj.Name.startswith(("FormingTool", "SMForm")):
            try:
                bb = obj.Shape.BoundBox
                if bb.isValid():
                    boxes.append(bb)
            except Exception as _fw_err:
                _fw_log("smflatdisplay.py:165", _fw_err)
    out = set()
    if not boxes:
        return out
    for i, e in enumerate(fp.Shape.Edges):
        c = e.BoundBox.Center
        if any(b.isInside(c) for b in boxes):
            out.add(i)
    return out


def _flat_normal(fp):
    face = None
    try:
        tip = fp.Body.Tip
        face = tip.Shape.getElement(fp.FixedFace) if fp.FixedFace else None
    except Exception:
        face = None
    n = face.normalAt(0, 0) if face is not None else App.Vector(0, 0, 1)
    return n, face


def _child(fp, name, label):
    obj = fp.Document.getObject(getattr(fp, name, None).Name) if getattr(fp, name, None) is not None else None
    if obj is None:
        if name not in fp.PropertiesList:
            fp.addProperty("App::PropertyLink", name, GROUP, label)
            fp.setEditorMode(name, 1)
        obj = fp.Document.addObject("App::Annotation" if name == "BendNotes" else "Part::Feature", name)
        obj.Label = label
        setattr(fp, name, obj)
    return obj


def note_text(doc, way, angle, radius):
    arrow = _opt(doc, MBD, "Bend direction", "Up/Down") == "Arrow"
    parts = [("↑" if way == "up" else "↓") if arrow else way.upper()]
    if _opt(doc, MBD, "Bend angle", True):
        parts.append("%g°" % round(angle, 2))
    if _opt(doc, MBD, "Inner radius", True):
        parts.append("R %g" % round(radius, 2))
    return "  ".join(parts)


def notes(fp):
    """[(text, position, leader end or None)] for each bend, as the options place them."""
    doc = fp.Document
    if not _opt(doc, PAGE, "Display sheet metal bend notes", True) or \
            _opt(doc, MBD, "Bend line notes", "Show") == "Hide":
        return []
    style = _opt(doc, PAGE, "Bend note style", "Above Bend Line")
    n, _face = _flat_normal(fp)
    lines = getattr(fp, "BendLines", None)
    out, seen = [], []
    for e in (lines.Shape.Edges if lines is not None else []):
        b = bend_of(fp, e)
        if b is None or not hasattr(e.Curve, "Direction"):
            continue
        mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        if any((mid - s).Length < 2 * b[2] + 5 for s in seen):
            continue                                      # one note per bend (its two lines)
        seen.append(mid)
        side = n.cross(e.Curve.Direction)
        side = side.normalize() if side.Length > 1e-9 else App.Vector(0, 1, 0)
        text = note_text(doc, *b)
        if style == "Inline":
            out.append((text, mid, None))
        elif style == "Below Bend Line":
            out.append((text, mid - side * 3, None))
        elif style == "With Leader":
            out.append((text, mid + side * 12, mid))
        else:
            out.append((text, mid + side * 3, None))
    return out


NOTE_INK = (0.1, 0.1, 0.1)
NOTE_INK_DARK = (0.82, 0.82, 0.82)  # off the part on a dark viewport, or on a dark face
_ink_hooked = False


def _lum(rgb):
    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(c)) for c in tuple(rgb)[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ground(fp, at):
    """The colour under a note: the flat face's when the note sits on the part, else None."""
    try:
        if fp is None or at is None or fp.ViewObject is None:
            return None
        shape = fp.Shape
        if shape.isNull():
            return None
        box = shape.BoundBox
        box.enlarge(0.5)
        if not box.isInside(at):
            return None
        try:
            if shape.Faces and min(f.distToShape(Part.Vertex(at))[0] for f in shape.Faces) > 0.5:
                return None         # inside the box but over a cut-out
        except Exception:
            pass                    # OCC could not measure: the box says it is on the part
        vo = fp.ViewObject
        if "ShapeAppearance" in vo.PropertiesList and vo.ShapeAppearance:
            return tuple(vo.ShapeAppearance[0].DiffuseColor)[:3]
        return tuple(vo.ShapeColor)[:3]
    except Exception as _fw_err:
        _fw_log("smflatdisplay.py:ground", _fw_err)
        return None


def note_ink(fp=None, at=None):
    ""


    try:
        ground = _ground(fp, at)
        if ground is not None:
            return NOTE_INK if _lum(ground) > 0.18 else NOTE_INK_DARK
        from . import style
        return NOTE_INK_DARK if style.viewport_dark() else NOTE_INK
    except Exception as _fw_err:
        _fw_log("smflatdisplay.py:note_ink_pick", _fw_err)
        return NOTE_INK


def _reink(*_args):
    """Theme or scene switched: every bend note takes the ink for what it stands on."""
    for doc in App.listDocuments().values():
        for o in doc.Objects:
            try:
                vo = o.ViewObject if "SWBendNoteOf" in o.PropertiesList else None
                ink = note_ink(doc.getObject(o.SWBendNoteOf), o.Position) if vo is not None else None
                if vo is not None and "TextColor" in vo.PropertiesList and tuple(vo.TextColor)[:3] != ink:
                    vo.TextColor = ink
            except Exception as _fw_err:
                _fw_log("smflatdisplay.py:reink", _fw_err)


def _hook_ink():
    global _ink_hooked
    if _ink_hooked:
        return
    try:
        from . import style
        style.signals.theme_changed.connect(_reink)
        _ink_hooked = True
    except Exception as _fw_err:
        _fw_log("smflatdisplay.py:hook_ink", _fw_err)


def _notes(fp, doc):
    rows = notes(fp)
    old = [o for o in doc.Objects if getattr(o, "SWBendNoteOf", "") == fp.Name]
    for o in old[len(rows):]:
        doc.removeObject(o.Name)
    old = old[:len(rows)]
    for k, (text, at, leader) in enumerate(rows):
        if k < len(old):
            a = old[k]
        else:
            a = doc.addObject("App::Annotation", "BendNote")
            a.addProperty("App::PropertyString", "SWBendNoteOf", GROUP, "Flat-Pattern of this bend note")
            a.SWBendNoteOf = fp.Name
            a.addProperty("App::PropertyVector", "SWLeaderTo", GROUP, "Leader end (With Leader)")
        a.LabelText = [text]
        a.Position = at
        a.SWLeaderTo = leader if leader is not None else at
        a.Label = "Bend Note%d" % (k + 1)
        if a.ViewObject is not None:
            a.ViewObject.Visibility = fp.ViewObject.Visibility if fp.ViewObject is not None else True
            try:

                _hook_ink()
                ink = note_ink(fp, at)
                if "TextColor" in a.ViewObject.PropertiesList and tuple(a.ViewObject.TextColor)[:3] != ink:
                    a.ViewObject.TextColor = ink
            except Exception as _fw_err:
                _fw_log("smflatdisplay.py:note_ink", _fw_err)
        a.purgeTouched()


def _fixed_face(fp, doc):
    vo = fp.ViewObject
    if vo is None or "ShapeAppearance" not in vo.PropertiesList:
        return
    show = _opt(doc, PAGE, "Show fixed face", False)
    n, face = _flat_normal(fp)
    base = vo.ShapeAppearance[0] if vo.ShapeAppearance else App.Material()
    mats = []
    hit = None
    if show and face is not None:
        c = face.CenterOfMass
        best = 1e9
        for i, f in enumerate(fp.Shape.Faces):
            if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(n)) - 1) < 1e-6:
                d = f.distToShape(Part.Vertex(c))[0]
                if d < best:
                    best, hit = d, i
    for i in range(len(fp.Shape.Faces)):
        m = App.Material()
        src = base
        for attr in ("DiffuseColor", "AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
            setattr(m, attr, getattr(src, attr))
        if i == hit:
            m.DiffuseColor = (0.2, 0.8, 0.2)
        mats.append(m)
    if mats:
        vo.ShapeAppearance = mats
    fp.addProperty("App::PropertyInteger", "SWFixedFaceShown", GROUP, "Face shown as fixed") \
        if "SWFixedFaceShown" not in fp.PropertiesList else None
    fp.setEditorMode("SWFixedFaceShown", 2)
    fp.SWFixedFaceShown = -1 if hit is None else hit + 1


def _grain(fp, doc):
    show = _opt(doc, PAGE, "Show grain direction", False)
    have = getattr(fp, "GrainArrow", None) if "GrainArrow" in fp.PropertiesList else None
    if not show:
        if have is not None and have.ViewObject is not None:
            have.ViewObject.Visibility = False
        return
    arrow = _child(fp, "GrainArrow", "Grain Direction")
    try:
        from . import smflatpm
        g = smflatpm.grain(fp)
    except Exception:
        g = None
    d = App.Vector(1, 0, 0)
    if g is not None:
        try:
            d = g if isinstance(g, App.Vector) else App.Vector(*g)
        except Exception as _fw_err:
            _fw_log("smflatdisplay.py:315", _fw_err)
    if d.Length < 1e-9:
        d = App.Vector(1, 0, 0)
    d.normalize()
    bb = fp.Shape.BoundBox
    c = bb.Center
    n, _f = _flat_normal(fp)
    c = c + n * (bb.ZLength / 2 + 0.01) if abs(n.z) > 0.5 else c
    size = max(10.0, 0.3 * max(bb.XLength, bb.YLength))
    tip = c + d * size / 2
    side = n.cross(d)
    side = side.normalize() if side.Length > 1e-9 else App.Vector(0, 1, 0)
    head = size * 0.12
    edges = [Part.makeLine(c - d * size / 2, tip),
             Part.makeLine(tip, tip - d * head + side * head * 0.6),
             Part.makeLine(tip, tip - d * head - side * head * 0.6)]
    arrow.Shape = Part.makeCompound(edges)
    if arrow.ViewObject is not None:
        arrow.ViewObject.LineColor = (0.1, 0.5, 0.1)
        arrow.ViewObject.LineWidth = 2.0
        arrow.ViewObject.Visibility = True
    arrow.purgeTouched()


def refresh(doc=None):
    """After Document Properties change: every Flat-Pattern shown flat takes the new display."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return
    names = [o.Name for o in doc.Objects if "SWFlattened" in o.PropertiesList and "Body" in o.PropertiesList]
    for name in names:
        obj = doc.getObject(name)
        if obj is not None:
            apply(obj)


def hide(fp):
    """Folded: the bend notes and the grain arrow go with the flat."""
    for o in fp.Document.Objects:
        if getattr(o, "SWBendNoteOf", "") == fp.Name and o.ViewObject is not None:
            o.ViewObject.Visibility = False
    arrow = getattr(fp, "GrainArrow", None) if "GrainArrow" in fp.PropertiesList else None
    if arrow is not None and arrow.ViewObject is not None:
        arrow.ViewObject.Visibility = False
