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
import re
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import rcmenus
from .widgets import alive

Qt = QtCore.Qt
RES = 10.0         # TechDraw's scene units per mm (Rez::guiX); scene y runs down
PX_MM = 3.78       # TechDraw draws a symbol's (and a table's) SVG at 96 px to the inch
NEAR = 4.0         # mm: an annotation or dimension counts this far round its anchor



def _fw_unsplit(objs):
    """objs with a drawing view's model parts read back as their model (drawviews.unsplit; Drawings land151)."""
    try:
        from . import drawviews as DV
        return DV.unsplit(list(objs or []))
    except Exception:
        return list(objs or [])

def _page():
    try:
        from . import drawings
        return drawings.active_page()
    except Exception:
        return None


def _cmd(name, key, text=None):
    ""

    try:
        known = Gui.listCommands()
        if "|" in name:     # "ours|FreeCAD's": the first that exists
            name = next((n for n in name.split("|") if n in known), name.split("|")[-1])
        if name not in known:
            return None
        c = Gui.Command.get(name)
        active = c.isActive()
        info = c.getInfo() or {}
    except Exception:
        return None
    icon = None
    try:
        pix = info.get("pixmap") or ""
        if pix:
            from PySide import QtGui
            icon = Gui.getIcon(pix) if hasattr(Gui, "getIcon") else QtGui.QIcon(pix)
    except Exception:
        icon = None
    try:
        from . import drawings
        icon = drawings.drawn_icon(name) or icon
    except Exception:
        pass
    from . import menunoicon
    if menunoicon.none_for(name):
        icon = None
    return rcmenus.action(key, text or info.get("menuText") or key, lambda: Gui.runCommand(name, 0),
                          enabled=bool(active), icon=icon, command=name)


def page_point(view, pos):
    """The sheet point (mm, y up) under pos (viewport coordinates)."""
    p = view.mapToScene(pos)
    return p.x() / RES, -p.y() / RES


def _num(q):
    return float(q.Value if hasattr(q, "Value") else q)


def _place(v):
    """The view's centre on the sheet (mm): its X, Y plus its projection group's; a dimension or note sits
    relative to the view it belongs to."""
    x, y = _num(v.X), _num(v.Y)
    for o in v.InList:
        if o.TypeId in ("TechDraw::DrawProjGroup", "TechDraw::DrawViewClip"):
            x, y = x + _num(o.X), y + _num(o.Y)
    if not v.isDerivedFrom("TechDraw::DrawViewPart") and not v.isDerivedFrom("TechDraw::DrawViewSymbol"):
        parent = None
        try:
            refs = v.References2D if hasattr(v, "References2D") else []
            parent = refs[0][0] if refs else None
        except Exception:
            parent = None
        parent = parent or getattr(v, "BaseView", None)
        if parent is not None and parent is not v and parent.isDerivedFrom("TechDraw::DrawViewPart"):
            px, py = _place(parent)
            x, y = x + px, y + py
    return x, y


_SVG_SIZE = re.compile(r'<svg[^>]*?\bwidth="([\d.]+)mm"[^>]*?\bheight="([\d.]+)mm"')
_SVG_RECT = re.compile(r'<rect[^>]*?\bx="([-\d.]+)"[^>]*?\by="([-\d.]+)"[^>]*?\bwidth="([-\d.]+)"[^>]*?\bheight="([-\d.]+)"')


def svg_size(svg):
    ""

    m = _SVG_SIZE.search(svg or "")
    if m:
        return float(m.group(1)), float(m.group(2))
    w = h = 0.0
    for x, y, cw, ch in _SVG_RECT.findall(svg or ""):
        w, h = max(w, float(x) + float(cw)), max(h, float(y) + float(ch))
    return w / PX_MM, h / PX_MM


def view_box(v):
    """(xmin, ymin, xmax, ymax) of a drawing view on its sheet, in mm, else None."""
    try:
        x0, y0 = _place(v)
    except Exception as _fw_err:
        _fw_log("drawmenu.py:132", _fw_err)
        return None
    text = getattr(v, "SWNoteText", "") if getattr(v, "SWViewLabelOf", "") else ""
    if text:                # Add View Label's note: its text, not its square canvas (which reaches into the view)
        lines = text.split("\n")
        k = float(getattr(v, "Scale", 1.0) or 1.0)
        w = (0.6 * 3.5 * max(len(line) for line in lines) + 3.0) * k
        h = (3.5 * 1.4 * len(lines) + 3.0) * k
        return (x0 - w / 2, y0 - h / 2, x0 + w / 2, y0 + h / 2)
    if v.isDerivedFrom("TechDraw::DrawViewSymbol") and getattr(v, "Symbol", ""):
        w, h = svg_size(v.Symbol)
        if w > 0 and h > 0:
            k = float(getattr(v, "Scale", 1.0) or 1.0)
            return (x0 - w * k / 2, y0 - h * k / 2, x0 + w * k / 2, y0 + h * k / 2)
    if v.isDerivedFrom("TechDraw::DrawViewDimension"):     # its text: wider than tall
        return (x0 - 2 * NEAR, y0 - NEAR, x0 + 2 * NEAR, y0 + NEAR)
    if not v.isDerivedFrom("TechDraw::DrawViewPart"):
        return (x0 - NEAR, y0 - NEAR, x0 + NEAR, y0 + NEAR)
    pts = []
    try:
        if hasattr(v, "getVisibleEdges"):
            for e in v.getVisibleEdges():
                bb = e.BoundBox
                pts += [(bb.XMin, bb.YMin), (bb.XMax, bb.YMax)]
    except Exception:
        pts = []
    if not pts:
        return (x0 - NEAR, y0 - NEAR, x0 + NEAR, y0 + NEAR)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    # TechDraw's visible edges are in the view's own frame, y down from the view centre
    box = (x0 + min(xs) - 1.0, y0 - max(ys) - 1.0, x0 + max(xs) + 1.0, y0 - min(ys) + 1.0)
    clip = _crop_of(v)
    if clip is not None:            # a cropped view shows only what is inside its crop
        cx, cy, w, h = _num(clip.X), _num(clip.Y), _num(clip.Width), _num(clip.Height)
        box = (max(box[0], cx - w / 2), max(box[1], cy - h / 2), min(box[2], cx + w / 2), min(box[3], cy + h / 2))
        if box[0] > box[2] or box[1] > box[3]:
            return None
    return box


def _visible(v):
    try:
        return bool(v.ViewObject.Visibility)
    except Exception:
        return True


def _is_label(v):
    """A view's label (its name or location note). A balloon also keeps SWView (the view it points
    into) and is an annotation, not a label."""
    kind = getattr(v, "SWAnnotation", "")
    return not kind or "Label" in kind


def _kind(v):
    if getattr(v, "SWTable", "") or v.isDerivedFrom("TechDraw::DrawViewSpreadsheet"):
        return "table"
    if v.isDerivedFrom("TechDraw::DrawViewPart"):
        return "view"
    if v.isDerivedFrom("TechDraw::DrawViewDimension"):
        return "dimension"
    if getattr(v, "SWViewLabelOf", "") or (getattr(v, "SWView", "") and _is_label(v)):
        return "label"
    if getattr(v, "SWAnnotation", "") in ("AutoBorder",):
        return "other"
    if getattr(v, "SWAnnotation", ""):
        return "annotation"
    return "other"          # anything else keeps TechDraw's own menu


LINE_NEAR = 1.5     # mm: a model edge, a cutting line or a detail circle counts this close


def _base_point(base, p3):
    """A 3D model point -> the base view's sheet point (mm, y up)."""
    from . import drawviews as DV
    q = base.projectPoint(p3) - base.projectPoint(DV.model_centre(base))
    k = float(getattr(base, "Scale", 1.0) or 1.0)
    x0, y0 = _place(base)
    return x0 + q.x * k, y0 + q.y * k


def cutting_line(section):
    """((x0, y0), (x1, y1)) of a section view's cutting line on the sheet, else None."""
    base = getattr(section, "BaseView", None)
    if base is None or not base.isDerivedFrom("TechDraw::DrawViewPart"):
        return None
    try:
        o = section.SectionOrigin
        n = section.SectionNormal
        a = _base_point(base, o)
        b = _base_point(base, o + n)
    except Exception:
        return None
    nx, ny = b[0] - a[0], b[1] - a[1]
    L = math.hypot(nx, ny)
    if L < 1e-9:
        return None
    dx, dy = -ny / L, nx / L               # the line runs across the normal
    box = view_box(base)
    if box is not None:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        reach = abs(dx) * (box[2] - box[0]) / 2 + abs(dy) * (box[3] - box[1]) / 2 + 3
        a = (a[0] + dx * ((cx - a[0]) * dx + (cy - a[1]) * dy), a[1] + dy * ((cx - a[0]) * dx + (cy - a[1]) * dy))
    else:
        reach = 50
    return (a[0] - dx * reach, a[1] - dy * reach), (a[0] + dx * reach, a[1] + dy * reach)


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2))
    return math.hypot(p[0] - ax - t * vx, p[1] - ay - t * vy)


def detail_circle(detail):
    """((cx, cy), r) of a detail view's circle on its base view (mm), else None."""
    base = getattr(detail, "BaseView", None)
    if base is None:
        return None
    try:
        k = float(getattr(base, "Scale", 1.0) or 1.0)
        x0, y0 = _place(base)
        return (x0 + detail.AnchorPoint.x * k, y0 + detail.AnchorPoint.y * k), float(detail.Radius) * k
    except Exception:
        return None


def edge_under(v, x, y):
    """The index of the view's model edge under sheet point (x, y), else None."""
    x0, y0 = _place(v)
    import Part
    p = Part.Vertex(App.Vector(x - x0, -(y - y0), 0))
    best = None
    # never ask for an index past the end: TechDraw can crash on that (Windows) instead of raising
    try:
        n = len(v.getVisibleEdges()) + len(v.getHiddenEdges())
    except Exception:
        return None
    for i in range(n):
        try:
            e = v.getEdgeByIndex(i)
        except Exception:
            break
        if e is None:
            continue
        try:
            d = e.distToShape(p)[0]
            if d <= LINE_NEAR and (best is None or d < best[0]):
                best = (d, i)
        except Exception as _fw_err:
            _fw_log("drawmenu.py:284", _fw_err)
    return best[1] if best else None


def hits(view, pos, page=None):
    """Everything under pos, smallest first: (kind, object, extra). Worked out from the document (each view's
    place and lines), not from the scene: wrapping TechDraw's scene items in Python can delete them."""
    page = page or _page()
    if page is None:
        return []
    x, y = page_point(view, pos)
    found = []
    for v in getattr(page, "Views", []) or []:
        if not _visible(v) or v.TypeId in ("TechDraw::DrawProjGroup", "TechDraw::DrawViewClip"):
            continue
        if getattr(v, "SWAnnotation", "") == "AutoBorder":     # the sheet format's zone border: the sheet's
            continue
        if v.isDerivedFrom("TechDraw::DrawViewSection"):
            line = cutting_line(v)
            try:
                shown = v.BaseView.ViewObject.ShowSectionLine
            except Exception:
                shown = True
            if line and shown and _seg_dist((x, y), *line) <= LINE_NEAR:
                found.append((0.5, 0.0, "cutting", v, None))
        if v.isDerivedFrom("TechDraw::DrawViewDetail"):
            c = detail_circle(v)
            if c and abs(math.hypot(x - c[0][0], y - c[0][1]) - c[1]) <= LINE_NEAR:
                found.append((0.5, 0.0, "detail", v, None))
        box = view_box(v)
        if box is None or not (box[0] <= x <= box[2] and box[1] <= y <= box[3]):
            continue
        k = _kind(v)
        area = (box[2] - box[0]) * (box[3] - box[1])
        if k == "view":
            e = edge_under(v, x, y)
            if e is not None:
                found.append((1, area, "edge", v, e))
                continue
        found.append(({"table": 2, "view": 3}.get(k, 0), area, k, v, None))
    found.sort(key=lambda f: (f[0], f[1]))
    return [(f[2], f[3], f[4]) for f in found]


def under(view, pos, page=None):
    """(kind, object) under pos: "dimension", "annotation", "label" (a view's label note), "cutting" (a section
    view's cutting line), "detail" (a detail circle), "edge" (a model edge of a view), "table", "view", "other"
    (anything else TechDraw draws), or (None, None) for the bare sheet."""
    h = hits(view, pos, page)
    if not h:
        return None, None
    return h[0][0], h[0][1]


def on_view(view, pos, page=None):
    """True when anything of the sheet is under pos."""
    return under(view, pos, page)[0] is not None


def pick(obj, sub=None):
    ""
    try:
        names = [(s.Object.Name, tuple(s.SubElementNames)) for s in Gui.Selection.getSelectionEx("", 0)]
        if any(n == obj.Name and (sub is None or sub in subs) for n, subs in names):
            return
        Gui.Selection.clearSelection()
        if sub:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)
        else:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing menu pick: %s\n" % error)


def _model_name(v):
    srcs = _fw_unsplit(getattr(v, "XSource", [])) + list(getattr(v, "Source", []) or [])
    if not srcs:
        return None
    doc = srcs[0].Document
    if doc is v.Document or not doc.FileName:
        return srcs[0].Label
    return doc.FileName.replace("\\", "/").split("/")[-1]


def _open_label(v, model):
    ""
    try:
        srcs = _fw_unsplit(getattr(v, "XSource", [])) + list(getattr(v, "Source", []) or [])
        if any(o.TypeId == "Assembly::AssemblyObject" for o in srcs):
            return "Open Assembly (%s)" % model
    except Exception as _fw_err:
        _fw_log("drawmenu.py:375", _fw_err)
    return "Open Part (%s)" % model


def _crop_of(v):
    return next((o for o in v.InList if o.TypeId == "TechDraw::DrawViewClip"), None)


# --------------------------------------------------------------------------- the parts every menu shares
P = "FreeWorks_Draw"
T_SMART_DIMENSION = "Smart Dimension"
T_CHANGE_LAYER = "Change Layer"
MORE_DIMENSIONS = (("Horizontal", "TechDraw_HorizontalDimension"), ("Vertical", "TechDraw_VerticalDimension"),
                   ("Baseline", "TechDraw_ExtensionCreateHorizCoordDimension"),
                   ("Chain", "TechDraw_ExtensionCreateHorizChainDimension"),
                   ("Symmetric Linear Diametric Dimension", "FreeWorks_DrawSymmetricDiameter|TechDraw_ExtensionInsertDiameter"),
                   ("Ordinate", "TechDraw_ExtensionCreateHorizCoordDimension"),
                   ("Horizontal Ordinate", "TechDraw_ExtensionCreateHorizCoordDimension"),
                   ("Vertical Ordinate", "TechDraw_ExtensionCreateVertCoordDimension"),
                   ("Angular Running Dimension", "TechDraw_3PtAngleDimension"),
                   ("Path Length", "TechDraw_ExtensionCreateLengthArc"),
                   ("Chamfer", "TechDraw_ExtensionCreateHorizChamferDimension"))
SEP = None
ANNOTATIONS = (("Note...", P + "Note"), ("Flag Note...", P + "FlagNote"), ("Balloon...", P + "Balloon"), ("Auto Balloon", P + "AutoBalloon"),
               ("Stacked Balloon...", P + "StackedBalloon"), ("Magnetic Line...", P + "MagneticLine"),
               ("Surface Finish Symbol...", P + "SurfaceFinish"), ("Weld Symbol...", P + "WeldSymbol"),
               ("Caterpillar...", P + "Caterpillar"), ("End Treatment...", P + "EndTreatment"),
               ("Geometric Tolerance...", P + "GeometricTolerance"), ("Datum Feature Symbol...", P + "DatumFeature"),
               ("Datum Target...", P + "DatumTarget"), ("Hole Callout...", P + "HoleCallout"),
               ("Cosmetic Thread...", "FreeWorks_DrawCosmeticThread|TechDraw_ExtensionThreadHoleSide"), SEP,
               ("Center Mark...", P + "CenterMark"), ("Centerline...", P + "Centerline"), SEP,
               ("Multi-jog Leader", P + "MultiJogLeader"), SEP,
               ("Dowel Pin Symbol", P + "DowelPin"), ("Area Hatch/Fill", P + "AreaHatch"),
               ("Location Label", P + "LocationLabel"), ("Revision Cloud", P + "RevisionCloud"),
               ("Insert Block", None), ("Format Painter", None))
DRAWING_VIEWS = (("Model...", P + "ModelView"), ("Projected View", P + "ProjectedView"),
                 ("Auxiliary View", P + "AuxiliaryView"), ("Section View", P + "SectionView"),
                 ("Removed Section", P + "RemovedSection"), ("Detail View", P + "DetailView"),
                 ("Relative View", P + "RelativeView"), SEP, ("Standard 3 View...", P + "Standard3View"), SEP,
                 ("Broken-out Section...", P + "BrokenOut"), ("Break View", P + "Break"), ("Crop View", P + "Crop"),
                 ("Alternate Position...", P + "AlternatePosition"), SEP, ("Empty View", P + "EmptyView"),
                 ("Predefined...", P + "PredefinedView"))
TABLES = (("General Table", P + "GeneralTable"), ("Hole Table...", P + "HoleTable"),
          ("Bill of Materials...", P + "BOM"), ("Revision Table", P + "RevisionTable"),
          ("Family Table...", P + "FamilyTable"),
          ("Weld Table", P + "WeldTable"), ("Bend Table", P + "BendTable"), ("Punch Table", P + "PunchTable"))


def _key(name):
    return name.replace("FreeWorks_", "").replace("TechDraw_", "TD_")


def _list(entries):
    out = []
    for e in entries:
        if e is SEP:
            if out and out[-1].kind != "sep":
                out.append(rcmenus.separator())
            continue
        text, name = e
        if name is None and text == "Insert Block":
            it = _cmd(P + "InsertBlock", "InsertBlock", text) or _cmd("TechDraw_Symbol", "TD_Symbol", text)
            if it is not None:
                out.append(it)
            continue
        if name is None and text == "Format Painter":
            out.append(prefer(P + "FormatPainter", "FormatPainter", text, lambda: X().format_painter()))
            continue
        if "|" in name:         # the first that exists: the Drawings thread's command, else TechDraw's
            name = next((n for n in name.split("|") if n in Gui.listCommands()), name.split("|")[-1])
        it = _cmd(name, _key(name) + "_" + text.replace(" ", "")[:12], text)
        if it is not None:
            out.append(it)
    while out and out[-1].kind == "sep":
        out.pop()
    return out


def prefer(name, key, text, fallback, **kw):
    ""
    it = _cmd(name, key, text)
    return it if it is not None else rcmenus.action(key, text, fallback, **kw)


def X():
    from . import drawextras
    return drawextras


def smart_dimension():
    return _cmd("FreeWorks_DrawSmartDimension|TechDraw_Dimension", "SmartDimension", T_SMART_DIMENSION)


def tail():
    """Smart Dimension, More Dimensions >, Annotations >, Drawing Views >, Tables > (every drawing menu)."""
    return _live([smart_dimension(),          # an emptied submenu goes too (pkg209)
            rcmenus.submenu("MoreDimensions", rcmenus.T_MORE_DIMS, _live(_list(MORE_DIMENSIONS))),
            rcmenus.submenu("Annotations", "Annotations", _live(_list(ANNOTATIONS))),   # e.g. no Balloon on the sheet format
            rcmenus.submenu("DrawingViews", "Drawing Views", _live(_list(DRAWING_VIEWS))),
            rcmenus.submenu("Tables", "Tables", _live(_list(TABLES)))])    # e.g. no second Revision Table (pkg209)


def change_layer(objs):
    return rcmenus.action("ChangeLayer", T_CHANGE_LAYER, lambda: X().change_layer(objs))


def head(select_other=True):
    out = []
    if select_other:
        out.append(rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, select_other_here))
    return out + [rcmenus.selection_tools_menu(), rcmenus.zoom_menu(), rcmenus.recent_menu(), rcmenus.separator()]


def comment(obj):
    def fill(menu):
        a = menu.addAction("Add Comment")

        def run():
            try:
                from . import fmmenu
                fmmenu._fallback_comment(obj)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Comment: %s\n" % error)
        a.triggered.connect(lambda: QtCore.QTimer.singleShot(0, run))
    return rcmenus.dynamic("Comment", "Comment", fill)


def rs_options():
    from . import rcextras
    return rcextras.relations_snaps_item(more=False)


def _live(items):
    """items without the ones that cannot run now (and submenus left empty): nothing greyed (pkg209)."""
    out = []
    for i in items:
        if i is None or (i.kind == "action" and not i.enabled):
            continue
        if i.kind == "sub":
            i.sub = _live(i.sub or [])
            if not i.sub:
                continue
        out.append(i)
    return out


def _clean(items):
    out = []
    for i in items:
        if i is None or (i.kind == "sub" and not i.sub and not getattr(i, "keep_empty", False)):
            continue
        if i.kind == "sep" and (not out or out[-1].kind == "sep"):
            continue
        out.append(i)
    while out and out[-1].kind == "sep":
        out.pop()
    return out


# --------------------------------------------------------------------------- Select Other
_LAST = {}


def select_other_here():
    """Select Other on a sheet: what is under the pointer, in a list; a click picks it."""
    view, pos = _LAST.get("view"), _LAST.get("pos")
    found = hits(view, pos) if view is not None else []
    menu = QtWidgets.QMenu(Gui.getMainWindow())
    menu.setObjectName("SWSelectOther")
    for kind, obj, extra in found:
        sub = "Edge%d" % extra if kind == "edge" else None
        a = menu.addAction("%s@%s" % (sub, obj.Label) if sub else obj.Label)
        a.triggered.connect(lambda c=False, o=obj, s=sub: pick(o, s))
    if not found:
        a = menu.addAction("(nothing here)")
        a.setEnabled(False)
    _LAST["menu"] = menu
    menu.popup(QtGui.QCursor.pos())
    return menu


# --------------------------------------------------------------------------- the menus
def set_as_anchor_menu(page):
    """Set as Anchor > (the table kinds), only on a sheet-format line end or corner while the format is edited
    (the Drawings thread's drawtableedit.anchor_target, land33)."""
    try:
        from . import drawtableedit as TE
        target = TE.anchor_target
        kinds = [k[0] if isinstance(k, (tuple, list)) else k for k in TE.ANCHOR_KINDS]
    except Exception:
        return None
    view, pos = _LAST.get("view"), _LAST.get("pos")
    if view is None or pos is None:
        return None
    p = page_point(view, pos)
    try:
        if target(page, p) is None:
            return None
    except Exception:
        return None

    def run(kind):
        TE.ASK["kind"] = kind
        try:
            TE.LAST_POINT[:] = [p]          # the right-click's point (LAST_POINT follows left presses only)
        except Exception as _fw_err:
            _fw_log("drawmenu.py:567", _fw_err)
        Gui.runCommand("FreeWorks_DrawSetAsAnchor", 0)
    if "FreeWorks_DrawSetAsAnchor" not in Gui.listCommands():
        return None
    return rcmenus.submenu("SetAsAnchor", "Set as Anchor",
                           [rcmenus.action("SetAsAnchor_" + k.replace(" ", ""), k, lambda k=k: run(k)) for k in kinds])


def sheet_items(page):
    try:
        from . import drawsheet
        editing = drawsheet.editing_format(page)
    except Exception:
        editing = False
    if editing:
        t = page.Template
        out = head() + [rcmenus.header("Sheet (%s)" % (t.Label if t is not None else page.Label), "HeaderSheet")]
        anchor = set_as_anchor_menu(page)
        if anchor is not None:
            out.append(anchor)
        out += [
                        prefer(P + "TitleBlockFields", "TitleBlockFields", "Title Block Fields...",
                               lambda: X().title_block_fields(page), enabled=t is not None),
                        prefer(P + "AutomaticBorder", "AutomaticBorder", "Automatic Border...",
                               lambda: X().automatic_border_dialog(page)),
                        _cmd(P + "EditSheet", "EditSheet", "Edit Sheet"),
                        _cmd(P + "AddSheet", "AddSheet", "Add Sheet..."),
                        rcmenus.action("CopySheet", "Copy", lambda: X().copy_sheet(page)),
                        rcmenus.action("DeleteSheet", rcmenus.T_DELETE, lambda: X().delete_object(page)),
                        rcmenus.separator(), rs_options(), rcmenus.separator()]
        return _clean(out + tail() + [change_layer([page])])
    locked = X().sheet_focus_locked(page)
    out = head() + [
        rcmenus.header("Sheet (%s)" % page.Label, "HeaderSheet"),
        rcmenus.action("DisplayGrid", rcmenus.T_DISPLAY_GRID, lambda: X().toggle_grid(page),
                       checked=X().grid_on(page), more=True),
        _cmd(P + "EditSheetFormat", "EditSheetFormat", "Edit Sheet Format"),
        rcmenus.action("LockSheetFocus", "Unlock Sheet Focus" if locked else "Lock Sheet Focus",
                       lambda: X().toggle_sheet_focus(page)),
        _cmd(P + "AddSheet", "AddSheet", "Add Sheet..."),
        rcmenus.action("CopySheet", "Copy", lambda: X().copy_sheet(page)),
        rcmenus.action("DeleteSheet", rcmenus.T_DELETE, lambda: X().delete_object(page))]
    props = _cmd(P + "SheetProperties", "SheetProperties", "Properties...")
    if props is not None:
        props.more = True
        out.append(props)
    out += [rcmenus.separator(), rs_options(), rcmenus.separator(), comment(page)]
    return _clean(out + tail() + [change_layer([page])])


ALIGNMENT = (("Break Alignment", "BreakAlignment"), ("Align Horizontal by Origin", "AlignHorizontalOrigin"),
             ("Align Vertical by Origin", "AlignVerticalOrigin"), ("Align Horizontal by Center", "AlignHorizontalCenter"),
             ("Align Vertical by Center", "AlignVerticalCenter"), ("Default Alignment", "DefaultAlignment"))


def _alignment(v=None):
    ""



    try:
        from . import drawviewcmds as DV
        parent = DV.default_parent(v) if v is not None else None
        aligned = v is not None and bool(getattr(v, "SWAlignedTo", "") or "")
    except Exception:
        DV, parent, aligned = None, None, False
    out = []
    for t, k in ALIGNMENT:
        if v is not None and parent is None and k == "BreakAlignment" and not aligned:
            continue
        if v is not None and parent is None and k == "DefaultAlignment":
            if aligned and DV is not None:
                out.append(rcmenus.action(k, t, lambda: _base_default_alignment(v)))
            continue
        out.append(_cmd(P + k, k, t))
    return _live(out)


def _base_default_alignment(v):
    """Default Alignment on a base view: no alignment, as when it was placed."""
    doc = v.Document
    doc.openTransaction("Default Alignment")
    try:
        for name in ("SWAlignedTo", "SWAlignment"):
            if name in v.PropertiesList:
                setattr(v, name, "")
        if "SWAlignmentBroken" in v.PropertiesList:
            v.SWAlignmentBroken = False
    finally:
        doc.commitTransaction()
    doc.recompute()


def _reset_sketch_visibility(v):
    """Reset sketch visibility, only while a sketch of the view's sheet is hidden: otherwise it has nothing to show
    again (it only said so in the status bar), so it is left out (NO DEAD CONTROLS; pkg214)."""
    try:
        page = X()._page_of(v)
        hidden = any(getattr(o, "SWAnnotation", "") == "SheetSketch" and not o.ViewObject.Visibility
                     for o in (page.Views if page is not None else []))
    except Exception:
        hidden = True
    if not hidden:
        return None
    return rcmenus.action("ResetSketchVisibility", "Reset sketch visibility", lambda: X().reset_sketch_visibility(v))


def _tangent_mode(v):
    m = getattr(v, "SWTangentEdges", "")
    if m:
        return m
    return "Visible" if getattr(v, "SmoothVisible", True) else "Removed"


def view_items(v, edge=None):
    locked = bool(getattr(v, "LockPosition", False))
    out = head()
    if edge is not None:
        out.insert(1, rcmenus.action("SelectMidpoint", rcmenus.T_SELECT_MIDPOINT, lambda: select_midpoint(v, edge)))
    comp = X().component_name(v)
    hidden = X().hidden_components(v)
    if comp or hidden:
        out += [rcmenus.header("Component (%s)" % (comp or hidden[0].Label), "HeaderComponent"),
                rcmenus.submenu("ShowHide", "Show/Hide", _live([
                    rcmenus.action("HideComponent", "Hide Component", lambda: X().hide_component(v), enabled=bool(comp)),
                    rcmenus.action("ShowComponents", "Show All Components", lambda: X().show_components(v),
                                   enabled=bool(hidden))])),
                rcmenus.action("ComponentLineFont", "Component Line Font...", lambda: X().component_line_font(v))]
    mode = _tangent_mode(v)
    parent = X().parent_view(v)
    out += [rcmenus.header("View (%s)" % v.Label, "HeaderView"),
            _cmd(P + "LockViewPosition", "LockViewPosition", "Unlock View Position" if locked else "Lock View Position"),
            rcmenus.action("LockViewFocus", "Unlock View Focus" if X().view_focus_locked(v) else "Lock View Focus",
                           lambda: X().toggle_view_focus(v))]
    hide = _hide_or_show(v)
    if hide is not None:
        hide.more = True
        out.append(hide)
    out += [rcmenus.submenu("ViewAlignment", "Alignment", _alignment(v)),
            _reset_sketch_visibility(v),
            rcmenus.submenu("TangentEdge", "Tangent Edge", [
                _checked(_cmd(P + "TangentVisible", "TangentVisible"), mode == "Visible"),
                _checked(_cmd(P + "TangentWithFont", "TangentWithFont"), mode == "With Font"),
                _checked(_cmd(P + "TangentRemoved", "TangentRemoved"), mode == "Removed"),
                rcmenus.separator(),
                rcmenus.action("TangentHideEnds", "Hide Ends", lambda: X().toggle_tangent_hide_ends(v),
                               checked=X().tangent_ends_hidden(v))])]
    if _crop_of(v) is not None:
        out.append(rcmenus.submenu("CropView", "Crop View", [_cmd(P + "RemoveCrop", "RemoveCrop")]))
    if parent is not None:
        out.append(rcmenus.action("JumpToParent", "Jump to Parent View", lambda: X().jump_to(parent)))
    out += [comment(v),
            prefer(P + "ReplaceModel", "ReplaceModel", "Replace Model", lambda: X().replace_model(v)),
            rcmenus.action("ConvertViewToSketch", "Convert View to Sketch", lambda: X().convert_view_to_sketch(v)),
            rcmenus.action("DeleteView", rcmenus.T_DELETE, lambda: X().delete_object(v)),
            change_layer([v]),
            rcmenus.action("AddViewLabel", "Add View Label", lambda: X().add_view_label(v)),
            _cmd(P + "ViewProperties", "ViewProperties", "Properties..."),
            rs_options()]
    return _clean(out + tail())


def _view_hidden(v):
    try:
        return not v.ViewObject.Visibility
    except Exception:
        return False


def _show_view(v):
    doc = v.Document
    doc.openTransaction("Show")
    try:
        v.ViewObject.Visibility = True
    finally:
        doc.commitTransaction()
    doc.recompute()


def _hide_or_show(v):
    ""
    if _view_hidden(v):
        return rcmenus.action("HideView", "Show", lambda: _show_view(v))
    return _cmd(P + "HideView", "HideView", rcmenus.T_HIDE)


def _checked(item, on):
    if item is not None:
        item.checked = bool(on)
    return item


def select_midpoint(v, edge):
    pick(v, "Edge%d" % edge)
    try:
        Gui.runCommand("TechDraw_Midpoints", 0)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Select Midpoint: %s\n" % error)



# pack families (the pack has none of these: the bar showed grey lettered tiles, Look audit row 13)
DRAWN_BAR = {"OpenPart": "DrawOpenModel", "OpenPartInPosition": "DrawOpenPartInPosition",
             "HideShowEdges": "DrawHideShowEdges", "LineColor": "DrawLineColor",
             "LineThickness": "DrawLineThickness", "LineStyle": "DrawLineStyle"}


def _entry(key, label, families, run):
    from . import contextbar, rcextras
    icon = None
    try:
        from . import icons
        if key in DRAWN_BAR and hasattr(icons, "drawn"):
            i = icons.drawn(DRAWN_BAR[key])
            if not i.isNull() and icons.paints(i):
                icon = i
    except Exception as _fw_err:
        _fw_log("drawmenu.py:_entry", _fw_err)
    return contextbar.Entry(key, label, icon or rcextras._icon(label, *families), rcextras._tip(label), run)


def view_row(v, edge=None):
    model = _model_name(v) or v.Label

    def open_in_position():
        doc = X()
        from . import drawviewcmds
        d = drawviewcmds.open_model(v)
        try:
            if d is not None:
                Gui.ActiveDocument.ActiveView.setViewDirection(tuple(v.Direction))
        except Exception as _fw_err:
            _fw_log("drawmenu.py:731", _fw_err)

    def decorate():
        if edge is not None:
            pick(v, "Edge%d" % edge)
        Gui.runCommand("TechDraw_DecorateLine", 0)

    def hide_show_edges():

        pick(v, "Edge%d" % edge) if edge is not None else pick(v)
        if "FreeWorks_DrawHideShowEdges" in Gui.listCommands():
            Gui.runCommand("FreeWorks_DrawHideShowEdges", 0)
        else:
            decorate()

    def open_model():
        from . import drawviewcmds
        drawviewcmds.open_model(v)
    top = [_entry("OpenPart", _open_label(v, model), ("FILE_OPEN_PART", "OPEN_PART", "FILE_OPEN"), open_model),
           _entry("OpenPartInPosition", "Open Part in Position", ("OPEN_PART_IN_POSITION", "FILE_OPEN_PART"),
                  open_in_position),
           _entry("HideShowEdges", "Hide/Show Edges", ("HIDE_SHOW_EDGES", "HIDE_EDGES"), hide_show_edges)]
    if edge is not None:
        top += [_entry("LineColor", "Line Color", ("LINE_COLOR",), decorate),
                _entry("LineThickness", "Line Thickness", ("LINE_THICKNESS",), decorate),
                _entry("LineStyle", "Line Style", ("LINE_STYLE", "LINE_FONT"), decorate)]
    return (top, [], set())


LINEAR = ("Distance", "DistanceX", "DistanceY")


def dimension_items(dim):
    name = "%s(%s)" % (dim.Label, X().dim_value_text(dim))
    hole = bool(getattr(dim, "SWHoleCallout", False))
    ex = X()
    opts = [rcmenus.action("CenterDimension", "Center Dimension", lambda: ex.center_dimension(dim),
                           checked=ex.is_centered(dim)),
            rcmenus.action("OffsetText", "Offset Text", lambda: ex.toggle_offset_text(dim), checked=ex.is_offset(dim)),
            rcmenus.action("ShowParentheses", "Show Parentheses", lambda: ex.toggle_parentheses(dim),
                           checked=ex.has_parentheses(dim)),
            rcmenus.action("ShowAsInspection", "Show as Inspection", lambda: ex.toggle_inspection(dim),
                           checked=ex.is_inspection(dim))]
    from . import drawdimtools as DDT
    linear = DDT.is_linear_round(dim)
    if dim.Type in ("Radius", "Diameter") or linear:
        def as_kind(kind, text):
            if kind == "Linear":
                ex._transaction(dim.Document, text, lambda: DDT.display_as_linear(dim))
            elif linear:
                ex._transaction(dim.Document, text, lambda: DDT.display_as_round(dim, kind))
            else:
                ex.set_dim_type(dim, kind, text)
        opts += [rcmenus.separator(),
                 rcmenus.action("DisplayAsDiameter", rcmenus.T_AS_DIAMETER,
                                lambda: as_kind("Diameter", "Display As Diameter"),
                                checked=dim.Type == "Diameter"),
                 rcmenus.action("DisplayAsRadius", rcmenus.T_AS_RADIUS,
                                lambda: as_kind("Radius", "Display As Radius"),
                                checked=dim.Type == "Radius"),
                 rcmenus.action("DisplayAsLinear", "Display As Linear",
                                lambda: as_kind("Linear", "Display As Linear"), checked=linear)]
    out = head() + [rcmenus.header("Dimension (%s)" % name, "HeaderDimension"),
                    rcmenus.action("Hide", rcmenus.T_HIDE, lambda: _hide(dim)),
                    rcmenus.action("Reattach", "Reattach", lambda: ex.reattach(dim)),
                    rcmenus.submenu("DisplayOptions", "Display Options", opts)]
    if not hole and dim.Type in LINEAR:
        def turn(kind, text):
            ex.set_dim_type(dim, kind, text)
            if linear:                          # shown as linear: its points move round the circle
                DDT.refresh_linear_rounds(dim.Document)
        out += [rcmenus.action("SetVertical", "Set Vertical", lambda: turn("DistanceY", "Set Vertical"),
                               enabled=dim.Type != "DistanceY"),
                rcmenus.action("AlignToEdge", "Align to edge", lambda: turn("Distance", "Align to edge"),
                               enabled=dim.Type != "Distance")]
    out += tail() + [rcmenus.header("%s (%s)" % (rcmenus.T_SELECTED, name), "HeaderSelected"), change_layer([dim])]
    return _clean(out)


def _hide(obj):
    doc = obj.Document
    doc.openTransaction("Hide")
    try:
        obj.ViewObject.Visibility = False
    finally:
        doc.commitTransaction()


def annotation_items(a, label_of=None):
    ex = X()
    out = head()
    if label_of is not None:
        out.append(rcmenus.action("JumpToParent", "Jump to Parent View", lambda: ex.jump_to(label_of)))
    out += tail()
    out += [rcmenus.header("%s (%s)" % (rcmenus.T_SELECTED, a.Label), "HeaderSelected")]
    editable = getattr(a, "SWAnnotation", "") in ("Note",) or label_of is not None
    if editable:
        out.append(rcmenus.action("EditText", "Edit Text", lambda: ex.edit_text(a)))
    out.append(prefer(P + "MakeBlock", "MakeBlock", "Make Block", lambda: ex.make_block(a)))
    if label_of is not None:
        out.append(rcmenus.action("ManualViewLabel", "Manual View Label Text", lambda: ex.manual_view_label(a),
                                  checked=bool(getattr(a, "FWManualLabel", False))))
    if getattr(a, "SWAnnotation", "") == "Block":       # a block instance (the Drawings thread's drawblocks)
        out += [_cmd(P + "EditBlock", "EditBlock", "Edit Block"), _cmd(P + "ExplodeBlock", "ExplodeBlock", "Explode Block"),
                _cmd(P + "SaveBlock", "SaveBlock", "Save Block...")]
    if getattr(a, "SWAnnotation", "") == "Balloon":
        out.append(rcmenus.action("AddToStack", "Add to Stack", lambda: add_to_stack(a)))
    if label_of is None:
        out.append(align_menu(a))
    out.append(change_layer([a]))
    out.append(rcmenus.action("AddToLibrary", "Add to Library", lambda: ex.add_to_library(a)))
    if editable:
        out.append(rcmenus.action("EditTextInWindow", "Edit Text in Window", lambda: ex.edit_text(a)))
    out.append(rcmenus.action("Hide", rcmenus.T_HIDE, lambda: _hide(a)))
    return _clean(out)


ALIGN_ITEMS = (("Align Left", "FreeWorks_DrawAlignLeft"), ("Align Right", "FreeWorks_DrawAlignRight"),
               ("Align Top", "FreeWorks_DrawAlignTop"), ("Align Bottom", "FreeWorks_DrawAlignBottom"),
               ("Align Horizontal", "FreeWorks_DrawAlignHorizontal"), ("Align Vertical", "FreeWorks_DrawAlignVertical"),
               None, ("Space Evenly Across", "FreeWorks_DrawSpaceEvenlyAcross"),
               ("Space Evenly Down", "FreeWorks_DrawSpaceEvenlyDown"))


def align_menu(a):
    ""
    def select_and_run(name):
        try:
            if not Gui.Selection.isSelected(a):
                Gui.Selection.addSelection(a)
        except Exception as _fw_err:
            _fw_log("drawmenu.py:847", _fw_err)
        Gui.runCommand(name, 0)
    try:
        from . import drawmenus, drawings as D
        picked = [o.Name for o in drawmenus.picked_page_objects(D.active_page())]
        two = len(set(picked) | {a.Name}) >= 2
    except Exception:
        two = True
    items = []
    for row in ALIGN_ITEMS:
        if row is None:
            items.append(rcmenus.separator())
            continue
        text, name = row
        items.append(rcmenus.action(name.replace("FreeWorks_Draw", ""), text, lambda n=name: select_and_run(n),
                                    enabled=two))
    if not two:
        return None
    return rcmenus.submenu("Align", "Align", items)


def add_to_stack(balloon):
    ""

    from . import drawannot, drawings as D
    item = getattr(balloon, "SWItem", "") or "1"
    try:
        nxt = str(int(item) + 1)
    except ValueError:
        nxt = ""
    page = D.active_page()
    if page is None:
        return
    panel = drawannot.StackedBalloonPanel(page)
    D._show(panel)
    try:
        panel.items.setText(", ".join(x for x in (item, nxt) if x))
    except Exception as _fw_err:
        _fw_log("drawmenu.py:883", _fw_err)


def cutting_items(section):
    ex = X()
    out = head() + [rcmenus.action("JumpToSection", "Jump to Section View", lambda: ex.jump_to(section)),
                    rcmenus.action("HideCuttingLine", "Hide Cutting Line", lambda: ex.toggle_cutting_line(section)),
                    rcmenus.action("EditCuttingLine", "Edit Cutting Line", lambda: ex.edit_object(section))]
    return _clean(out + tail() + [change_layer([section])])


def detail_items(detail):
    ex = X()
    out = head() + [rcmenus.action("JumpToDetail", "Jump to Detail View", lambda: ex.jump_to(detail)),
                    rcmenus.action("EditDetailSketch", "Edit Sketch", lambda: ex.edit_object(detail))]
    return _clean(out + tail() + [change_layer([detail])])


def _table_menu_items():
    """The Drawings thread's table editing menu (drawtableedit.TABLE_MENU: (label, command) or (label, [...]),
    None = separator), as menu items; None when that module is not there."""
    try:
        from . import drawtableedit
        spec = drawtableedit.TABLE_MENU
    except Exception:
        return None
    out = []
    for e in spec:
        if e is None:
            out.append(rcmenus.separator())
            continue
        label, what = e
        if isinstance(what, (list, tuple)):
            out.append(rcmenus.submenu("Table_" + label.replace(" ", ""), label,
                                       [_cmd(n, "Table_" + label.replace(" ", "") + "_" + l.replace(" ", ""), l)
                                        for l, n in what]))
        else:
            out.append(_cmd(what, "Table_" + label.replace(" ", ""), label))
    return out



# Delete > | Hide > | Formatting > [Column Width, Lock Column Width, Row Height, Lock Row Height, Entire Table] |
# Split > | Sort | Save As... | (revision table: --- Hide Table, the drawing tools) | "Selected Entity (...)"
# Change Layer. No "Table (...)" heading; a BOM cell has no drawing tools under it. FreeCAD's own table items that

TABLE_SW_ORDER = ("Insert", "Select", "Delete", "Hide", "Show", "Formatting", "Split", "Sort...", "Sort",
                  "Merge Cells", "Unmerge a Cell", "Merge Tables", "Save As...")
FORMAT_LOCKS = {"Column Width...": "Lock Column Width", "Row Height...": "Lock Row Height"}
FORMAT_PLAIN = ("Column Width...", "Row Height...", "Entire Table...")


def _is_bom(t):
    return getattr(t, "SWTable", "") in ("BOM", "Bill of Materials")


def _bom_row_model(t):
    ""

    if not _is_bom(t):
        return None
    try:
        from . import drawtableedit as TE
        cur = TE.current()
        if cur is None or cur[0] is not t or cur[1] <= 0:
            return None
        keys = list(getattr(t, "SWBomRowKeys", []) or [])
        key = keys[cur[1] - 1] if cur[1] - 1 < len(keys) else ""
        dn, _, on = key.partition("#")
        obj = App.getDocument(dn).getObject(on) if dn and on else None
        for _ in range(8):                              # a component is a link: open what it links to
            nxt = getattr(obj, "LinkedObject", None) if obj is not None else None
            if nxt is None or nxt is obj or not hasattr(nxt, "Document"):
                break
            obj = nxt
        return obj
    except Exception as _fw_err:
        _fw_log("drawmenu.py:_bom_row_model", _fw_err)
        return None


def _open_row(obj):
    """Brings the row's part forward in its own model window (its file's, or this document's 3D view)."""
    doc = obj.Document
    try:
        Gui.Selection.clearSelection()
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sw in (mdi.subWindowList() if mdi else []):
            w = sw.widget()
            if w is not None and "View3DInventor" in w.metaObject().className() and \
                    (doc.Label in sw.windowTitle() or doc.Name in sw.windowTitle()):
                mdi.setActiveSubWindow(sw)
                break
        else:
            Gui.activateDocument(doc.Name)
            Gui.runCommand("Std_ViewCreate", 0)
        App.setActiveDocument(doc.Name)
        Gui.Selection.addSelection(doc.Name, obj.Name)
    except Exception as _fw_err:
        _fw_log("drawmenu.py:_open_row", _fw_err)
        from . import fwtell
        fwtell.tell("Could not open a window for the part.", _fw_err)


def _open_row_label(obj):
    fn = getattr(obj.Document, "FileName", "") or ""
    return "Open %s" % (fn.replace("\\", "/").split("/")[-1] if fn else obj.Label)


def table_items(t):
    kind = getattr(t, "SWTable", "")
    out = head()
    row = _bom_row_model(t)
    if row is not None:
        out.insert(len(out) - 1, rcmenus.action("Table_OpenRowModel", _open_row_label(row), lambda: _open_row(row)))
    if kind == "Revision":
        out.append(rcmenus.submenu("Revisions", "Revisions", [_cmd(P + "AddRevision", "AddRevision")]))
    edits = _table_menu_items()
    if edits is None:
        edits = [_cmd(P + "UpdateTable", "UpdateTable")] if kind in ("BOM", "Hole", "Bend", "Punch", "Weld") else []
    edits = [e for e in _live(edits) if e.kind != "sep"]       # only what runs on the picked cells (pkg209)
    by = {}
    for e in edits:
        by.setdefault(e.text, e)
    if "Sort..." in by:
        by["Sort..."].text = "Sort"
        by.pop("Sort", None)
    fmt = by.get("Formatting")
    if fmt is not None:
        sub = []
        for s in fmt.sub or []:
            sub.append(s)
            lock = by.pop(FORMAT_LOCKS.get(s.text, ""), None)
            if lock is not None:
                sub.append(lock)
        for s in sub:
            if s.text in FORMAT_PLAIN:
                s.text = s.text[:-3]
        fmt.sub = sub
    by.pop("Table Header", None)
    if kind != "Revision":                  # Hide > Table first (the revision table has Hide Table instead)
        whole = rcmenus.action("Table_Hide_Table", "Table", lambda: _hide(t))
        if "Hide" in by:
            by["Hide"].sub = [whole] + list(by["Hide"].sub or [])
        else:
            by["Hide"] = rcmenus.submenu("Table_Hide", "Hide", [whole])
    used = set()
    for name in TABLE_SW_ORDER:
        e = by.get(name)
        if e is not None and id(e) not in used:
            out.append(e)
            used.add(id(e))
    rest = [e for e in edits if id(e) not in used and by.get(e.text) is e]
    if rest:
        out += [rcmenus.separator()] + rest
    if kind == "Revision":
        out += [rcmenus.separator(), rcmenus.action("HideTable", "Hide Table", lambda: _hide(t))]
    if not _is_bom(t):
        out += [rcmenus.separator()] + tail()
    out += [rcmenus.header("%s (%s)" % (rcmenus.T_SELECTED, t.Label), "HeaderSelected"), change_layer([t])]
    return _clean(out)


def table_cell_pick(t):
    ""
    try:
        from . import drawtableedit as TE
    except Exception:
        return
    view, pos = _LAST.get("view"), _LAST.get("pos")
    page = _page()
    if view is None or pos is None or page is None:
        return
    p = page_point(view, pos)
    try:
        cell = TE.cell_at(t, p)
    except Exception:
        cell = None
    if cell is None:
        return
    cur = TE.current()
    if cur is not None and cur[0] is t and cur[1] <= cell[0] <= cur[3] and cur[2] <= cell[1] <= cur[4]:
        return
    TE.set_current(t, cell[0], cell[1])


def _label_view(a):
    name = getattr(a, "SWViewLabelOf", "") or (getattr(a, "SWView", "") if _is_label(a) else "")
    return a.Document.getObject(name) if name else None


def show_menu(pos, kind=None, obj=None, extra=None):
    page = _page()
    if page is None:
        return None
    if kind in ("view", "edge") and obj is not None:
        edge = extra if kind == "edge" else None
        pick(obj, "Edge%d" % edge if edge is not None else None)
        return rcmenus.show(rcmenus.Builder("DrawEdge" if edge is not None else "DrawView", view_items(obj, edge),
                                            row=view_row(obj, edge), chevron=True), pos)
    if kind == "dimension" and obj is not None:
        pick(obj)
        return rcmenus.show(rcmenus.Builder("DrawDimension", dimension_items(obj)), pos)
    if kind in ("annotation", "label") and obj is not None:
        pick(obj)
        return rcmenus.show(rcmenus.Builder("DrawAnnotation", annotation_items(obj, _label_view(obj))), pos)
    if kind == "cutting" and obj is not None:
        pick(obj)
        return rcmenus.show(rcmenus.Builder("DrawCuttingLine", cutting_items(obj)), pos)
    if kind == "detail" and obj is not None:
        pick(obj)
        return rcmenus.show(rcmenus.Builder("DrawDetailCircle", detail_items(obj)), pos)
    if kind == "table" and obj is not None:
        pick(obj)
        table_cell_pick(obj)
        return rcmenus.show(rcmenus.Builder("DrawTable", table_items(obj)), pos)
    try:
        from . import drawsheet
        editing = drawsheet.editing_format(page)
    except Exception:
        editing = False
    return rcmenus.show(rcmenus.Builder("DrawSheetFormat" if editing else "DrawSheet", sheet_items(page),
                                        chevron=not editing), pos)


# --------------------------------------------------------------------------- the tree rows (RC6, RC7)
def _tree_tail(view, doc, obj):
    from . import fmmenu
    return [rcmenus.action("GoTo", "Go To...", lambda: fmmenu.go_to(view, doc)),
            rcmenus.action("ZoomToSelection", "Zoom to Selection", lambda: X().jump_to(obj)),
            rcmenus.action("CollapseItems", "Collapse Items", lambda: fmmenu.collapse(view)),
            rcmenus.action("TreeItems", "Hide/Show Tree Items...", fmmenu.tree_items)]


def tree_sheet_items(page, view=None):
    """RC6: the sheet's row in the tree (full already)."""
    locked = X().sheet_focus_locked(page)
    try:
        from . import drawsheet
        editing = drawsheet.editing_format(page)
    except Exception:
        editing = False
    # while the sheet format is being edited, Edit Sheet Format can't run (it showed greyed): Edit Sheet takes its

    edit = _cmd(P + "EditSheet", "EditSheet", "Edit Sheet") if editing else \
        _cmd(P + "EditSheetFormat", "EditSheetFormat", "Edit Sheet Format")
    lock = None if editing else rcmenus.action("LockSheetFocus", "Unlock Sheet Focus" if locked else "Lock Sheet Focus",
                                               lambda: X().toggle_sheet_focus(page))
    out = [rcmenus.header("Sheet (%s)" % page.Label, "HeaderSheet"),
           rcmenus.action("DisplayGrid", rcmenus.T_DISPLAY_GRID, lambda: X().toggle_grid(page), checked=X().grid_on(page)),
           edit, lock,
           _cmd(P + "AddSheet", "AddSheet", "Add Sheet..."),
           rcmenus.action("CopySheet", "Copy", lambda: X().copy_sheet(page)),
           rcmenus.action("DeleteSheet", rcmenus.T_DELETE, lambda: X().delete_object(page)),
           _cmd(P + "SheetProperties", "SheetProperties", "Properties..."),
           rcmenus.separator(), rs_options(), rcmenus.separator(), comment(page)]
    return _clean(out + _tree_tail(view, page.Document, page))


def tree_view_items(v, view=None):
    """RC7: a drawing view's row in the tree (full already)."""
    locked = bool(getattr(v, "LockPosition", False))
    mode = _tangent_mode(v)
    model = _model_name(v)
    out = [rcmenus.header("View (%s)" % v.Label, "HeaderView")]
    if model:
        out.append(_cmd(P + "OpenModel", "OpenModel", _open_label(v, model)))
    out += [rcmenus.action("EditFeature", "Edit Feature", lambda: X().edit_object(v)),
            _cmd(P + "LockViewPosition", "LockViewPosition", "Unlock View Position" if locked else "Lock View Position"),
            rcmenus.action("LockViewFocus", "Unlock View Focus" if X().view_focus_locked(v) else "Lock View Focus",
                           lambda: X().toggle_view_focus(v)),
            _hide_or_show(v),
            rcmenus.submenu("ViewAlignment", "Alignment", _alignment(v)),
            _reset_sketch_visibility(v),
            rcmenus.submenu("TangentEdge", "Tangent Edge", [
                _checked(_cmd(P + "TangentVisible", "TangentVisible"), mode == "Visible"),
                _checked(_cmd(P + "TangentWithFont", "TangentWithFont"), mode == "With Font"),
                _checked(_cmd(P + "TangentRemoved", "TangentRemoved"), mode == "Removed"),
                rcmenus.separator(),
                rcmenus.action("TangentHideEnds", "Hide Ends", lambda: X().toggle_tangent_hide_ends(v),
                               checked=X().tangent_ends_hidden(v))]),
            comment(v),
            prefer(P + "ReplaceModel", "ReplaceModel", "Replace Model", lambda: X().replace_model(v)),
            rcmenus.action("ConvertViewToSketch", "Convert View to Sketch", lambda: X().convert_view_to_sketch(v)),
            rcmenus.action("DeleteView", rcmenus.T_DELETE, lambda: X().delete_object(v)),
            change_layer([v]),
            rcmenus.action("AddViewLabel", "Add View Label", lambda: X().add_view_label(v)),
            _cmd(P + "ViewProperties", "ViewProperties", "Properties..."),
            rs_options()]
    return _clean(out + _tree_tail(view, v.Document, v))


def _page_of_template(t):
    for o in getattr(t, "InList", []) or []:
        if o.isDerivedFrom("TechDraw::DrawPage") and getattr(o, "Template", None) is t:
            return o
    return None


def tree_format_items(t, view=None):
    ""




    page = _page_of_template(t)
    if page is None:
        return _clean(_live([rcmenus.header("Sheet (%s)" % t.Label, "HeaderSheet")] + _tree_tail(view, t.Document, t)))
    from . import drawsheet
    editing = drawsheet.editing_format(page)
    out = [rcmenus.header("Sheet (%s)" % t.Label, "HeaderSheet"),
           rcmenus.action("DisplayGrid", rcmenus.T_DISPLAY_GRID, lambda: X().toggle_grid(page), checked=X().grid_on(page))]
    if editing:
        out += [prefer(P + "TitleBlockFields", "TitleBlockFields", "Title Block Fields...",
                       lambda: X().title_block_fields(page)),
                prefer(P + "AutomaticBorder", "AutomaticBorder", "Automatic Border...",
                       lambda: X().automatic_border_dialog(page)),
                _cmd(P + "EditSheet", "EditSheet", "Edit Sheet")]
    else:
        locked = X().sheet_focus_locked(page)
        out += [_cmd(P + "EditSheetFormat", "EditSheetFormat", "Edit Sheet Format"),
                rcmenus.action("LockSheetFocus", "Unlock Sheet Focus" if locked else "Lock Sheet Focus",
                               lambda: X().toggle_sheet_focus(page))]
    out += [_cmd(P + "AddSheet", "AddSheet", "Add Sheet..."),
            rcmenus.action("CopySheet", "Copy", lambda: X().copy_sheet(page)),
            rcmenus.action("DeleteSheet", rcmenus.T_DELETE, lambda: X().delete_object(page)),
            _cmd(P + "SheetProperties", "SheetProperties", "Properties..."),
            rs_options(), rcmenus.separator()]
    return _clean(_live(out + _tree_tail(view, t.Document, page)))


def show_tree_menu(target, pos, view=None):
    if target.isDerivedFrom("TechDraw::DrawTemplate"):
        return rcmenus.show(rcmenus.Builder("DrawTreeFormat", tree_format_items(target, view), line_before_customize=True), pos)
    if target.isDerivedFrom("TechDraw::DrawPage"):
        return rcmenus.show(rcmenus.Builder("DrawTreeSheet", tree_sheet_items(target, view), line_before_customize=True), pos)
    if target.isDerivedFrom("TechDraw::DrawViewPart"):
        if target.Name not in [o.Name for o in Gui.Selection.getSelection()]:
            pick(target)
        return rcmenus.show(rcmenus.Builder("DrawTreeView", tree_view_items(target, view)), pos)
    if getattr(target, "SWAnnotationsFolder", False):
        return rcmenus.show(rcmenus.Builder("DrawTreeAnnotations", tree_annotations_items(target, view),
                                            line_before_customize=True), pos)
    items = tree_annotation_row_items(target, view)
    if items is not None:
        return rcmenus.show(rcmenus.Builder("DrawTree" + _kind(target).title(), items), pos)
    return None


def tree_annotations_items(folder, view=None):
    """The drawing's Annotations folder (first in the tree): it heads its menu and has the tree's own commands. It got
    the part feature menu before (Configure Feature, Parent/Child..., FeatureWorks...: none of them reach a drawing
    folder; pkg217)."""
    return _clean([rcmenus.header("Annotations", "HeaderAnnotations")] + _tree_tail(view, folder.Document, folder))


def tree_annotation_row_items(obj, view=None):
    """A dimension, note, balloon or table row in the drawing's tree: the menu it has on the sheet, then the tree's
    own commands (Go To..., Zoom to Selection, Collapse Items, Hide/Show Tree Items...). These rows got the part
    feature menu before: What's Wrong?, Configure Feature, Parent/Child..., FeatureWorks... (pkg217)."""
    kind = _kind(obj)
    if kind == "dimension":
        items = dimension_items(obj)
    elif kind in ("annotation", "label"):
        items = annotation_items(obj, _label_view(obj))
    elif kind == "table":
        items = table_items(obj)        # the whole table: no cell under the pointer in the tree
    else:
        return None             # anything else keeps its own menu
    # the sheet's own rows (Select Other, Selection Tools, Zoom/Pan/Rotate, Recent Commands; Smart Dimension and the

    items = [i for i in items if getattr(i, "key", "") not in TREE_ROW_DROP]
    return _clean(list(items) + [rcmenus.separator()] + _tree_tail(view, obj.Document, obj))


TREE_ROW_DROP = ("SelectOther", "SelectionTools", "ZoomPanRotate", "RecentCommands", "SmartDimension", "MoreDimensions",
                 "Annotations", "DrawingViews", "Tables")


def hook_tree():
    """The tree rows of a drawing's sheets and views go through show_tree_menu (fmmenu.show hook)."""
    from . import fmmenu
    if getattr(fmmenu, "_fw_draw_tree_menu", False):
        return
    original = fmmenu.show

    def show(shell, target, global_pos, view=None, *more, **named):
        try:
            if not (QtWidgets.QApplication.keyboardModifiers() & Qt.ShiftModifier) and \
                    isinstance(target, App.DocumentObject) and (target.isDerivedFrom("TechDraw::DrawPage")
                                                                or target.isDerivedFrom("TechDraw::DrawTemplate")
                                                                or target.isDerivedFrom("TechDraw::DrawView")
                                                                or getattr(target, "SWAnnotationsFolder", False)):
                if not Gui.Selection.isSelected(target):
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(target)
                menu = show_tree_menu(target, global_pos, view)
                if menu is not None:
                    fmmenu.LAST[0] = menu
                    return menu
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: drawing tree menu: %s\n" % error)
        return original(shell, target, global_pos, view, *more, **named)

    fmmenu.show = show
    fmmenu._fw_draw_tree_menu = True
    try:
        hook_pick_bar()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing context toolbar: %s\n" % error)


# --------------------------------------------------------------------------- the pick's context toolbar
def bar_for(v, sub=""):
    """A drawing view picked (or an edge in it): the icons over its shortcut menu (read 3 RC1/RC2),
    as the left-click context toolbar."""
    edge = None
    leaf = (sub or "").split(".")[-1]
    if leaf.startswith("Edge"):
        try:
            edge = int(leaf[4:])
        except ValueError:
            edge = None
    return list(view_row(v, edge)[0])


def _drawing_viewport(shell):
    mdi = shell.window.findChild(QtWidgets.QMdiArea) if shell is not None else None
    sub = (mdi.activeSubWindow() or mdi.currentSubWindow()) if mdi is not None else None
    w = sub.widget() if sub is not None else None
    if w is None or w.findChildren(QtWidgets.QWidget, "") is None:
        return None
    for g in w.findChildren(QtWidgets.QGraphicsView):
        return g.viewport()
    return None


def hook_pick_bar():
    from . import contextbar
    if getattr(contextbar, "_fw_draw_bar", False):
        return
    original = contextbar.part_entries

    def part_entries(shell, obj, sub, *more, **named):
        try:
            if isinstance(obj, App.DocumentObject) and obj.isDerivedFrom("TechDraw::DrawViewPart"):
                return bar_for(obj, sub)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drawing bar: %s\n" % error)
        return original(shell, obj, sub, *more, **named)
    contextbar.part_entries = part_entries

    original_attach = contextbar.ContextBar.attach

    def attach(self, *args, **named):
        out = original_attach(self, *args, **named)
        try:
            vp = _drawing_viewport(self.shell)      # a drawing's page: clicks there bring the bar too
            if vp is not None and vp not in self._watched:
                vp.installEventFilter(self)
                self._watched.append(vp)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drawing bar clicks: %s\n" % error)
        return out
    contextbar.ContextBar.attach = attach
    contextbar._fw_draw_bar = True
    sh = rcmenus.shell()
    bar = getattr(sh, "context", None) if sh is not None else None
    if bar is not None and getattr(bar, "mdi", None) is not None:
        # the bar made before this hook connected its own attach: switch it to this one
        try:
            bar.mdi.subWindowActivated.disconnect(bar.attach)
        except Exception as _fw_err:
            _fw_log("drawmenu.py:1158", _fw_err)
        bar.mdi.subWindowActivated.connect(lambda *a, b=bar: attach(b, *a))


class DrawMenu(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self._watched = []
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        sub = self.mdi.activeSubWindow() if self.mdi is not None else None
        if sub is None or sub.widget() is None:
            return
        for view in sub.widget().findChildren(QtWidgets.QGraphicsView):
            if view.inherits("QOpenGLWidget"):
                continue
            vp = view.viewport()
            if vp is None or vp in self._watched:
                continue
            vp.installEventFilter(self)
            self._watched.append(vp)

    def remove(self):
        for w in self._watched:
            if alive(w):
                w.removeEventFilter(self)
        self._watched = []

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
            try:
                self._left_click(obj, event, t == QtCore.QEvent.MouseButtonPress)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: drawing context toolbar: %s\n" % error)
            return False
        if t != QtCore.QEvent.ContextMenu:
            return False
        try:
            if not getattr(self.shell, "enabled", True) or _page() is None:
                return False
            if event.modifiers() & Qt.ShiftModifier:
                return False
            view = obj.parent()
            if not isinstance(view, QtWidgets.QGraphicsView):
                return False
            h = hits(view, event.pos())
            kind, hit, extra = h[0] if h else (None, None, None)
            if kind == "other":
                return False
            _LAST.update(view=view, pos=event.pos())
            pos = event.globalPos()
            QtCore.QTimer.singleShot(0, lambda: show_menu(pos, kind, hit, extra))
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: drawing sheet menu: %s\n" % error)
            return False


    def _left_click(self, obj, event, press):
        ""

        if event.button() != Qt.LeftButton or event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier):
            self._press = None
            return
        if press:
            self._press = event.pos()
            return
        start, self._press = getattr(self, "_press", None), None
        if start is None or (event.pos() - start).manhattanLength() > 4:
            return
        if not getattr(self.shell, "enabled", True) or _page() is None or not context_on_selection():
            return
        view = obj.parent()
        if not isinstance(view, QtWidgets.QGraphicsView):
            return
        h = [x for x in hits(view, event.pos()) if x[0] in ("edge", "view")]
        if not h:
            return
        kind, v, extra = h[0]
        row = view_row(v, extra if kind == "edge" else None)
        entries = list(row[0]) + list(row[1])
        bar = getattr(self.shell, "context", None)
        if not entries or bar is None:
            return
        pos = event.globalPos()
        LEFT_BAR[:] = [entry.key for entry in entries]
        QtCore.QTimer.singleShot(60, lambda: bar.popup("drawing", entries, pos))


LEFT_BAR = []       # keys on the last drawing context toolbar (checks)


def context_on_selection():
    try:
        from . import customizedlg
        return bool(customizedlg.option("ShowOnSelection"))
    except Exception:
        return True


_menu = []


def install(shell=None):
    if shell is None:
        shell = rcmenus.shell()
    if shell is None:
        return None
    if _menu and _menu[0].shell is shell:
        _menu[0].attach()
        return _menu[0]
    remove()
    _menu.append(DrawMenu(shell))
    try:
        hook_tree()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing tree menu hook: %s\n" % error)
    try:
        X().install_paste()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet paste: %s\n" % error)
    return _menu[0]


def remove():
    while _menu:
        _menu.pop().remove()
