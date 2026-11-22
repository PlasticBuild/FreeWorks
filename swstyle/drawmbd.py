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


import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import pmboxes
except ImportError:
    Gui = None

V = App.Vector
TOLERANCE_KINDS = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Datum", "DatumTarget", "GTol",
                   "Pattern", "Reference")
HATCHES = {"ANSI31 (Iron, brick, stone)": (0.55, 0.55, 0.62), "ANSI32 (Steel)": (0.5, 0.55, 0.65),
           "ANSI33 (Bronze, brass, copper)": (0.7, 0.55, 0.35), "ANSI37 (Lead, zinc)": (0.6, 0.6, 0.6),
           "Solid": (0.3, 0.3, 0.3)}


def _mbd():
    from . import mbd
    return mbd


# --------------------------------------------------------------------------- where we are
def is_drawing(doc):
    return doc is not None and any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)


def is_assembly(doc):
    return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


def model_doc():
    """The part or assembly whose 3D window is the active window, else None."""
    if Gui is None:
        return None
    doc = App.ActiveDocument
    if doc is None or is_drawing(doc) or Gui.ActiveDocument is None:
        return None
    try:
        view = Gui.ActiveDocument.ActiveView
    except Exception:
        return None
    if view is None or not hasattr(view, "getCameraNode"):
        return None
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow()
        if mdi is not None and mdi.widget() is not None and "MDIViewPage" in mdi.widget().metaObject().className():
            return None                      # a drawing sheet is the active window
    except Exception as _fw_err:
        _fw_log("drawmbd.py:75", _fw_err)
    return doc


def _used(o):
    """o feeds another feature (annotations and folders do not count)."""
    return any(getattr(i, "SWStyleKind", "") != "PMI" and i.TypeId not in ("App::DocumentObjectGroup", "App::Link")
               and not i.isDerivedFrom("TechDraw::DrawView") for i in o.InList)


def solids(doc):
    out = []
    for o in doc.Objects:
        if o.TypeId == "PartDesign::Body" or (o.isDerivedFrom("Part::Feature") and o.getParentGeoFeatureGroup() is None
                                               and not _used(o)):
            s = getattr(o, "Shape", None)
            if s is not None and not s.isNull() and s.Solids:
                out.append(o)
    return out


def model_box(doc):
    import Part
    box = App.BoundBox()
    for o in doc.Objects:
        if o.getParentGeoFeatureGroup() is not None or not o.ViewObject or not getattr(o, "Visibility", True):
            continue
        try:
            s = Part.getShape(o)
        except Exception as _fw_err:
            _fw_log("drawmbd.py:106", _fw_err)
            continue
        if not s.isNull() and s.Solids:
            box.add(s.BoundBox)
    return box if box.isValid() else App.BoundBox(-10, -10, -10, 10, 10, 10)


def has_model(doc):
    return doc is not None and (bool(solids(doc)) or is_assembly(doc))


# --------------------------------------------------------------------------- picks
def picks():
    """[(object, element, global point)] of the picked faces / edges / vertices. In a part the object
    is the body (or loose solid) the element is on; in an assembly it is the top object of the path."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        pts = list(sel.PickedPoints or [])
        for i, sub in enumerate(sel.SubElementNames):
            path = sub.split(".")
            holder = sel.Object
            for part in path[:-1]:
                child = sel.Object.Document.getObject(part)
                if child is not None and hasattr(child, "Shape") and child.TypeId != "App::Link":
                    holder = child
            if holder.TypeId.startswith("PartDesign::") and holder.TypeId != "PartDesign::Body":
                holder = holder.getParentGeoFeatureGroup() or holder
            pt = pts[i] if i < len(pts) else None
            if pt is None:
                try:
                    import Part
                    el = Part.getShape(sel.Object, sub, needSubElement=True)
                    pt = el.CenterOfMass if hasattr(el, "CenterOfMass") else el.Point
                except Exception:
                    pt = V()
            out.append((holder, path[-1], V(pt), sel.Object, sub))
    return out


def _direct(doc, pick):
    """The (object, element) a PMI can reference, or None (assembly components are kept by point)."""
    holder, el, _pt, _top, _sub = pick
    if is_assembly(doc) or not el:
        return None
    try:
        holder.Shape.getElement(el)
    except Exception as _fw_err:
        _fw_log("drawmbd.py:153", _fw_err)
        return None
    return (holder, el)


def component_of(doc, pick):
    """The assembly component a pick is on (the first link/part of its path)."""
    _h, _el, _pt, top, sub = pick
    first = sub.split(".")[0] if "." in sub else ""
    if top.TypeId == "Assembly::AssemblyObject" and first:
        return doc.getObject(first)
    return top


# --------------------------------------------------------------------------- leaders by point
if Gui is not None:
    from . import mbd as _m

    class AnchoredView(_m.PMIView):
        """mbd's PMI view, with the leader going to SWAnchor (a point on an assembly component), or no
        leader at all (SWNoLeader: tables, General Profile Tolerance, a note without a leader)."""

        def updateData(self, obj, prop):
            super().updateData(obj, prop)
            self._lead(obj)

        def restyle(self, obj):
            super().restyle(obj)
            self._lead(obj)

        def _lead(self, obj):
            if not hasattr(self, "coords"):
                return
            tp = V(obj.TextPosition)
            if bool(getattr(obj, "SWNoLeader", False)):
                self.coords.point.setValues(0, 2, [tuple(tp), tuple(tp)])
                self.arrow.removeAllChildren()
                return
            if "SWAnchor" in obj.PropertiesList:
                a = V(obj.SWAnchor)
                self.coords.point.setValues(0, 2, [tuple(a), tuple(tp)])
                try:
                    self._arrow(obj, a, tp)
                except Exception as _fw_err:
                    _fw_log("drawmbd.py:194", _fw_err)


def _unique(doc, base):
    used = {o.Label for o in doc.Objects}
    n = 1
    while "%s%d" % (base, n) in used:
        n += 1
    return "%s%d" % (base, n)


def text_spot(doc, at, gap=12.0):
    """Where a text goes: off the model, away from its centre, past other annotations."""
    box = model_box(doc)
    c = box.Center
    d = V(at) - c
    if d.Length < 1e-6:
        d = V(1, 1, 1)
    d.normalize()
    reach = 0.0
    for x in (box.XMin, box.XMax):
        for y in (box.YMin, box.YMax):
            for z in (box.ZMin, box.ZMax):
                reach = max(reach, (V(x, y, z) - V(at)).dot(d))
    pos = V(at) + d * (reach + gap)
    others = [V(o.TextPosition) for o in doc.Objects if _mbd().is_pmi(o)]
    for _i in range(20):
        if all((p - pos).Length >= 5.0 for p in others):
            break
        pos = pos + d * 8.0
    return pos


def annotate(doc, kind, pick_list, text, what, value=0.0, plus=0.0, minus=0.0, leader=True, position=None):
    """A PMI annotation: on the picked part element when it can reference it, else on the picked point."""
    m = _mbd()
    refs = []
    for p in pick_list:
        r = _direct(doc, p)
        if r is not None:
            refs.append(r)
    anchor = pick_list[0][2] if pick_list else None
    if position is None:
        position = None if refs and leader else text_spot(doc, anchor if anchor is not None else model_box(doc).Center)
    obj = m.make(doc, kind, refs, text, value, plus, minus, position)
    obj.addProperty("App::PropertyString", "SWAnnotation3D", "PMI", "What made it: Note, Balloon, Table...")
    obj.SWAnnotation3D = what
    obj.setEditorMode("SWAnnotation3D", 1)
    if not leader or not pick_list:
        obj.addProperty("App::PropertyBool", "SWNoLeader", "PMI", "Shown without a leader")
        obj.SWNoLeader = True
    elif not refs and anchor is not None:
        obj.addProperty("App::PropertyVector", "SWAnchor", "PMI", "The point on the model the leader goes to")
        obj.SWAnchor = anchor
    if what not in ("Note", "Datum", "DatumTarget", "GTol", "SurfaceFinish", "Weld"):
        obj.Label = _unique(doc, what.replace(" ", ""))
    _anchored(obj)
    doc.recompute()
    return obj


def _anchored(obj):
    """mbd.make gave it mbd's view; this one draws the leader to SWAnchor, or none."""
    if App.GuiUp and obj.ViewObject is not None and obj.ViewObject.Proxy is not None:
        obj.ViewObject.Proxy.__class__ = AnchoredView
        obj.ViewObject.Proxy.updateData(obj, "Text")


# --------------------------------------------------------------------------- the annotations
def note(doc, pick_list, text, leader=True):
    try:
        from . import docstyle
        text = docstyle.note_text(doc, text)
    except Exception as _fw_err:
        _fw_log("drawmbd.py:268", _fw_err)
    return annotate(doc, "Note", pick_list[:1], text or "NOTE", "Note", leader=leader and bool(pick_list))


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def balloon_text(n):
    return CIRCLED[n - 1] if 1 <= n <= len(CIRCLED) else "(%d)" % n


def item_number(doc, pick):
    """The component's item number: its place among the assembly's distinct parts, in tree order
    (the BOM order); 1 in a part."""
    if not is_assembly(doc):
        return 1
    from . import asmcore
    asm = asmcore.assembly_of(doc)
    comp = component_of(doc, pick)
    seen = []
    for c in asmcore.components(asm):
        src = getattr(c, "LinkedObject", None) or c
        key = (getattr(src, "Document", doc).Name, src.Name)
        if key not in seen:
            seen.append(key)
        if c is comp:
            return seen.index(key) + 1
    return len(seen) + 1


def balloon(doc, pick, text=None):
    n = item_number(doc, pick)
    obj = annotate(doc, "Note", [pick], text or balloon_text(n), "Balloon", value=n)
    return obj


def stacked_balloon(doc, pick_list):
    nums = []
    for p in pick_list:
        n = item_number(doc, p)
        if n not in nums:
            nums.append(n)
    return annotate(doc, "Note", pick_list[:1], "\n".join(balloon_text(n) for n in nums), "Stacked Balloon",
                    value=nums[0] if nums else 0)


def surface_finish(doc, pick, symbol="Machining required", roughness="3.2"):
    from . import mbdtab
    text = "%s Ra %s" % (mbdtab.SURFACE.get(symbol, "√"), roughness)
    return annotate(doc, "SurfaceFinish", [pick], text, "SurfaceFinish")


def weld_symbol(doc, pick, kind="Fillet", size="5", both=False, all_around=False, field=False):
    from . import mbdtab
    sym = mbdtab.WELDS.get(kind, kind)
    text = "%s%s %s" % ("○" if all_around else "", sym + ("/" + sym if both else ""), size)
    if field:
        text = "⚑" + text
    return annotate(doc, "Weld", [pick], text, "Weld")


def gtol_text(symbol, value, datums, diameter=False, material="None"):
    m = _mbd()
    parts = [m.GTOL_SYMBOLS.get(symbol, symbol), ("⌀" if diameter else "") + "%g" % value +
             m.MATERIAL.get(material, "")] + [d for d in datums if d]
    return "|" + "|".join(parts) + "|"


def geometric_tolerance(doc, pick, symbol="Position", value=None, datums=("A", "B", "C"), material="None"):
    m = _mbd()
    value = m.default_gtol(doc, symbol) if value is None else value
    r = _direct(doc, pick)
    if r is not None:
        return m.gtol(doc, r[0], r[1], symbol, value, datums, None, material)
    return annotate(doc, "GTol", [pick], gtol_text(symbol, value, datums, False, material), "GTol", value, value, 0)


def datum_feature(doc, pick, letter=None):
    m = _mbd()
    letter = letter or m.next_letter(doc)
    r = _direct(doc, pick)
    if r is not None:
        return m.datum(doc, r[0], r[1], letter)
    obj = annotate(doc, "Datum", [pick], letter, "Datum")
    obj.Label = "Datum %s" % letter
    return obj


def datum_target(doc, pick, target=None):
    m = _mbd()
    target = target or (m.next_letter(doc) + "1")
    r = _direct(doc, pick)
    if r is not None:
        return m.datum_target(doc, r[0], r[1], target)
    obj = annotate(doc, "DatumTarget", [pick], target, "DatumTarget")
    obj.Label = "Datum Target %s" % target
    return obj


def _material_copy(m):
    out = App.Material()
    if m is not None:
        for prop in ("AmbientColor", "DiffuseColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
            try:
                setattr(out, prop, getattr(m, prop))
            except Exception as _fw_err:
                _fw_log("drawmbd.py:374", _fw_err)
    return out


def area_hatch(doc, pick_list, pattern="ANSI31 (Iron, brick, stone)", scale=1.0, angle=0.0):
    """Area Hatch/Fill on model faces: the faces take the hatch's colour and a hatch annotation names
    the pattern, scale and angle."""
    colour = HATCHES.get(pattern, (0.55, 0.55, 0.62))
    for holder, el, _pt, _top, _sub in pick_list:
        if not el.startswith("Face") or is_assembly(doc):
            continue
        try:
            vo = holder.ViewObject
            n = len(holder.Shape.Faces)
            if hasattr(vo, "ShapeAppearance") and not hasattr(vo, "DiffuseColor"):
                # FreeCAD 1.1: per-face colours are the materials of ShapeAppearance (DiffuseColor is gone)
                base = list(vo.ShapeAppearance)
                mats = [_material_copy(base[j] if len(base) == n else (base[0] if base else None)) for j in range(n)]
                mats[int(el[4:]) - 1].DiffuseColor = colour + (0.0,)
                vo.ShapeAppearance = mats
                continue
            cols = list(getattr(vo, "DiffuseColor", []) or [])
            if len(cols) != n:
                cols = [cols[0] if cols else tuple(vo.ShapeColor)] * n
            cols[int(el[4:]) - 1] = colour + (0.0,)
            vo.DiffuseColor = cols
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Area Hatch colour: %s\n" % error)
    text = "%s  SCALE %g  ANGLE %g°" % (pattern.split(" ")[0], scale, angle)
    obj = annotate(doc, "Note", pick_list[:1], text, "AreaHatch", leader=True)
    obj.addProperty("App::PropertyStringList", "SWHatchFaces", "PMI", "The faces it fills")
    obj.SWHatchFaces = ["%s.%s" % (p[0].Name, p[1]) for p in pick_list]
    return obj


def location_label(doc, view_name):
    return annotate(doc, "Note", [], "SEE VIEW %s" % view_name.upper(), "LocationLabel", leader=False)


# --------------------------------------------------------------------------- tables
def grid_text(rows):
    widths = [max(len(str(r[c])) if c < len(r) else 0 for r in rows) for c in range(max(len(r) for r in rows))]
    out = []
    for r in rows:
        out.append("| " + " | ".join(str(r[c] if c < len(r) else "").ljust(widths[c]) for c in range(len(widths))) + " |")
    return "\n".join(out)


def _sheet(doc, base, rows):
    s = doc.addObject("Spreadsheet::Sheet", "Table")
    s.Label = _unique(doc, base + "Data")
    for r, row in enumerate(rows, 1):
        for c, value in enumerate(row):
            if str(value).strip():
                s.set("%s%d" % (chr(ord("A") + c), r), "'" + str(value))
    doc.recompute()
    return s


def table(doc, what, rows, at=None):
    """A 3D table annotation: its cells in a spreadsheet (double-click it to edit; Update Table
    redraws), shown in the model as a grid without a leader."""
    s = _sheet(doc, what.replace(" ", ""), rows)
    pos = at if at is not None else text_spot(doc, model_box(doc).Center + V(0, 0, model_box(doc).ZLength))
    obj = annotate(doc, "Note", [], grid_text(rows), what.replace(" ", ""), leader=False, position=pos)
    obj.addProperty("App::PropertyLink", "SWTableSheet", "PMI", "The table's cells")
    obj.SWTableSheet = s
    _mbd()._folder(doc).addObject(s)
    return obj


def sheet_rows(sheet):
    rows = []
    r = 1
    while True:
        row = []
        for c in range(26):
            cell = "%s%d" % (chr(ord("A") + c), r)
            try:
                v = sheet.getContents(cell)
            except Exception:
                v = ""
            row.append(str(v).lstrip("'="))
        while row and row[-1] == "":
            row.pop()
        if not row:
            break
        rows.append(row)
        r += 1
    return rows


def update_table(obj):
    s = getattr(obj, "SWTableSheet", None)
    if s is None:
        return False
    rows = sheet_rows(s)
    if rows:
        obj.Text = grid_text(rows)
        obj.AutoText = obj.Text
    return True


def general_table(doc, columns=2, rows=2):
    return table(doc, "General Table", [[" " for _c in range(columns)] for _r in range(rows)])


def hole_rows(doc, obj, origin=None):
    m = _mbd()
    shape = obj.Shape
    seen = []
    for f in shape.Faces:
        if f.Surface.TypeId != "Part::GeomCylinder" or not m._is_hole(shape, f):
            continue
        c = f.Surface.Center + f.Surface.Axis * (f.CenterOfMass - f.Surface.Center).dot(f.Surface.Axis)
        if any((c - s[0]).Length < 1e-3 and abs(f.Surface.Radius - s[1]) < 1e-6 for s in seen):
            continue
        seen.append((c, f.Surface.Radius))
    o = origin if origin is not None else V(shape.BoundBox.XMin, shape.BoundBox.YMin, shape.BoundBox.ZMin)
    sizes = sorted({round(r * 2, 3) for _c, r in seen})
    rows = [["TAG", "X LOC", "Y LOC", "SIZE"]]
    for i, (c, r) in enumerate(sorted(seen, key=lambda s: (sizes.index(round(s[1] * 2, 3)), s[0].x, s[0].y))):
        letter = chr(ord("A") + sizes.index(round(r * 2, 3)))
        n = sum(1 for row in rows[1:] if row[0].startswith(letter)) + 1
        rows.append(["%s%d" % (letter, n), "%.2f" % (c.x - o.x), "%.2f" % (c.y - o.y), "⌀%g" % (2 * r)])
    return rows


def hole_table(doc, obj, origin=None):
    return table(doc, "Hole Table", hole_rows(doc, obj, origin))


def title_block_rows(doc):
    return [["Title", doc.Label], ["Part number", doc.Name], ["Created by", doc.CreatedBy or ""],
            ["Company", doc.Company or ""], ["Date", (doc.CreationDate or "")[:10]],
            ["Revision", getattr(doc, "Id", "") or "A"], ["Comment", doc.Comment or ""]]


def title_block_table(doc):
    return table(doc, "Title Block Table", title_block_rows(doc))


# --------------------------------------------------------------------------- MBD tolerance commands
def general_profile_tolerance(doc, value=0.5, datums=("A", "B", "C")):
    """General Profile Tolerance: a profile of a surface frame that covers every face of the part with
    no tolerance of its own, as a note without a leader ("UNLESS OTHERWISE SPECIFIED")."""
    m = _mbd()
    covered = set()
    for o in doc.Objects:
        if m.is_pmi(o) and o.Kind in TOLERANCE_KINDS and not bool(getattr(o, "SWGeneralProfile", False)):
            for r, subs in o.References or []:
                for s in subs or []:
                    covered.add((r.Name, s.split(".")[-1]))
    refs = []
    for body in solids(doc):
        for i in range(len(body.Shape.Faces)):
            if (body.Name, "Face%d" % (i + 1)) not in covered:
                refs.append((body, "Face%d" % (i + 1)))
    text = "UNLESS OTHERWISE SPECIFIED\n" + gtol_text("Profile of a Surface", value, datums)
    box = model_box(doc)
    obj = m.make(doc, "GTol", refs, text, value, value, 0, V(box.XMax, box.YMax, box.ZMax) + V(10, 10, 10))
    obj.addProperty("App::PropertyBool", "SWNoLeader", "PMI", "")
    obj.SWNoLeader = True
    obj.addProperty("App::PropertyBool", "SWGeneralProfile", "PMI", "A General Profile Tolerance")
    obj.SWGeneralProfile = True
    obj.Label = _unique(doc, "GeneralProfileTolerance")
    _anchored(obj)
    doc.recompute()
    return obj


def tolerances(doc):
    m = _mbd()
    return [o for o in doc.Objects if m.is_pmi(o) and o.Kind in TOLERANCE_KINDS]


def delete_all_tolerances(doc):
    """Delete All Tolerances: every dimension, datum and tolerance of the MBD scheme (notes, balloons,
    surface finish and weld symbols stay)."""
    names = [o.Name for o in tolerances(doc)]
    for n in names:
        if doc.getObject(n) is not None:
            doc.removeObject(n)
    doc.recompute()
    return len(names)


def import_scheme(doc, path, target=None):
    """Import Scheme: the MBD scheme of another part file put on this part, face for face (the same
    face numbers), for a copy or a revision of the part."""
    m = _mbd()
    target = target or (solids(doc)[0] if solids(doc) else None)
    if target is None:
        return []
    had = {d.Name for d in App.listDocuments().values()}
    src = App.openDocument(path, hidden=True) if "hidden" in App.openDocument.__doc__ else App.openDocument(path)
    made = []
    try:
        n = len(target.Shape.Faces)
        for o in src.Objects:
            if not m.is_pmi(o):
                continue
            refs = []
            for r, subs in o.References or []:
                for s in subs or [""]:
                    el = s.split(".")[-1]
                    if el.startswith("Face") and int(el[4:]) <= n or el.startswith(("Edge", "Vertex")):
                        refs.append((target, el))
            c = m.make(doc, o.Kind, refs, o.Text, o.Value, o.Plus, o.Minus, V(o.TextPosition))
            made.append(c)
    finally:
        if src.Name not in had:
            App.closeDocument(src.Name)
    if App.ActiveDocument is not doc:
        App.setActiveDocument(doc.Name)
    m.restyle_all(doc)
    return made


# =========================================================================== GUI
if Gui is not None:
    NAMES = {
        "FreeWorks_DrawNote": "Note", "FreeWorks_DrawBalloon": "Balloon",
        "FreeWorks_DrawStackedBalloon": "Stacked Balloon", "FreeWorks_DrawSurfaceFinish": "Surface Finish",
        "FreeWorks_DrawWeldSymbol": "Weld Symbol", "FreeWorks_DrawGeometricTolerance": "Geometric Tolerance",
        "FreeWorks_DrawDatumFeature": "Datum Feature", "FreeWorks_DrawDatumTarget": "Datum Target",
        "FreeWorks_DrawAreaHatch": "Area Hatch/Fill", "FreeWorks_DrawLocationLabel": "Location Label",
        "FreeWorks_DrawGeneralTable": "General Table", "FreeWorks_DrawHoleTable": "Hole Table",
        "FreeWorks_DrawTitleBlockTable": "Title Block Table",
    }
    NEED = {"Note": 0, "Balloon": 1, "Stacked Balloon": 1, "Surface Finish": 1, "Weld Symbol": 1,
            "Geometric Tolerance": 1, "Datum Feature": 1, "Datum Target": 1, "Area Hatch/Fill": 1,
            "Location Label": 0, "General Table": 0, "Hole Table": 0, "Title Block Table": 0}
    HINTS = {"Note": "Type the note. Pick a face or edge for a leader, or none for a note without one.",
             "Balloon": "Pick a face of the component.", "Stacked Balloon": "Pick faces of the components to stack.",
             "Surface Finish": "Pick the face.", "Weld Symbol": "Pick the face or edge of the weld.",
             "Geometric Tolerance": "Pick the toleranced face.", "Datum Feature": "Pick the datum face.",
             "Datum Target": "Pick where the target is.", "Area Hatch/Fill": "Pick the faces to hatch.",
             "Location Label": "Pick the 3D view it points to.", "General Table": "Set the rows and columns.",
             "Hole Table": "Pick a vertex for the origin, or none for the corner of the part.",
             "Title Block Table": "The part's properties as a table."}

    def active(name):
        doc = model_doc()
        if doc is None:
            return False
        what = NAMES.get(name)
        if what is None:
            return False
        if what == "Hole Table":
            return bool(solids(doc))
        if what in ("Note", "Location Label", "General Table", "Title Block Table"):
            return True
        return has_model(doc)

    def run(name):
        ""

        doc = model_doc()
        if doc is None or name not in NAMES:
            return
        if Gui.Control.activeDialog():
            try:
                panel = Gui.Control.activeTaskDialog() if hasattr(Gui.Control, "activeTaskDialog") else None
                if panel is not None and hasattr(panel, "reject"):
                    panel.reject()
            except Exception as _fw_err:
                _fw_log("drawmbd.py:641", _fw_err)
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            try:
                from PySide import QtWidgets as _Q
                _Q.QApplication.processEvents()
            except Exception as _fw_err:
                _fw_log("drawmbd.py:648", _fw_err)
        if Gui.Control.activeDialog():
            App.Console.PrintWarning("FreeCAD: %s: close the open task first\n" % NAMES[name])
            return
        Gui.Control.showDialog(AnnotationPM(doc, NAMES[name]))

    class AnnotationPM:
        """The PropertyManager of a 3D annotation: the picks, the annotation's own boxes, OK makes it."""

        def __init__(self, doc, what):
            self.doc, self.what = doc, what
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWMBDAnnotationPM")
            self.form.setWindowTitle(what)
            self.form.setProperty("swstyle_pm_title", what)
            lay = QtWidgets.QFormLayout(self.form)
            self.hint = QtWidgets.QLabel(HINTS.get(what, ""))
            self.hint.setWordWrap(True)
            lay.addRow(self.hint)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWMBDPicks")
            self.list.setMaximumHeight(70)
            pmboxes.mark(self.list, True)
            if what not in ("General Table", "Title Block Table", "Location Label"):
                lay.addRow(self.list)
            self.w = {}
            self._boxes(lay)
            self.msg = QtWidgets.QLabel("")
            self.msg.setObjectName("SWMBDMessage")
            self.msg.setWordWrap(True)
            lay.addRow(self.msg)
            self.items = []
            for p in picks():
                self._add(p)
            Gui.Selection.addObserver(self)

        def _w(self, key, widget, label, lay):
            widget.setObjectName("SWMBD" + key)
            self.w[key] = widget
            lay.addRow(label, widget)
            return widget

        def _boxes(self, lay):
            m = _mbd()
            what = self.what
            if what == "Note":
                t = self._w("NoteText", QtWidgets.QPlainTextEdit(), "Text", lay)
                t.setMaximumHeight(80)
                c = self._w("Leader", QtWidgets.QCheckBox("Leader"), "", lay)
                c.setChecked(True)
            elif what in ("Balloon",):
                c = self._w("BalloonText", QtWidgets.QComboBox(), "Balloon text", lay)
                c.addItems(["Item Number", "Custom"])
                self._w("BalloonCustom", QtWidgets.QLineEdit(), "Custom text", lay)
            elif what == "Surface Finish":
                from . import mbdtab
                c = self._w("Symbol", QtWidgets.QComboBox(), "Symbol", lay)
                c.addItems(list(mbdtab.SURFACE))
                c.setCurrentText("Machining required")
                r = self._w("Roughness", QtWidgets.QLineEdit("3.2"), "Roughness Ra", lay)
            elif what == "Weld Symbol":
                from . import mbdtab
                c = self._w("WeldKind", QtWidgets.QComboBox(), "Weld symbol", lay)
                c.addItems(list(mbdtab.WELDS))
                self._w("WeldSize", QtWidgets.QLineEdit("5"), "Size", lay)
                self._w("BothSides", QtWidgets.QCheckBox("Both sides"), "", lay)
                self._w("AllAround", QtWidgets.QCheckBox("All around"), "", lay)
                self._w("FieldWeld", QtWidgets.QCheckBox("Field/Site"), "", lay)
            elif what == "Geometric Tolerance":
                c = self._w("GTolSymbol", QtWidgets.QComboBox(), "Symbol", lay)
                c.addItems(list(m.GTOL_SYMBOLS))
                v = self._w("GTolValue", QtWidgets.QDoubleSpinBox(), "Tolerance 1", lay)
                v.setDecimals(3)
                v.setRange(0, 100)
                v.setValue(float(m.default_gtol(self.doc)))
                self._w("GTolDatums", QtWidgets.QLineEdit("A B C"), "Datums", lay)
                mc = self._w("GTolMaterial", QtWidgets.QComboBox(), "Material condition", lay)
                mc.addItems(list(m.MATERIAL))
            elif what == "Datum Feature":
                self._w("Letter", QtWidgets.QLineEdit(m.next_letter(self.doc)), "Label", lay)
            elif what == "Datum Target":
                self._w("Letter", QtWidgets.QLineEdit(m.next_letter(self.doc) + "1"), "Target", lay)
            elif what == "Area Hatch/Fill":
                c = self._w("Pattern", QtWidgets.QComboBox(), "Pattern", lay)
                c.addItems(list(HATCHES))
                s = self._w("Scale", QtWidgets.QDoubleSpinBox(), "Scale", lay)
                s.setRange(0.01, 100)
                s.setValue(1.0)
                a = self._w("Angle", QtWidgets.QDoubleSpinBox(), "Angle", lay)
                a.setRange(-360, 360)
            elif what == "Location Label":
                from . import mbdtab
                c = self._w("View", QtWidgets.QComboBox(), "3D view", lay)
                names = [v.get("name", "") for v in mbdtab.views(self.doc)] if hasattr(mbdtab, "views") else []
                c.addItems([n for n in names if n] or ["Front", "Top", "Right", "Isometric"])
            elif what == "General Table":
                c = self._w("Columns", QtWidgets.QSpinBox(), "Columns", lay)
                c.setRange(1, 26)
                c.setValue(2)
                r = self._w("Rows", QtWidgets.QSpinBox(), "Rows", lay)
                r.setRange(1, 200)
                r.setValue(2)

        # selection
        def _add(self, p):
            key = (p[3].Name, p[4])
            if any((q[3].Name, q[4]) == key for q in self.items):
                return
            self.items.append(p)
            self.list.addItem("%s.%s" % (p[0].Label, p[1]) if p[1] else p[0].Label)

        def addSelection(self, doc, obj, sub, pnt):
            if doc != self.doc.Name or not sub:
                return
            o = self.doc.getObject(obj)
            path = sub.split(".")
            holder = o
            for part in path[:-1]:
                child = self.doc.getObject(part)
                if child is not None and hasattr(child, "Shape") and child.TypeId != "App::Link":
                    holder = child
            if holder.TypeId.startswith("PartDesign::") and holder.TypeId != "PartDesign::Body":
                holder = holder.getParentGeoFeatureGroup() or holder
            self._add((holder, path[-1], V(*pnt), o, sub))

        def removeSelection(self, *_a):
            pass

        def setSelection(self, *_a):
            pass

        def clearSelection(self, *_a):
            pass

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _bye(self):
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("drawmbd.py:789", _fw_err)

        def make(self):
            doc, what, w, p = self.doc, self.what, self.w, self.items
            if len(p) < NEED.get(what, 0):
                self.msg.setText(HINTS.get(what, "Pick an item."))
                return None
            if what == "Note":
                return note(doc, p, w["NoteText"].toPlainText().strip() or "NOTE", w["Leader"].isChecked())
            if what == "Balloon":
                custom = w["BalloonText"].currentText() == "Custom" and w["BalloonCustom"].text().strip()
                return balloon(doc, p[0], custom or None)
            if what == "Stacked Balloon":
                return stacked_balloon(doc, p)
            if what == "Surface Finish":
                return surface_finish(doc, p[0], w["Symbol"].currentText(), w["Roughness"].text().strip() or "3.2")
            if what == "Weld Symbol":
                return weld_symbol(doc, p[0], w["WeldKind"].currentText(), w["WeldSize"].text().strip(),
                                   w["BothSides"].isChecked(), w["AllAround"].isChecked(), w["FieldWeld"].isChecked())
            if what == "Geometric Tolerance":
                return geometric_tolerance(doc, p[0], w["GTolSymbol"].currentText(), w["GTolValue"].value(),
                                           tuple(w["GTolDatums"].text().split()), w["GTolMaterial"].currentText())
            if what == "Datum Feature":
                return datum_feature(doc, p[0], w["Letter"].text().strip().upper() or None)
            if what == "Datum Target":
                return datum_target(doc, p[0], w["Letter"].text().strip().upper() or None)
            if what == "Area Hatch/Fill":
                return area_hatch(doc, p, w["Pattern"].currentText(), w["Scale"].value(), w["Angle"].value())
            if what == "Location Label":
                return location_label(doc, w["View"].currentText())
            if what == "General Table":
                return general_table(doc, w["Columns"].value(), w["Rows"].value())
            if what == "Hole Table":
                body = p[0][0] if p and getattr(p[0][0], "Shape", None) is not None else solids(doc)[0]
                origin = p[0][2] if p and p[0][1].startswith("Vertex") else None
                return hole_table(doc, body, origin)
            if what == "Title Block Table":
                return title_block_table(doc)
            return None

        def accept(self):
            self.doc.openTransaction(self.what)
            try:
                obj = self.make()
            except Exception as error:
                self.doc.abortTransaction()
                self.msg.setText(str(error))
                App.Console.PrintWarning("FreeCAD: %s: %s\n" % (self.what, error))
                return False
            if obj is None:
                self.doc.abortTransaction()
                return False
            self.doc.commitTransaction()
            self._bye()
            Gui.Control.closeDialog()
            Gui.Selection.clearSelection()
            return True

        def reject(self):
            self._bye()
            Gui.Control.closeDialog()
            return True

    # ----------------------------------------------------------------- the three MBD commands
    class GeneralProfilePM:
        def __init__(self, doc):
            self.doc = doc
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWMBDGeneralProfilePM")
            self.form.setWindowTitle("General Profile Tolerance")
            self.form.setProperty("swstyle_pm_title", "General Profile Tolerance")
            lay = QtWidgets.QFormLayout(self.form)
            lay.addRow(QtWidgets.QLabel("Covers every face with no tolerance of its own."))
            self.value = QtWidgets.QDoubleSpinBox()
            self.value.setObjectName("SWMBDProfileValue")
            self.value.setDecimals(3)
            self.value.setRange(0.001, 100)
            self.value.setValue(float(_mbd().default_gtol(doc, "Profile of a Surface")))
            lay.addRow("Tolerance", self.value)
            self.datums = []
            used = sorted({o.Text for o in doc.Objects if _mbd().is_pmi(o) and o.Kind == "Datum"})
            for i, title in enumerate(("Primary", "Secondary", "Tertiary")):
                c = QtWidgets.QComboBox()
                c.setObjectName("SWMBDProfileDatum%d" % (i + 1))
                c.addItems([""] + (used or ["A", "B", "C"]))
                if i < len(used or "ABC"):
                    c.setCurrentIndex(i + 1)
                lay.addRow(title + " datum", c)
                self.datums.append(c)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            self.doc.openTransaction("General Profile Tolerance")
            try:
                general_profile_tolerance(self.doc, self.value.value(),
                                          tuple(c.currentText() for c in self.datums if c.currentText()))
            except BaseException:
                try:
                    self.doc.abortTransaction()
                except Exception:
                    pass
                raise
            self.doc.commitTransaction()
            Gui.Control.closeDialog()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    def _part_doc():
        doc = model_doc()
        return doc if doc is not None and not is_assembly(doc) and solids(doc) else None

    class _Cmd:
        def __init__(self, text, tip, active_fn, run_fn):
            self.text, self.tip, self.active_fn, self.run_fn = text, tip, active_fn, run_fn

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            try:
                return bool(self.active_fn())
            except Exception:
                return False

        def Activated(self):
            self.run_fn()

    def _profile():
        Gui.Control.showDialog(GeneralProfilePM(_part_doc()))

    def _delete_all():
        doc = model_doc()
        n = len(tolerances(doc))
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, "Delete All Tolerances",
                                    "Delete all %d dimensions and tolerances of the scheme?" % n,
                                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, Gui.getMainWindow())
        box.setObjectName("SWMBDDeleteAllQuestion")
        if box.exec_() != QtWidgets.QMessageBox.Yes:
            return
        doc.openTransaction("Delete All Tolerances")
        try:
            delete_all_tolerances(doc)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()

    def _import():
        doc = _part_doc()
        path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Import Scheme", "",
                                                        "FreeCAD part (*.FCStd)")
        if not path:
            return
        doc.openTransaction("Import Scheme")
        try:
            made = import_scheme(doc, path)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        App.Console.PrintMessage("FreeCAD: Import Scheme: %d annotations\n" % len(made))

    def _has_tol():
        doc = model_doc()
        return doc is not None and not Gui.Control.activeDialog() and bool(tolerances(doc))

    COMMANDS = {
        "SWStyle_MBDGeneralProfileTolerance": ("General Profile Tolerance",
                                                "A profile tolerance for every face with no tolerance of its own.",
                                                lambda: _part_doc() is not None and not Gui.Control.activeDialog(),
                                                _profile),
        "SWStyle_MBDImportScheme": ("Import Scheme...", "The MBD scheme of another part file, face for face.",
                                     lambda: _part_doc() is not None and not Gui.Control.activeDialog(), _import),
        "SWStyle_MBDDeleteAllTolerances": ("Delete All Tolerances", "Deletes every dimension and tolerance of the scheme.",
                                            _has_tol, _delete_all),
    }

    def register():
        have = set(Gui.listCommands())
        for name, (text, tip, a, r) in COMMANDS.items():
            if name not in have:
                Gui.addCommand(name, _Cmd(text, tip, a, r))
