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
import os
import sys

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
REZ = 10.0

ORIENTATIONS = {   # name -> (direction to the viewer, view X)
    "Front": (V(0, -1, 0), V(1, 0, 0)), "Back": (V(0, 1, 0), V(-1, 0, 0)),
    "Top": (V(0, 0, 1), V(1, 0, 0)), "Bottom": (V(0, 0, -1), V(1, 0, 0)),
    "Right": (V(1, 0, 0), V(0, 1, 0)), "Left": (V(-1, 0, 0), V(0, -1, 0)),
    "Isometric": (V(1, -1, 1), V(1, 1, 0)), "Trimetric": (V(0.62, -0.78, 0.5), V(0.78, 0.62, 0)),
    "Dimetric": (V(0.35, -0.94, 0.4), V(0.94, 0.35, 0)),
}
DISPLAY_STYLES = ("Wireframe", "Hidden Lines Visible", "Hidden Lines Removed", "Shaded With Edges", "Shaded")


def pixmap(name):
    """A command icon that FreeCAD finds whether or not TechDraw has been opened yet: TechDraw's icons live in
    its own module's resources under actions/, so the bare name alone gave "Cannot find icon". TechDraw's GUI
    is not loaded while FreeCAD starts (about 0.4 s before the window shows): the icon's path is given ahead
    and the icons are set on the commands' actions once TechDraw's GUI is loaded, just after start-up."""
    if not name or name.startswith(":") or "/" in name:
        return name
    name = ICON_ALIASES.get(name, name)
    if "TechDrawGui" not in sys.modules:
        for path in (":/icons/%s.svg" % name, ":/icons/actions/%s.svg" % name):
            if QtCore.QFile.exists(path):
                return path          # FreeCAD's own icons are there from the start
        _icons_later(name)
        if name.startswith("Constraint_"):
            return ":/icons/constraints/%s.svg" % name
        if name.startswith("Sketcher_"):
            if name[9:] in SKETCHER_TOOLS:
                return ":/icons/tools/%s.svg" % name
            if "Create" in name or name[9:] in ("Projection", "CarbonCopy", "Trimming", "Intersection", "Extend",
                                                "Split", "ToggleConstruction"):
                return ":/icons/geometry/%s.svg" % name
            return ":/icons/%s.svg" % name
        if name.startswith("TechDraw_Extension") or name.startswith("TechDraw_") and "Dimension" in name or \
                name in TECHDRAW_ROOT or name.startswith("TechDraw_Tree") or \
                name.startswith("TechDraw_Proj") and not name.startswith("TechDraw_Projection") and \
                name != "TechDraw_ProjectShape":
            return _ahead(":/icons/%s.svg" % name, name)     # TechDraw keeps these at the root, not under actions/
        return _ahead(":/icons/actions/%s.svg" % name, name)
    if name.startswith("Sketcher_"):
        try:
            import SketcherGui  # noqa: F401  (the Sketcher's icons, for the sheet sketch tools)
        except Exception as _fw_err:
            _fw_log("drawings.py:79", _fw_err)
    return _found(name)


def _ahead(path, name):
    """path while TechDraw's resources are not loaded yet would print "Cannot find icon" at start-up (stock FreeCAD
    prints nothing): a blank stand-in file of the same name is given instead, and load_icons puts the real icon on
    the command once TechDraw's GUI is loaded."""
    if QtCore.QFile.exists(path):
        return path
    try:
        folder = os.path.join(App.getUserCachePath(), "FreeCAD-icons-ahead")
        os.makedirs(folder, exist_ok=True)
        f = os.path.join(folder, "%s.svg" % name)
        if not os.path.isfile(f):
            with open(f, "w", encoding="utf-8") as out:
                out.write('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"/>\n')
        return f.replace("\\", "/")
    except Exception as _fw_err:
        _fw_log("drawings.py:icon ahead", _fw_err)
        return path


SKETCHER_TOOLS = ("Symmetry", "RectangularArray", "Copy", "Move", "Rotate", "Scale", "Offset", "Clone",
                  "Translate")     # the Sketcher keeps these icons under tools/


def real_pixmap(name):
    """The resource path of a TechDraw (or FreeCAD) icon once TechDraw's GUI is loaded, else "" (never the blank
    stand-in file _ahead gives at start-up)."""
    if not name:
        return ""
    if name.startswith(":"):
        return name if QtCore.QFile.exists(name) else ""
    name = ICON_ALIASES.get(name, name)
    if name.startswith("TechDraw") and "TechDrawGui" not in sys.modules:
        try:
            import TechDrawGui  # noqa: F401  (its icon resources)
        except Exception:
            return ""
    path = _found(name)
    return path if path.startswith(":") else ""


def _found(name):
    for path in (":/icons/actions/%s.svg" % name, ":/icons/%s.svg" % name, ":/icons/geometry/%s.svg" % name,
                 ":/icons/tools/%s.svg" % name, ":/icons/constraints/%s.svg" % name):
        if QtCore.QFile.exists(path):
            return path
    return name


_LATER = {"names": set(), "timer": None}


def _icons_later(name):
    _LATER["names"].add(name)
    if _LATER["timer"] is None:
        t = QtCore.QTimer()
        t.setSingleShot(True)
        t.timeout.connect(load_icons)
        t.start(1500)
        _LATER["timer"] = t


def load_icons():
    """Loads TechDraw's GUI (its icon resources) and puts the icons on the add-on's drawing commands."""
    try:
        import TechDrawGui      # noqa: F401  (registers TechDraw's icon resources)
        import SketcherGui      # noqa: F401
    except Exception as _fw_err:
        _fw_log("drawings.py:114", _fw_err)
    detail_tree_icon()
    names = _LATER["names"]
    for cmd in Gui.listCommands():
        if not cmd.startswith("FreeWorks_") and not cmd.startswith("SWStyle_"):
            continue
        try:
            c = Gui.Command.get(cmd)
            res = c.getInfo() if c is not None else None
            pm = (res or {}).get("pixmap", "")
        except Exception:
            continue
        pm = str(pm).replace("\\", "/")
        bare = pm.rsplit("/", 1)[-1][:-4] if (pm.startswith(":/icons/") or "/FreeCAD-icons-ahead/" in pm) \
            and pm.endswith(".svg") else None
        if bare not in names:
            continue
        path = _found(bare)
        if not path.startswith(":"):
            continue
        try:
            icon = QtGui.QIcon(path)
            for a in c.getAction() or ():
                a.setIcon(icon)
        except Exception as _fw_err:
            _fw_log("drawings.py:137", _fw_err)
    drawn_command_icons()


_DRAWN_BY_CMD = {}


def drawn_icon(name):
    ""

    try:
        from . import catalog, icons
        if not _DRAWN_BY_CMD:
            for cmd in catalog.ALL:
                if cmd.key.startswith("Draw") and not cmd.icon:
                    for n in cmd.natives:
                        _DRAWN_BY_CMD.setdefault(n, cmd.key)
            _DRAWN_BY_CMD.setdefault("", "")
        key = _DRAWN_BY_CMD.get(name)
        if not key or not hasattr(icons, "drawn"):
            return None
        icon = icons.drawn(key)
        return icon if icons.paints(icon) else None
    except Exception as _fw_err:
        _fw_log("drawings.py:drawn_icon", _fw_err)
        return None


def drawn_command_icons():
    """The drawn pictures on the drawing commands' own actions (menus and toolbars made from them)."""
    n = 0
    drawn_icon("")
    for name, key in list(_DRAWN_BY_CMD.items()):
        if not key:
            continue
        icon = drawn_icon(name)
        if icon is None:
            continue
        try:
            c = Gui.Command.get(name)
            for a in (c.getAction() or ()) if c is not None else ():
                a.setIcon(icon)
                n += 1
        except Exception as _fw_err:
            _fw_log("drawings.py:drawn_command_icons", _fw_err)
    return n


def detail_tree_icon():
    ""



    try:
        import TechDrawGui      # noqa: F401
    except Exception as _fw_err:
        _fw_log("drawings.py:detail_tree_icon import", _fw_err)
    data, fmt = None, "SVG"
    f = QtCore.QFile(":/icons/TechDraw_TreeView.svg")
    if f.open(QtCore.QIODevice.ReadOnly):
        data = bytes(f.readAll()).decode("utf-8", "ignore")
        f.close()
    if not data:
        try:
            from PySide import QtGui
            pm = Gui.BitmapFactory().pixmap("TechDraw_TreeView")
            if pm is None or pm.isNull():
                pm = QtGui.QIcon(":/icons/TechDraw_TreeView.svg").pixmap(64, 64)
            if pm is not None and not pm.isNull():
                buf = QtCore.QBuffer()
                buf.open(QtCore.QIODevice.WriteOnly)
                pm.save(buf, "PNG")
                data, fmt = bytes(buf.data()), "PNG"
        except Exception as _fw_err:
            _fw_log("drawings.py:detail_tree_icon png", _fw_err)
    if not data:
        return False
    done = False
    for name in ("actions/TechDraw_DetailView", "TechDraw_DetailView"):   # what TechDraw's detail view provider asks for
        try:
            Gui.addIcon(name, data, fmt)
            done = done or Gui.isIconCached(name)
        except Exception as _fw_err:
            _fw_log("drawings.py:detail_tree_icon addIcon", _fw_err)
    return done


TECHDRAW_ROOT = ("TechDraw_Balloon", "TechDraw_Lock", "TechDraw_Pages", "TechDraw_CameraOrientation",
                 "TechDraw_RefError")    # TechDraw 1.1 icons at :/icons/, not :/icons/actions/
ICON_ALIASES = {"TechDraw_2LineCenterLine": "TechDraw_2LineCenterline", "TechDraw_Spreadsheet": "TechDraw_SpreadsheetView"}


# --------------------------------------------------------------------------- the sheet
def active_page():
    """The sheet shown in the active window, else the first sheet of the active document, else None."""
    doc = App.ActiveDocument
    if doc is None:
        return None
    # extapps/69: asked about 100 times a second by command states and pollers while a drawing is open, and each
    # ask walked the window tree and every object: kept until the event loop runs again, per document, object
    # count and front window
    try:
        area = _mdi_area()
        mdi = area.activeSubWindow() if area is not None else None
        from . import tickcache
        return tickcache.get(("active_page", doc.Name, len(doc.Objects), id(mdi)), lambda: _active_page(doc, mdi))
    except Exception:
        return _active_page(doc, None, look=True)


_AREA = [None]


def _mdi_area():
    area = _AREA[0]
    try:
        try:
            from shiboken6 import isValid
        except ImportError:
            from shiboken2 import isValid
        if area is not None and isValid(area):
            return area
    except Exception:
        pass
    area = _AREA[0] = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    return area


def _active_page(doc, mdi, look=False):
    if look:
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow()
        except Exception:
            mdi = None
    try:
        title = mdi.windowTitle() if mdi is not None else ""
    except Exception:
        title = ""
    pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
    try:
        import TechDrawGui
        widget = mdi.widget() if mdi is not None else None
        shown = widget.findChildren(QtWidgets.QGraphicsView) if widget is not None else []
        scenes = [v.scene() for v in shown]
        for p in pages:
            scene = TechDrawGui.getSceneForPage(p)
            if scene is not None and scene in scenes:
                return p
    except Exception as _fw_err:
        _fw_log("drawings.py:190", _fw_err)
    for p in pages:
        if p.Label and p.Label in title:
            return p
    return pages[0] if pages else None


def in_drawing():
    """True when the active document is a drawing (has a sheet) and a sheet window is in front."""
    page = active_page()
    return page is not None and page_view(page) is not None


def sheet_shown(page):
    ""
    return page_view(page) is not None


def page_view(page):
    """The QGraphicsView that shows page, else None."""
    try:
        import TechDrawGui
        scene = TechDrawGui.getSceneForPage(page)
        views = scene.views() if scene is not None else []
        return next((v for v in views if v.isVisible()), None)
    except Exception as _fw_err:
        _fw_log("drawings.py:233", _fw_err)
        return None


def to_sheet(pt):
    """Scene point -> sheet millimetres."""
    return (pt.x() / REZ, -pt.y() / REZ)


def to_scene(x, y):
    return QtCore.QPointF(x * REZ, -y * REZ)


def sheet_size(page):
    try:
        return float(page.Template.Width), float(page.Template.Height)
    except Exception:
        return 279.4, 215.9


def views_of(page):
    return [v for v in page.Views if v.isDerivedFrom("TechDraw::DrawViewPart")]


def view_position(v):
    """The view's centre on the sheet (a projection group member: the group's place plus its own)."""
    x, y = float(v.X), float(v.Y)
    for o in v.InList:
        if o.TypeId == "TechDraw::DrawProjGroup":
            x, y = x + float(o.X), y + float(o.Y)
    return x, y


def model_shapes(doc):
    """What a view of doc shows: the assembly, else the visible bodies, else the top-level shapes (links from
    drawings in other files do not count)."""
    tops = [o for o in doc.Objects if o.TypeId == "Assembly::AssemblyObject"]
    if tops:
        return tops[:1]
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    if bodies:
        return [b for b in bodies if getattr(b, "Visibility", True)] or bodies
    tops = [o for o in doc.Objects if o.isDerivedFrom("Part::Feature") and o.Visibility
            and not any(i.Document is doc for i in o.InList)][:20]
    try:                        # a weldment: its bodies are the trimmed members inside the Structural Members
        from . import wemember
        if wemember.structural_members(doc):
            from . import wecutlist
            seen, out = set(), []
            for _k, _p, o in wecutlist.entries(doc):
                if o.Name not in seen:
                    seen.add(o.Name)
                    out.append(o)
            if out:
                return out + [o for o in tops if o.Name not in seen]
    except Exception as _fw_err:
        _fw_log("drawings.py:271", _fw_err)
    return tops


MADE_FROM = "FreeWorks:MadeFrom"


def set_made_from(doc, source):
    """Remembers the model a drawing was made from (Make Drawing from Part/Assembly)."""
    try:
        meta = dict(doc.Meta)
        meta[MADE_FROM] = source.FileName or source.Name
        doc.Meta = meta
    except Exception as _fw_err:
        _fw_log("drawings.py:285", _fw_err)


def drawing_model(doc):
    """The open model document drawing doc shows: its views' model, else the one it was made from."""
    if doc is None:
        return None
    try:
        from . import drawviews as DV
        for o in doc.Objects:
            if o.isDerivedFrom("TechDraw::DrawViewPart"):
                for s in DV.xsource(o):
                    if s.Document is not doc:
                        return s.Document
    except Exception as _fw_err:
        _fw_log("drawings.py:300", _fw_err)
    try:
        made = dict(doc.Meta).get(MADE_FROM, "")
    except Exception:
        made = ""
    if made:
        for d in App.listDocuments().values():
            if d is not doc and (d.Name == made or (d.FileName and os.path.normcase(os.path.abspath(d.FileName)) ==
                                                    os.path.normcase(os.path.abspath(made)))):
                return d
    return None


def source_documents():
    """The open documents with a part or an assembly in them (not drawings)."""
    from . import newdoc
    out = []
    for name in App.listDocuments():
        doc = App.getDocument(name)
        if any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
            continue
        if model_shapes(doc):
            out.append(doc)
    return out


def _unit(v):
    v = V(v)
    return v * (1.0 / v.Length) if v.Length > 1e-12 else v


def view_frame(v):
    """(direction to the viewer, view X, view Y) of a part view."""
    d = _unit(v.Direction)
    x = V(v.XDirection)
    x = _unit(x - d * x.dot(d)) if x.Length > 1e-12 else _unit(d.cross(V(0, 0, 1)) if abs(d.z) < 0.99
                                                               else V(1, 0, 0))
    return d, x, d.cross(x)


def projected_frame(parent, dx, dy, third_angle=True):
    ""

    d, x, y = view_frame(parent)
    ax, ay = abs(dx), abs(dy)
    s = 1.0 if third_angle else -1.0
    if ax > 1e-9 and ay > 1e-9 and min(ax, ay) / max(ax, ay) > 0.5:
        sx = math.copysign(1.0, dx) * s
        sy = math.copysign(1.0, dy) * s
        nd = _unit(d + x * sx + y * sy)
        nx = _unit(x - nd * x.dot(nd))
        return nd, nx, "Isometric"
    if ax >= ay:
        side = 1.0 if dx > 0 else -1.0
        nd = x * (side * s)
        return nd, d * (-side * s), "Right" if side > 0 else "Left"
    side = 1.0 if dy > 0 else -1.0
    nd = y * (side * s)
    return nd, x, "Top" if side > 0 else "Bottom"


def system_option(page_name, text, default):
    """A System Options value (features' optionspages: Drawings > Display Style, Area Hatch/Fill, Performance)."""
    try:
        from . import optionspages
        return optionspages.stored(page_name, text, default)
    except Exception:
        return default


OPTION_STYLES = {"wireframe": "Wireframe", "hidden lines visible": "Hidden Lines Visible",
                 "hidden lines removed": "Hidden Lines Removed", "shaded with edges": "Shaded With Edges",
                 "shaded": "Shaded"}


def new_view_style():
    """System Options > Drawings > Display Style > Display style: the style new views start with."""
    return OPTION_STYLES.get(str(system_option("Display Style", "Display style", "Hidden lines removed")).lower(),
                             "Hidden Lines Removed")


def new_view_options(v):
    """System Options > Drawings > Display Style: Tangent edges and Edge quality for new views."""
    tangent = {"visible": "Visible", "use font": "With Font", "removed": "Removed"}.get(
        str(system_option("Display Style", "Tangent edges", "Visible")).lower(), "Visible")
    try:
        if tangent == "Visible":
            v.SmoothVisible = True
        else:
            from . import drawviewcmds
            drawviewcmds.set_tangent_edges(v, tangent)
    except Exception as _fw_err:
        _fw_log("drawings.py:392", _fw_err)
    try:
        v.CoarseView = str(system_option("Display Style", "Edge quality for new views", "High quality")) == "Draft quality"
    except Exception as _fw_err:
        _fw_log("drawings.py:396", _fw_err)


def new_view(page, source, direction, xdir, at, scale=None, style=None, label=None):
    """A part view on page at sheet point at."""
    doc = page.Document
    from . import newdoc
    newdoc._serial_projections()
    v = doc.addObject("TechDraw::DrawViewPart", "View")
    page.addView(v)
    first = not any(o is not v for o in views_of(page))
    link_source(v, source)
    v.Direction = direction
    v.XDirection = xdir
    if scale is not None:
        v.ScaleType = "Custom"
        v.Scale = scale
    else:

        if first:
            fit_sheet_scale(page, source)
        v.ScaleType = "Page"
    if first:
        name_after_model(page, source)
    set_scale_mode(v, "Sheet" if scale is None else "Custom")
    set_display_style(v, style or new_view_style())
    new_view_options(v)
    v.X, v.Y = at
    if label:
        v.Label = label
    else:
        v.Label = _next_label(page)
    return v


STANDARD_SCALES = (100.0, 50.0, 20.0, 10.0, 5.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.2, 0.1, 0.05, 0.04, 0.02, 0.01,
                   0.005, 0.002, 0.001)


def scale_text(s):
    ""
    s = float(s)
    if s >= 1:
        return "%g:1" % round(s, 4)
    return "1:%g" % round(1.0 / s, 4)


def parse_scale(text):
    """1:2, 2:1, 0.5 -> a factor, else None."""
    try:
        t = str(text).replace(" ", "")
        if ":" in t:
            a, b = t.split(":", 1)
            return float(a) / float(b)
        return float(t)
    except Exception:
        return None


def model_box(source):
    box = None
    for o in (source or []):
        try:
            b = o.Shape.BoundBox
        except Exception:
            continue
        if b.isValid():
            box = App.BoundBox(b) if box is None else (box.add(b) or box)
    return box


def fit_scale(page, source):
    ""

    box = model_box(source)
    if box is None:
        return None
    w, h = sheet_size(page)
    across = max(box.XLength + box.YLength, 1e-6)       # front + right, side by side
    down = max(box.ZLength + box.YLength, 1e-6)          # front + top, one above the other
    want = min(0.62 * w / across, 0.55 * h / down)
    for s in STANDARD_SCALES:
        if s <= want:
            return s
    return STANDARD_SCALES[-1]


def auto_scale():
    """System Options > Drawings > Automatically scale new drawing views (on unless turned off)."""
    try:
        from . import optionspages
        return bool(optionspages.stored("Drawings", "Automatically scale new drawing views", True))
    except Exception:
        return True


def fit_sheet_scale(page, source):
    if not auto_scale():
        return None                 # the first view keeps the sheet's scale
    s = fit_scale(page, source)
    if s is not None:
        try:
            page.Scale = s
        except Exception as _fw_err:
            _fw_log("drawings.py:489", _fw_err)
    return s


DWG_FIELDS = ("DWG_NO", "DWG NO", "DWGNO", "DRAWING_NUMBER", "DRAWING_NO", "DRAWINGNUMBER", "DOCUMENT_NUMBER",
              "PART_NUMBER", "PARTNUMBER", "DN")


def name_after_model(page, source):
    ""

    try:
        objs = list(source or [])
        if not objs:
            return
        model = objs[0].Document
        doc = page.Document
        if model is doc:
            return
        name = model.Label
        if is_temp(doc) or doc.Label.startswith("Draw"):
            doc.Label = name
        tpl = page.Template
        texts = dict(getattr(tpl, "EditableTexts", {}) or {})
        changed = False
        for k in list(texts):
            key = k.upper().replace(" ", "_")
            if any(key == f.replace(" ", "_") or key.endswith(f.replace(" ", "_")) for f in DWG_FIELDS):
                if not texts[k].strip() or texts[k].strip() in ("...", "DWG NO", "XXX", "0", "Drawing number"):
                    texts[k] = name
                    changed = True
        if changed:
            tpl.EditableTexts = texts
    except Exception as error:
        App.Console.PrintLog("FreeCAD: drawing name: %s\n" % error)


def set_scale_mode(v, mode):
    ""
    try:
        if "SWScaleMode" not in v.PropertiesList:
            v.addProperty("App::PropertyString", "SWScaleMode", "FreeCAD", "Use parent / sheet / custom scale")
        v.SWScaleMode = mode
    except Exception as _fw_err:
        _fw_log("drawings.py:533", _fw_err)


def _next_label(page):
    ""
    used = {o.Label for o in page.Document.Objects}
    n = 1
    while "Drawing View%d" % n in used:
        n += 1
    return "Drawing View%d" % n


def set_display_style(v, style):
    ""
    hidden = style in ("Wireframe", "Hidden Lines Visible")
    try:
        if bool(v.HardHidden) != hidden:
            v.HardHidden = hidden
            _settle_hidden(v.Document.Name, v.Name)

        v.SmoothVisible = (getattr(v, "SWTangentEdges", "") or "Visible") == "Visible"
    except Exception as _fw_err:
        _fw_log("drawings.py:553", _fw_err)
    try:
        if not hasattr(v, "SWDisplayStyle"):
            v.addProperty("App::PropertyString", "SWDisplayStyle", "FreeCAD", "Display Style")
        was = v.SWDisplayStyle
        v.SWDisplayStyle = style
    except Exception:
        was = ""
    if style in ("Shaded", "Shaded With Edges") or was in ("Shaded", "Shaded With Edges"):
        try:
            from . import drawshade
            drawshade.apply(v, style)        # TechDraw draws lines only: a shaded picture under them
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: shaded view: %s\n" % error)


def _settle_hidden(doc_name, name, tries=0):
    """Hidden lines shown or taken off while TechDraw is still working the view out (a view just made) were
    lost: TechDraw skips a recompute while its hidden line pass runs and then shows what that pass found
    (vd112, 11-20). Once the view has its lines, it is worked out again if they don't match its style."""
    doc = App.listDocuments().get(doc_name)
    v = doc.getObject(name) if doc is not None else None
    if v is None:
        return
    try:
        if not v.getVisibleEdges() and tries < 120:
            QtCore.QTimer.singleShot(500, lambda: _settle_hidden(doc_name, name, tries + 1))
            return
        if bool(v.HardHidden) != bool(v.getHiddenEdges()):
            v.touch()
            doc.recompute([v])
    except Exception as _fw_err:
        _fw_log("drawings settle hidden", _fw_err)


def _name_orientation(v, name):
    ""
    try:
        if "SWOrientation" not in v.PropertiesList:
            v.addProperty("App::PropertyString", "SWOrientation", "FreeCAD", "named view")
        v.SWOrientation = name
    except Exception as _fw_err:
        _fw_log("drawings.py:576", _fw_err)


def standard_3_view(page, source, third_angle=None):
    ""


    from . import newdoc
    shapes = model_shapes(source) if hasattr(source, "Objects") else list(source)
    if not shapes:
        return None
    try:
        if third_angle is not None:
            page.ProjectionType = "Third angle" if third_angle else "First angle"
    except Exception as _fw_err:
        _fw_log("drawings.py:591", _fw_err)
    third = globals()["third_angle"](page)
    newdoc._serial_projections()
    w, h = sheet_size(page)
    box = model_box(shapes)
    if not views_of(page):
        fit_sheet_scale(page, shapes)
    k = float(page.Scale)
    bx = box.XLength if box else 50.0
    by = box.YLength if box else 50.0
    bz = box.ZLength if box else 50.0
    gap = max(15.0, 0.12 * min(w, h))
    fx, fy = w * 0.36, h * 0.40
    if not third:
        fx, fy = w - fx, h - fy          # first angle: top goes below and right to the left, so Front sits upper right
    sx = 1.0 if third else -1.0
    # before Front is made: it goes where the three views fit, and "empty" means no view on the sheet yet
    fx, fy, k = _clear_of_title_block(page, fx, fy, k, bx, by, bz, gap, sx,
                                      empty=not views_of(page) and auto_scale())
    d, x = ORIENTATIONS["Front"]
    front = new_view(page, shapes, _unit(d), _unit(x), (fx, fy))
    _name_orientation(front, "Front")
    top_at = (fx, fy + sx * (bz * k / 2 + gap + by * k / 2))
    right_at = (fx + sx * (bx * k / 2 + gap + by * k / 2), fy)
    made = [front]
    for name, at in (("Top", top_at), ("Right", right_at)):
        nd, nx = ORIENTATIONS[name]
        v = new_view(page, shapes, _unit(nd), _unit(nx), at)
        _name_orientation(v, name)
        follow_parent_scale(v, front)
        set_parent(v, front)
        made.append(v)
    page.Document.recompute()
    return front


def _three_view_box(fx, fy, k, bx, by, bz, gap, sx):
    """(x0, y0, x1, y1) sheet mm taken by Front at (fx, fy) and its Top and Right views at scale k."""
    ty = fy + sx * (bz * k / 2 + gap + by * k / 2)
    rx = fx + sx * (bx * k / 2 + gap + by * k / 2)
    boxes = ((fx - bx * k / 2, fy - bz * k / 2, fx + bx * k / 2, fy + bz * k / 2),
             (fx - bx * k / 2, ty - by * k / 2, fx + bx * k / 2, ty + by * k / 2),
             (rx - by * k / 2, fy - bz * k / 2, rx + by * k / 2, fy + bz * k / 2))
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _clear_of_title_block(page, fx, fy, k, bx, by, bz, gap, sx, empty=True):
    ""


    try:
        from . import drawauto
        w, h = sheet_size(page)
        tb = drawauto.title_block(page)
        for _try in range(len(STANDARD_SCALES)):
            u = _three_view_box(fx, fy, k, bx, by, bz, gap, sx)
            got = drawauto._place_union(u, w, h, tb)
            if got is not None:
                return fx + got[0], fy + got[1], k
            smaller = [s for s in STANDARD_SCALES if s < k - 1e-9] if empty else []
            if not smaller:
                break
            k = smaller[0]
            page.Scale = k
    except Exception as _fw_err:
        _fw_log("drawings.py:three_view_fit", _fw_err)
    return fx, fy, k


def sheet_defaults(page):
    ""

    try:
        if getattr(page, "FreeWorksSheet", False):
            return
        tpl = getattr(page.Template, "Template", "") or ""
        name = tpl.replace("\\", "/").rsplit("/", 1)[-1].upper()
        if "ANSI" in name or "ASME" in tpl.upper():
            page.ProjectionType = "Third angle"
        page.addProperty("App::PropertyBool", "FreeWorksSheet", "FreeCAD", "Sheet set up with a standard title block and projection")
        page.FreeWorksSheet = True
        default_field_links(page)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet defaults: %s\n" % error)


SHEET_FIELDS = {"sheet": 'SHEET $PRP:"FW-Current Sheet" OF $PRP:"FW-Total Sheets"',
                "scale": 'SCALE $PRP:"FW-Sheet Scale"',
                # FreeCAD's ISO 5457 / 7200 formats: "Sheet: n / m" (it showed TechDraw's "0 / 2")
                "sheet_number": '$PRP:"FW-Current Sheet" / $PRP:"FW-Total Sheets"'}

# model, $PRPSHEET) Description, Revision, Material and Weight, the drawing's file name and its DrawnBy/DrawnDate.
# (role, link, the field names of FreeCAD's ANSI/ASME and ISO formats, lower case without spaces or _)
FIELD_ROLES = (("title", '$PRPSHEET:"Description"', ("title", "drawingtitle1")),
               ("number", '$PRP:"SW-File Name"', ("drawingnumber", "number", "dwgno")),
               ("revision", '$PRPSHEET:"Revision"', ("revisionindex", "rev", "revision")),
               ("material", '$PRPSHEET:"Material"', ("partmaterial", "material")),
               ("weight", '$PRPSHEET:"Weight"', ("weight",)),
               ("drawnby", '$PRP:"DrawnBy"', ("drawnby", "authorname", "creator")),
               ("date", '$PRP:"DrawnDate"', ("dateofissue", "creationdate", "date")),
               ("company", '$PRP:"CompanyName"', ("companyname", "company")),
               ("finish", '$PRPSHEET:"Finish"', ("finish",)),
               ("checkedby", '$PRP:"CheckedBy"', ("checkedby",)),
               ("checkeddate", '$PRP:"CheckedDate"', ("checkeddate",)),
               ("engapproval", '$PRP:"EngineeringApproval"', ("engapproval",)),
               ("engapprovaldate", '$PRP:"EngAppDate"', ("engapprovaldate",)),
               ("mfgapproval", '$PRP:"ManufacturingApproval"', ("mfgapproval",)),
               ("mfgapprovaldate", '$PRP:"MfgAppDate"', ("mfgapprovaldate",)),
               ("qa", '$PRP:"QAApproval"', ("qa",)),
               ("qadate", '$PRP:"QAAppDate"', ("qadate",)))


def _field_key(k):
    return "".join(c for c in str(k).lower() if c.isalnum())


def field_role(k):
    ""
    key = _field_key(k)
    if key in ("sheet", "sheetnumber"):
        return "sheet"
    if key == "scale":
        return "scale"
    return next((r for r, _l, names in FIELD_ROLES if key in names), "")



# sheet formats show empty fields or linked values, never sample names (look audit DW-7)
SAMPLE_TEXTS = {"A. Nemesis", "B. Hecate", "Component Drawing", "DN", "AAA", "ISO 2768-m",
                "Stainless steel Mat.No. 1.4301", "YYYY-MM-DD", "X / Y", "ST1", "ST2", "RD", "In preparation",
                "ISO 7200 titleblock", "ISO 5457 template", "AUTHOR NAME", "SUPERVISOR NAME", "CREATION DATE",
                "CHECK DATE", "WEIGHT", "Weight", "NUMBER", "SUBTITLE", "COPYRIGHT", "COMPANY NAME", "Company Name",
                "1234 Main St", "Drawing Title 1", "Drawing Title 2", "Drawing Title 3", "Drawing Number", "Rev",
                "Drawn By", "Checked By", "Approved 1", "Approved 2", "Code", "TITLE", "_________",
                "Editable Text", "Another Editable"}


def clear_sample_texts(page, links=None):
    """The title block's sample values blanked (fields not linked to a property or the sheet)."""
    try:
        from . import drawlayout
        tpl = page.Template
        texts = dict(getattr(tpl, "EditableTexts", {}) or {})
        links = drawlayout.field_links(page) if links is None else links
        hard = {k for k in links if k not in set(drawlayout.soft_fields(page))}
        out = {k: ("" if str(v).strip() in SAMPLE_TEXTS and k not in hard else v) for k, v in texts.items()}
        if out != texts:
            tpl.EditableTexts = out
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sheet sample texts: %s\n" % error)
    return False


def default_field_links(page):
    ""



    try:
        from . import drawlayout
        tpl = page.Template
        links = drawlayout.field_links(page)
        clear_sample_texts(page, links)
        texts = dict(getattr(tpl, "EditableTexts", {}) or {})
        add = {k: SHEET_FIELDS[k.lower()] for k in texts if k.lower() in SHEET_FIELDS and k not in links}
        roles = {r: l for r, l, _n in FIELD_ROLES}
        taken = {field_role(k) for k in links if k in texts}
        soft = []
        for k in sorted(texts):
            r = field_role(k)
            if r in roles and k not in links and r not in taken:
                add[k] = roles[r]
                soft.append(k)
                taken.add(r)
        if not add:
            return False
        links.update(add)
        drawlayout.set_field_links(page, links)
        if soft:
            drawlayout.set_soft_fields(page, sorted(set(drawlayout.soft_fields(page)) | set(soft)))
        tpl.EditableTexts = drawlayout.resolve_fields(page, texts)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sheet fields: %s\n" % error)
        return False


SAVE_PATH = None   # checks: where an unsaved drawing is saved, without the file box
SAVE_AS_HOOK = None   # checks: callable(start path) -> path, in place of the Save As box
TEMP_ROOT = None   # checks: where new drawings are kept until their first Save (default: FreeCAD's user data)


# --------------------------------------------------------------------------- a new drawing before its first Save
def temp_dir():
    import os
    import time
    root = TEMP_ROOT or os.path.join(App.getUserAppDataDir(), "FreeWorks", "Unsaved")
    d = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + "-%d" % (int(time.time() * 1000) % 1000))
    os.makedirs(d, exist_ok=True)
    return d


def is_temp(doc):
    return bool(getattr(doc, "SWTempDrawing", ""))


def temp_save(doc):
    ""


    import os
    path = os.path.join(temp_dir(), (doc.Label or doc.Name) + ".FCStd")
    if "SWTempDrawing" not in doc.PropertiesList:
        doc.addProperty("App::PropertyString", "SWTempDrawing", "FreeCAD",
                        "holding file of a drawing not saved yet") if hasattr(doc, "addProperty") else None
    label = doc.Label
    _SAVING.append(doc.Name)
    try:
        try:
            doc.SWTempDrawing = path
        except Exception as _fw_err:
            _fw_log("drawings.py:744", _fw_err)
        doc.saveAs(path)
    finally:
        _SAVING.remove(doc.Name)
    doc.Label = label
    _TEMP[doc.Name] = path
    _modified(doc)
    return path


_SAVING = []
_TEMP = {}


def _modified(doc):
    """Marked as changed, so closing it asks to save (it has not been saved anywhere yet). The mark is an undo
    step too: interface's cleanopen marks a just-opened file with no new undo step clean again, and it took the
    holding file of a new drawing for one (bench drawsel/autosave)."""
    try:
        if not getattr(doc, "UndoCount", 0):
            doc.openTransaction("New Drawing")
            try:
                if "SWNewDrawing" not in doc.PropertiesList:
                    doc.addProperty("App::PropertyBool", "SWNewDrawing", "FreeCAD", "made as a new drawing")
                doc.SWNewDrawing = True
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
    except Exception as _fw_err:
        _fw_log("drawings.py:770", _fw_err)
    try:
        Gui.getDocument(doc.Name).Modified = True
    except Exception as _fw_err:
        _fw_log("drawings.py:774", _fw_err)


def temp_path(doc):
    return _TEMP.get(doc.Name) or getattr(doc, "SWTempDrawing", "") or ""


def _save_as_first(doc_name):
    """The first Save of a new drawing: the Save As box, starting next to its part under the drawing's name."""
    import os
    try:
        doc = App.getDocument(doc_name)
    except Exception as _fw_err:
        _fw_log("drawings.py:814", _fw_err)
        return False
    if not temp_path(doc):
        return True
    if doc_name in _ASKING:
        return False                # its Save As box is open already (a second Save while it is up)
    _ASKING.append(doc_name)
    try:
        return _ask_first(doc)
    finally:
        _ASKING.remove(doc_name)


_ASKING = []


def _first_box(doc, start):
    ""

    try:
        from . import saveas
        box, _types = saveas.save_dialog(doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Save As box: %s\n" % error)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save As", start,
                                                        "FreeCAD document (*.FCStd)")
        return path
    box.setDirectory(os.path.dirname(start) or os.path.expanduser("~"))
    box.selectFile(os.path.splitext(os.path.basename(start))[0])
    if not box.exec():
        return ""
    files = box.selectedFiles()
    path = files[0] if files else ""
    try:
        if path and box.description.text() != (doc.Comment or ""):
            doc.Comment = box.description.text()
    except Exception as _fw_err:
        _fw_log("drawings.py:823", _fw_err)
    return path


def _ask_first(doc):
    start = doc.Label + ".FCStd"
    for v in doc.Objects:
        from . import drawviews as DV
        for o in DV.xsource(v):
            if o.Document is not doc and o.Document.FileName:
                start = os.path.join(os.path.dirname(o.Document.FileName), doc.Label + ".FCStd")
                break
    # a drawing named after its part would get the part's own file name (both are .FCStd): never offer that
    if _taken(start, doc):
        stem = os.path.splitext(start)[0] + " Drawing"
        start, n = stem + ".FCStd", 1
        while _taken(start, doc) or os.path.exists(start):
            n += 1
            start = "%s %d.FCStd" % (stem, n)
    while True:
        if SAVE_AS_HOOK is not None:
            path = SAVE_AS_HOOK(start)
        else:
            path = _first_box(doc, start)
        if not path:
            _modified(doc)          # still not saved anywhere of the user's choosing
            return False
        if not path.lower().endswith(".fcstd"):
            path += ".FCStd"
        if not _taken(path, doc):
            break
        msg = "%s is the file of an open document (%s). Choose another name for the drawing." % (
            os.path.basename(path), _taken(path, doc))
        if SAVE_AS_HOOK is not None:
            App.Console.PrintWarning("FreeCAD: " + msg + "\n")
            _modified(doc)
            return False
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save As", msg)
        start = path
    old = temp_path(doc)
    _TEMP.pop(doc.Name, None)
    try:
        doc.SWTempDrawing = ""
    except Exception as _fw_err:
        _fw_log("drawings.py:867", _fw_err)
    doc.saveAs(path)
    # the links to the part keep the path they had from the holding file: set them again and save once more
    relinked = False
    for o in doc.Objects:
        try:
            xs = list(getattr(o, "XSource", []) or [])
        except Exception as _fw_err:
            _fw_log("drawings.py:903", _fw_err)
            continue
        if xs:
            o.XSource = []
            o.XSource = xs
            relinked = True
    if relinked:
        _SAVING.append(doc.Name)
        try:
            doc.save()
        finally:
            _SAVING.remove(doc.Name)
    try:
        # App's save leaves the GUI document "modified" (title asterisk, Save prompt on close: ChatGPT C13-01)
        Gui.getDocument(doc.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("drawings.py:890", _fw_err)
    try:
        if old and os.path.isfile(old):
            os.remove(old)
            os.rmdir(os.path.dirname(old))
    except Exception as _fw_err:
        _fw_log("drawings.py:896", _fw_err)
    return True


def _taken(path, doc):
    """The label of another open document whose file is path, else ''."""
    p = os.path.normcase(os.path.abspath(path))
    for o in App.listDocuments().values():
        if o is not doc and o.FileName and os.path.normcase(os.path.abspath(o.FileName)) == p:
            return o.Label
    return ""


def save_as_first(doc):
    """For the close box: Save As for a new drawing still in its holding file. True when saved."""
    return _save_as_first(doc.Name)


class _SaveWatch:
    ""

    def slotFinishSaveDocument(self, doc, path):
        try:
            if doc.Name in _SAVING:
                return
            temp = temp_path(doc)
            if temp and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(temp)):
                QtCore.QTimer.singleShot(0, lambda n=doc.Name: _save_as_first(n))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: first save: %s\n" % error)


    def slotDeletedDocument(self, doc):
        ""

        try:
            path = temp_path(doc)
            _TEMP.pop(doc.Name, None)
            if path and doc.Name not in _SAVING:
                QtCore.QTimer.singleShot(500, lambda p=path: _drop_holding(p))
        except Exception as _fw_err:
            _fw_log("drawings.py:937", _fw_err)


def _drop_holding(path):
    for name in App.listDocuments().values():
        try:
            if os.path.normcase(os.path.abspath(name.FileName)) == os.path.normcase(os.path.abspath(path)):
                return          # reopened meanwhile
        except Exception as _fw_err:
            _fw_log("drawings.py:946", _fw_err)
    try:
        root = os.path.normcase(os.path.abspath(TEMP_ROOT or os.path.join(App.getUserAppDataDir(), "FreeWorks",
                                                                          "Unsaved")))
        if not os.path.normcase(os.path.abspath(path)).startswith(root):
            return              # only ever a holding file of ours
        for f in (path, path + ".bak", os.path.splitext(path)[0] + ".FCBak"):
            if os.path.isfile(f):
                os.remove(f)
        d = os.path.dirname(path)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: holding file left: %s\n" % error)


def autosave_holding():
    """Auto-recover for new drawings: each one still in its holding file is saved there quietly (FreeCAD's
    own auto-recovery interval), and stays marked unsaved."""
    n = 0
    for doc in list(App.listDocuments().values()):
        try:
            if not temp_path(doc) or not Gui.getDocument(doc.Name).Modified:
                continue
            _SAVING.append(doc.Name)
            try:
                doc.save()
            finally:
                _SAVING.remove(doc.Name)
            _modified(doc)
            n += 1
        except Exception as error:
            App.Console.PrintLog("FreeCAD: auto-recover of %s: %s\n" % (doc.Name, error))
    return n


_WATCH = []


def watch_saves():
    if not _WATCH:
        _WATCH.append(_SaveWatch())
        App.addDocumentObserver(_WATCH[0])
        minutes = App.ParamGet("User parameter:BaseApp/Preferences/Document").GetInt("AutoSaveTimeout", 15)
        timer = QtCore.QTimer()
        timer.setInterval(max(1, minutes) * 60 * 1000)
        timer.timeout.connect(autosave_holding)
        timer.start()
        _WATCH.append(timer)


def saved_source(doc, drawing=None):
    """TechDraw links a view to a part's file only when both files are saved (an in-memory link to another
    document is lost on save and can crash FreeCAD when one of them closes). Asks to save an unsaved part, as
    Make Drawing does, then saves an unsaved drawing next to it (the Save As box). False on Cancel."""
    from . import newdoc
    if not newdoc._saved(doc, "a drawing view"):
        return False
    if drawing is not None and not drawing.FileName:
        if SAVE_PATH:
            drawing.saveAs(SAVE_PATH)
            try:
                # App's save leaves the GUI document "modified" (title asterisk, Save prompt on close: ChatGPT C13-01)
                Gui.getDocument(drawing.Name).Modified = False
            except Exception as _fw_err:
                _fw_log("drawings.py:1011", _fw_err)
        else:
            temp_save(drawing)
    return bool(doc.FileName) and (drawing is None or bool(drawing.FileName))


def link_source(view, shapes):
    """The view's model, a link to the part's file (both files must be saved: see saved_source)."""
    view.XSource = list(shapes)


def third_angle(page):
    try:
        return page.ProjectionType != "First angle"
    except Exception:
        return True


def auxiliary_frame(view, edge_index, dx, dy):
    """(direction, XDirection) of the Auxiliary View square to the view's straight edge edge_index, on the side
    of sheet offset (dx, dy)."""
    d, x, y = view_frame(view)
    e = view.getEdgeByIndex(edge_index)
    a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
    ex, ey = b.x - a.x, b.y - a.y       # in the view's own 2D frame (y up)
    L = math.hypot(ex, ey)
    if L < 1e-9:
        raise ValueError("the edge has no length")
    ex, ey = ex / L, ey / L
    along = _unit(x * ex + y * ey)       # the edge in space (its projection)
    # the line of sight square to the edge, in the view plane, towards the side the click is on
    nx, ny = -ey, ex
    if nx * dx + ny * dy < 0:
        nx, ny = -nx, -ny
    nd = _unit(x * nx + y * ny)
    return nd, along


# --------------------------------------------------------------------------- clicks on the sheet
GHOST_COLOR = "#1f6fd6"


def ghost_size(shapes, d, x, scale=1.0):
    """(width, height) on the sheet of shapes seen along d with x to the right, at scale: their box's outline."""
    bb = None
    for o in shapes or ():
        try:
            b = o.Shape.BoundBox if hasattr(o, "Shape") else o.BoundBox
        except Exception:
            continue
        if b is None or not b.isValid():
            continue
        if bb is None:
            bb = App.BoundBox(b)
        else:
            bb.add(b)
    if bb is None:
        return 40.0, 40.0
    d, x = _unit(V(d)), _unit(V(x))
    y = d.cross(x)
    xs, ys = [], []
    for i in range(8):
        c = V(bb.XMax if i & 1 else bb.XMin, bb.YMax if i & 2 else bb.YMin, bb.ZMax if i & 4 else bb.ZMin)
        xs.append(c.dot(x))
        ys.append(c.dot(y))
    k = float(scale or 1.0)
    return (max(xs) - min(xs)) * k, (max(ys) - min(ys)) * k


def placing_scale(page, shapes, scale=None):
    """The scale a new view of shapes will get: scale (Use custom scale), else the sheet's, picked to fit
    first when the view is the sheet's first (as new_view does)."""
    if scale is not None:
        return float(scale)
    try:
        if not [v for v in views_of(page) if v.TypeId == "TechDraw::DrawViewPart"] and auto_scale():
            s = fit_scale(page, shapes)
            if s:
                return float(s)
        return float(page.Scale)
    except Exception:
        return 1.0


def view_scale(v):
    return float(v.getScale()) if hasattr(v, "getScale") else float(v.Scale)


def projected_ghost(clicks, parent, p, shapes=None, third=True):
    """The Projected View preview at pointer p: the outline where the click puts the view (in line with
    parent for a side, top or bottom view) and the alignment line to parent."""
    bx, by = view_position(parent)
    d, x, name = projected_frame(parent, p[0] - bx, p[1] - by, third)
    at = aligned_place(name, p, (bx, by))
    size = ghost_size(shapes if shapes is not None else (parent.XSource or parent.Source), d, x, view_scale(parent))
    clicks.ghost(at, size, ((bx, by), at) if name != "Isometric" else None)
    return at, size


class SheetClicks(QtCore.QObject):
    """Feeds left clicks and moves on the sheet (in sheet mm) to a handler while a PropertyManager runs."""

    def __init__(self, page, owner):
        super().__init__()
        self.page = page
        self.owner = owner
        self.view = page_view(page)
        if self.view is not None:
            self.view.viewport().installEventFilter(self)
            self.view.viewport().setCursor(QtCore.Qt.CrossCursor)

    def ghost(self, center=None, size=None, line=None):
        ""


        scene = self.view.scene() if self.view is not None else None
        items = getattr(self, "_ghost", None)
        if scene is None:
            return None
        if center is None or size is None:
            for it in items or ():
                try:
                    scene.removeItem(it)
                except Exception:
                    pass
            self._ghost = None
            return None
        if not items:
            pen = QtGui.QPen(QtGui.QColor(GHOST_COLOR))
            pen.setCosmetic(True)
            pen.setWidthF(1.0)
            pen.setStyle(QtCore.Qt.DashLine)
            rect = QtWidgets.QGraphicsRectItem()
            rect.setPen(pen)
            rect.setBrush(QtCore.Qt.NoBrush)
            lpen = QtGui.QPen(pen)
            lpen.setStyle(QtCore.Qt.DashDotLine)
            ln = QtWidgets.QGraphicsLineItem()
            ln.setPen(lpen)
            for it in (rect, ln):
                it.setZValue(1e6)
                it.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                scene.addItem(it)
            items = self._ghost = [rect, ln]
        w, h = max(1.0, size[0]), max(1.0, size[1])
        tl = to_scene(center[0] - w / 2.0, center[1] + h / 2.0)
        items[0].setRect(QtCore.QRectF(tl.x(), tl.y(), w * REZ, h * REZ))
        if line:
            a, b = to_scene(*line[0]), to_scene(*line[1])
            items[1].setLine(a.x(), a.y(), b.x(), b.y())
            items[1].setVisible(True)
        else:
            items[1].setVisible(False)
        return items

    def stop(self):
        try:
            self.ghost(None)
        except Exception as _fw_err:
            _fw_log("drawings.py:ghost off", _fw_err)
        if self.view is not None:
            try:
                self.view.viewport().removeEventFilter(self)
                self.view.viewport().unsetCursor()
            except Exception as _fw_err:
                _fw_log("drawings.py:1068", _fw_err)
        self.owner = None

    def eventFilter(self, obj, event):
        try:
            if self.owner is None or not isinstance(event, QtCore.QEvent):
                return False
            t = event.type()
            if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                p = to_sheet(self.view.mapToScene(event.position().toPoint()))
                return bool(self.owner.sheet_click(p))
            if t == QtCore.QEvent.MouseMove:
                p = to_sheet(self.view.mapToScene(event.position().toPoint()))
                self.owner.sheet_move(p)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: drawing click: %s\n" % error)
        return False


# --------------------------------------------------------------------------- PropertyManagers
class FoldGroup(QtWidgets.QGroupBox):
    ""


    def __init__(self, title, parent=None, folded=False):
        super().__init__(title, parent)
        self._folded = False
        self._hidden = []
        self._fold_on_show = folded

    def title_height(self):
        return QtGui.QFontMetrics(self.font()).height() + 6

    def is_folded(self):
        return self._folded

    def set_folded(self, on):
        on = bool(on)
        if on == self._folded:
            return
        self._folded = on
        kids = [w for w in self.children() if isinstance(w, QtWidgets.QWidget)]
        if on:
            self._hidden = [w for w in kids if not w.isHidden()]
            for w in self._hidden:
                w.hide()
            self.setFixedHeight(self.title_height() + 4)
        else:
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            for w in self._hidden:
                try:
                    w.show()
                except RuntimeError as _fw_err:
                    _fw_log("drawings.py:1122", _fw_err)
            self._hidden = []
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if self._fold_on_show:
            self._fold_on_show = False
            self.set_folded(True)

    def _on_title_check(self, pos):
        """True when pos is on the title's check box or its text (a group ticked in its title: Arrow...)."""
        if not self.isCheckable():
            return False
        try:
            opt = QtWidgets.QStyleOptionGroupBox()
            self.initStyleOption(opt)
            st = self.style()
            for sc in (QtWidgets.QStyle.SC_GroupBoxCheckBox, QtWidgets.QStyle.SC_GroupBoxLabel):
                if st.subControlRect(QtWidgets.QStyle.CC_GroupBox, opt, sc, self).contains(pos):
                    return True
        except Exception as _fw_err:
            _fw_log("drawings.py:fold title check", _fw_err)
        return False

    def mousePressEvent(self, event):
        if self._on_title_check(event.pos()):
            super().mousePressEvent(event)       # the title's check box ticks, it does not fold the group
            return
        if event.button() == QtCore.Qt.LeftButton and event.pos().y() <= self.title_height():
            self.set_folded(not self._folded)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        try:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            pen = QtGui.QPen(self.palette().color(QtGui.QPalette.WindowText))
            pen.setWidthF(1.4)
            p.setPen(pen)
            h = self.title_height()
            x, y = self.width() - 14, h / 2.0
            if self._folded:             # down chevron: click to open
                pts = [QtCore.QPointF(x - 4, y - 2), QtCore.QPointF(x, y + 2), QtCore.QPointF(x + 4, y - 2)]
            else:                        # up chevron: click to fold
                pts = [QtCore.QPointF(x - 4, y + 2), QtCore.QPointF(x, y - 2), QtCore.QPointF(x + 4, y + 2)]
            p.drawPolyline(QtGui.QPolygonF(pts))
            p.end()
        except Exception as _fw_err:
            _fw_log("drawings.py:1156", _fw_err)


FOLDED_GROUPS = ("Mirror", "Import options", "Save View as")


def _group(title, parent, folded=None):
    box = FoldGroup(title, parent, title in FOLDED_GROUPS if folded is None else folded)
    box.setObjectName("SWDrawGroup_" + title.replace(" ", "").replace("/", ""))
    lay = QtWidgets.QVBoxLayout(box)
    lay.setContentsMargins(6, 6, 6, 6)
    return box, lay


STYLE_ICONS = {"Wireframe": "DrawStyleWireFrame", "Hidden Lines Visible": "DrawStyleHiddenLine",
               "Hidden Lines Removed": "DrawStyleNoShading", "Shaded With Edges": "DrawStyleFlatLines",
               "Shaded": "DrawStyleShaded"}


PACK_STYLE_ICONS = {"Wireframe": "I3DVIEW_WIREFRAME", "Hidden Lines Visible": "I3DVIEW_HLV",
                    "Hidden Lines Removed": "I3DVIEW_HLR", "Shaded With Edges": "I3DVIEW_SHADED_EDGES",
                    "Shaded": "I3DVIEW_SHADED"}


def _style_icon(style):
    """A Display Style button's picture: the icon pack's (the one the Heads-up toolbar shows), else FreeCAD's."""
    try:
        from . import icons
        icon = icons.family(PACK_STYLE_ICONS[style])
        if icons.paints(icon):
            return icon
    except Exception as _fw_err:
        _fw_log("drawings.py:style_icon", _fw_err)
    return QtGui.QIcon(":/icons/%s.svg" % STYLE_ICONS[style])


class StyleButtons(QtWidgets.QWidget):
    ""


    def __init__(self, parent, name="SWDrawDisplayStyle", current="Hidden Lines Removed"):
        super().__init__(parent)
        self.setObjectName(name + "Buttons")
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        self.combo = QtWidgets.QComboBox(self)
        self.combo.setObjectName(name)
        self.combo.addItems(DISPLAY_STYLES)
        self.combo.hide()
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for n, style in enumerate(DISPLAY_STYLES):
            b = QtWidgets.QToolButton(self)
            b.setObjectName("SWStyleButton" + style.replace(" ", ""))
            b.setCheckable(True)
            b.setToolTip(style)
            icon = _style_icon(style)
            if icon.isNull():
                b.setText("".join(w[0] for w in style.split()))
            else:
                b.setIcon(icon)
                b.setIconSize(QtCore.QSize(22, 22))
            self.group.addButton(b, n)
            row.addWidget(b)
            self.buttons[style] = b
        row.addStretch(1)
        self.group.buttonClicked.connect(lambda b: self.combo.setCurrentText(b.toolTip()))
        self.combo.currentTextChanged.connect(self._sync)
        self.combo.setCurrentText(current)
        self._sync(current)

    def _sync(self, text):
        b = self.buttons.get(text)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def currentText(self):
        return self.combo.currentText()

    def setCurrentText(self, text):
        self.combo.setCurrentText(text)

    @property
    def currentTextChanged(self):
        return self.combo.currentTextChanged

    def setEnabled(self, on):
        for b in self.buttons.values():
            b.setEnabled(on)


SCALES = ("1:1", "1:2", "1:4", "1:5", "1:10", "1:20", "1:50", "2:1", "4:1", "5:1", "10:1", "User Defined")


def mirror_group(panel, prefix="SWView", current=""):
    ""
    box, lay = _group("Mirror", panel.form)
    panel.mirror = QtWidgets.QCheckBox("Mirror view", box)
    panel.mirror.setObjectName(prefix + "Mirror")
    panel.mirror.setChecked(bool(current))
    lay.addWidget(panel.mirror)
    row = QtWidgets.QHBoxLayout()
    panel.mirror_h = QtWidgets.QRadioButton("Horizontal", box)
    panel.mirror_h.setObjectName(prefix + "MirrorHorizontal")
    panel.mirror_v = QtWidgets.QRadioButton("Vertical", box)
    panel.mirror_v.setObjectName(prefix + "MirrorVertical")
    (panel.mirror_v if current == "Vertical" else panel.mirror_h).setChecked(True)
    row.addWidget(panel.mirror_h)
    row.addWidget(panel.mirror_v)
    lay.addLayout(row)
    for w in (panel.mirror_h, panel.mirror_v):
        # live, never greyed: picking a side turns Mirror view on
        w.clicked.connect(lambda *_: panel.mirror.isChecked() or panel.mirror.setChecked(True))
    panel.lay.addWidget(box)


def mirror_choice(panel):
    if not panel.mirror.isChecked():
        return ""
    return "Vertical" if panel.mirror_v.isChecked() else "Horizontal"


def view_groups(panel, parent=None, scale="Sheet", custom=1.0, dim="Projected", thread="Draft quality",
                style=None, config=True, prefix="SWView"):
    ""


    f = panel.form
    if config:
        box, lay = _group("Reference Configuration", f)
        panel.config = QtWidgets.QComboBox(box)
        panel.config.setObjectName(prefix + "Configuration")
        panel.config.addItem("Default <Link to parent>" if parent is not None else "Default")
        lay.addWidget(panel.config)
        panel.lay.addWidget(box)
    box, lay = _group("Display State", f)
    panel.display_state = QtWidgets.QComboBox(box)
    panel.display_state.setObjectName(prefix + "DisplayState")
    panel.display_state.addItem("<Default>_Display State 1")
    lay.addWidget(panel.display_state)
    panel.lay.addWidget(box)
    box, lay = _group("Display Style", f)
    panel.parent_style = QtWidgets.QCheckBox("Use parent style", box)
    panel.parent_style.setObjectName(prefix + "ParentStyle")
    panel.parent_style.setVisible(parent is not None)
    panel.parent_style.setChecked(parent is not None)
    lay.addWidget(panel.parent_style)
    pstyle = getattr(parent, "SWDisplayStyle", "") if parent is not None else ""
    panel.style = StyleButtons(box, "SWDrawDisplayStyle", style or pstyle or new_view_style())
    # live with Use parent style on too: a style picked turns Use parent style off
    panel.parent_style.toggled.connect(lambda on: on and pstyle and panel.style.setCurrentText(pstyle))
    panel.style.group.buttonClicked.connect(lambda b: panel.parent_style.isChecked() and
                                            b.toolTip() != pstyle and panel.parent_style.setChecked(False))
    lay.addWidget(panel.style)
    panel.see_through = QtWidgets.QCheckBox("See through transparent components", box)
    panel.see_through.setObjectName(prefix + "SeeThrough")
    panel.see_through.setChecked(True)
    lay.addWidget(panel.see_through)
    panel.lay.addWidget(box)
    box, lay = _group("Scale", f)
    panel.use_parent = QtWidgets.QRadioButton("Use parent scale", box)
    panel.use_parent.setObjectName(prefix + "ParentScale")
    panel.use_parent.setVisible(parent is not None)
    panel.use_sheet = QtWidgets.QRadioButton("Use sheet scale", box)
    panel.use_sheet.setObjectName(prefix + "SheetScale")
    panel.use_custom = QtWidgets.QRadioButton("Use custom scale", box)
    panel.use_custom.setObjectName(prefix + "CustomScale")
    panel.scale_combo = QtWidgets.QComboBox(box)
    panel.scale_combo.setObjectName(prefix + "ScaleCombo")
    panel.scale_combo.setEditable(True)
    panel.scale_combo.addItems(SCALES)
    panel.scale_combo.setCurrentText(scale_text(custom))
    mode = scale if (scale != "Parent" or parent is not None) else "Sheet"
    {"Parent": panel.use_parent, "Sheet": panel.use_sheet}.get(mode, panel.use_custom).setChecked(True)
    # live, never greyed: a scale picked or typed makes it the custom scale
    # (Qt 6 sends activated when the editable box only loses focus: that is no pick, and must not leave Use parent)
    combo = panel.scale_combo
    combo.activated.connect(lambda *_: QtWidgets.QApplication.focusWidget() in (combo, combo.lineEdit(), combo.view())
                            and panel.use_custom.setChecked(True))
    panel.scale_combo.lineEdit().textEdited.connect(lambda *_: panel.use_custom.setChecked(True))
    for w in (panel.use_parent, panel.use_sheet, panel.use_custom, panel.scale_combo):
        lay.addWidget(w)
    panel.lay.addWidget(box)
    box, lay = _group("Dimension Type", f)
    panel.dim_projected = QtWidgets.QRadioButton("Projected", box)
    panel.dim_projected.setObjectName(prefix + "DimProjected")
    panel.dim_true = QtWidgets.QRadioButton("True", box)
    panel.dim_true.setObjectName(prefix + "DimTrue")
    (panel.dim_true if dim == "True" else panel.dim_projected).setChecked(True)
    lay.addWidget(panel.dim_projected)
    lay.addWidget(panel.dim_true)
    panel.lay.addWidget(box)
    box, lay = _group("Cosmetic Thread Display", f)
    panel.thread_high = QtWidgets.QRadioButton("High quality", box)
    panel.thread_high.setObjectName(prefix + "ThreadHigh")
    panel.thread_draft = QtWidgets.QRadioButton("Draft quality", box)
    panel.thread_draft.setObjectName(prefix + "ThreadDraft")
    (panel.thread_high if thread == "High quality" else panel.thread_draft).setChecked(True)
    lay.addWidget(panel.thread_high)
    lay.addWidget(panel.thread_draft)
    panel.lay.addWidget(box)
    box, lay = _group("Automatic View Update", f, folded=parent is None)
    panel.exclude_update = QtWidgets.QCheckBox("Exclude from automatic update", box)
    panel.exclude_update.setObjectName(prefix + "ExcludeUpdate")
    lay.addWidget(panel.exclude_update)
    panel.lay.addWidget(box)


def extra_groups(panel, dim="Projected", thread="Draft quality", style_lay=None, prefix="SWView"):
    ""

    f = panel.form
    if style_lay is not None:
        panel.parent_style = QtWidgets.QCheckBox("Use parent style", f)
        panel.parent_style.setObjectName(prefix + "ParentStyle")
        panel.parent_style.setChecked(True)
        style_lay.insertWidget(0, panel.parent_style)
        panel.see_through = QtWidgets.QCheckBox("See through transparent components", f)
        panel.see_through.setObjectName(prefix + "SeeThrough")
        panel.see_through.setChecked(True)
        style_lay.addWidget(panel.see_through)
    box, lay = _group("Display State", f)
    panel.display_state = QtWidgets.QComboBox(box)
    panel.display_state.setObjectName(prefix + "DisplayState")
    panel.display_state.addItem("<Default>_Display State 1")
    lay.addWidget(panel.display_state)
    panel.lay.addWidget(box)
    box, lay = _group("Dimension Type", f)
    panel.dim_projected = QtWidgets.QRadioButton("Projected", box)
    panel.dim_projected.setObjectName(prefix + "DimProjected")
    panel.dim_true = QtWidgets.QRadioButton("True", box)
    panel.dim_true.setObjectName(prefix + "DimTrue")
    (panel.dim_true if dim == "True" else panel.dim_projected).setChecked(True)
    lay.addWidget(panel.dim_projected)
    lay.addWidget(panel.dim_true)
    panel.lay.addWidget(box)
    box, lay = _group("Cosmetic Thread Display", f)
    panel.thread_high = QtWidgets.QRadioButton("High quality", box)
    panel.thread_high.setObjectName(prefix + "ThreadHigh")
    panel.thread_draft = QtWidgets.QRadioButton("Draft quality", box)
    panel.thread_draft.setObjectName(prefix + "ThreadDraft")
    (panel.thread_high if thread == "High quality" else panel.thread_draft).setChecked(True)
    lay.addWidget(panel.thread_high)
    lay.addWidget(panel.thread_draft)
    panel.lay.addWidget(box)
    box, lay = _group("Automatic View Update", f)
    panel.exclude_update = QtWidgets.QCheckBox("Exclude from automatic update", box)
    panel.exclude_update.setObjectName(prefix + "ExcludeUpdate")
    lay.addWidget(panel.exclude_update)
    panel.lay.addWidget(box)


def apply_extra(panel, v):
    for name, val, kind in (("SWDimensionType", "True" if panel.dim_true.isChecked() else "Projected", "App::PropertyString"),
                            ("SWCosmeticThreads", "High quality" if panel.thread_high.isChecked() else "Draft quality",
                             "App::PropertyString"),
                            ("SWDisplayState", panel.display_state.currentText(), "App::PropertyString"),
                            ("SWSeeThrough", panel.see_through.isChecked(), "App::PropertyBool"),
                            ("SWExcludeUpdate", panel.exclude_update.isChecked(), "App::PropertyBool")):
        if name not in v.PropertiesList:
            v.addProperty(kind, name, "FreeCAD", "Drawing View option")
        setattr(v, name, val)
    if getattr(panel, "parent_style", None) is not None:
        if "SWStyleFromParent" not in v.PropertiesList:
            v.addProperty("App::PropertyString", "SWStyleFromParent", "FreeCAD", "Drawing View option")
        v.SWStyleFromParent = "1" if panel.parent_style.isChecked() else "0"


def view_scale_choice(panel, parent=None):
    """(mode, factor) from the panel's Scale group: mode Parent / Sheet / Custom."""
    if panel.use_parent.isChecked() and parent is not None:
        return "Parent", None
    if panel.use_sheet.isChecked():
        return "Sheet", None
    s = parse_scale(panel.scale_combo.currentText())
    return "Custom", (s if s and s > 0 else 1.0)


def apply_view_groups(panel, v, parent=None):
    """The view-group choices onto a placed view v."""
    def put(name, val, kind="App::PropertyString"):
        if name not in v.PropertiesList:
            v.addProperty(kind, name, "FreeCAD", "Drawing View option")
        setattr(v, name, val)
    style = panel.style.currentText()
    if panel.parent_style.isChecked() and parent is not None:
        style = getattr(parent, "SWDisplayStyle", "") or style
        put("SWStyleFromParent", "1")
    else:
        put("SWStyleFromParent", "0")
    set_display_style(v, style)
    mode, factor = view_scale_choice(panel, parent)
    if mode == "Parent":
        follow_parent_scale(v, parent)
    elif mode == "Sheet":
        v.ScaleType = "Page"
        set_scale_mode(v, "Sheet")
    else:
        v.ScaleType = "Custom"
        v.Scale = factor
        set_scale_mode(v, "Custom")
    put("SWDimensionType", "True" if panel.dim_true.isChecked() else "Projected")
    put("SWCosmeticThreads", "High quality" if panel.thread_high.isChecked() else "Draft quality")
    put("SWSeeThrough", panel.see_through.isChecked(), "App::PropertyBool")
    put("SWExcludeUpdate", panel.exclude_update.isChecked(), "App::PropertyBool")
    put("SWDisplayState", panel.display_state.currentText())
    if getattr(panel, "config", None) is not None:
        put("SWConfiguration", panel.config.currentText().replace(" <Link to parent>", ""))


def arrow_group(panel, page, prefix="SWView"):
    """The Arrow group (title check box) of Projected and Auxiliary View: an arrow on the parent and VIEW X."""
    box, lay = _group("Arrow", panel.form)
    panel.arrow = QtWidgets.QCheckBox("Arrow", box)
    panel.arrow.setObjectName(prefix + "Arrow")
    row = QtWidgets.QHBoxLayout()
    panel.arrow_label = QtWidgets.QLineEdit("", box)
    panel.arrow_label.setObjectName(prefix + "ArrowLabel")
    # live, never greyed: a label typed turns Arrow on
    panel.arrow_label.textEdited.connect(lambda *_: panel.arrow.isChecked() or panel.arrow.setChecked(True))

    def toggled(on):
        if on and not panel.arrow_label.text():
            cur = getattr(page, "FreeWorksNextViewLabel", "") if hasattr(page, "FreeWorksNextViewLabel") else ""
            panel.arrow_label.setText(cur or "A")
    panel.arrow.toggled.connect(toggled)
    lay.addWidget(panel.arrow)
    row.addWidget(QtWidgets.QLabel("Label:", box))
    row.addWidget(panel.arrow_label)
    lay.addLayout(row)
    panel.lay.addWidget(box)

    box.setObjectName(prefix + "ArrowGroup")
    box.setCheckable(True)
    box.setChecked(panel.arrow.isChecked())
    panel.arrow.hide()
    box.toggled.connect(lambda on: panel.arrow.isChecked() == on or panel.arrow.setChecked(on))
    panel.arrow.toggled.connect(lambda on: box.isChecked() == on or box.setChecked(on))
    try:
        from . import drawlive as DL
        DL.fold(box)
    except Exception as _fw_err:
        _fw_log("drawings.py:arrow fold", _fw_err)
    panel.arrow_box = box


def view_arrow(page, parent, v, letter):
    ""

    from . import drawannot as DA
    from . import drawviews as DV
    px, py = view_position(parent)
    vx, vy = view_position(v)
    dx, dy = vx - px, vy - py
    L = math.hypot(dx, dy) or 1.0
    ux, uy = dx / L, dy / L
    try:
        w, h = DV.view_extent(parent) if hasattr(DV, "view_extent") else (40.0, 40.0)
    except Exception:
        w, h = 40.0, 40.0
    reach = abs(ux) * w / 2 + abs(uy) * h / 2 + 8
    tail = (px + ux * (reach + 10), py + uy * (reach + 10))
    tip = (px + ux * reach, py + uy * reach)
    ax, ay = tip[0] - tail[0], -(tip[1] - tail[1])
    body = DA._arrow(ax / 2, ay / 2, -ax / 2, -ay / 2) + (
        '<text x="%g" y="%g" font-family="osifont, Arial" font-size="5" text-anchor="middle">%s</text>'
        % (-ax / 2 - uy * 4, -ay / 2 - ux * 4 + 1.8, DA._esc(letter)))
    mid = ((tip[0] + tail[0]) / 2, (tip[1] + tail[1]) / 2)
    arrow = DA.svg_symbol(page, "ViewArrow", body, 14, mid, "View Arrow %s" % letter, "ViewArrow")
    arrow.addProperty("App::PropertyString", "SWArrowOf", "FreeCAD", "the view this arrow names")
    arrow.SWArrowOf = v.Name
    try:
        vw, vh = DV.view_extent(v) if hasattr(DV, "view_extent") else (40.0, 40.0)
    except Exception:
        vw, vh = 40.0, 40.0
    label = DA.svg_symbol(page, "ViewLabel", '<text x="0" y="1.8" font-family="osifont, Arial" font-size="5" '
                          'text-anchor="middle">VIEW %s</text>' % DA._esc(letter), 20, (vx, vy - vh / 2 - 8),
                          "VIEW %s" % letter, "ViewLabel")
    label.addProperty("App::PropertyString", "SWLabelOf", "FreeCAD", "the view this label names")
    label.SWLabelOf = v.Name
    return arrow, label


def after_build(panel, fn):
    """fn runs once the PM's build() is done (before it shows)."""
    getattr(panel, "_after", []).append(fn)


def _apply_format_font(panel):
    """A PM's Format group (Use document font off, Font... picked): its symbols' text takes that font."""
    box = getattr(panel, "doc_font", None)
    if box is None or box.isChecked():
        return
    from . import drawpmparts as PP
    family = PP.font_of(panel)
    for o in getattr(panel, "made", []):
        try:
            sym = getattr(o, "Symbol", None)
        except Exception:
            continue
        if sym and 'font-family="osifont, Arial"' in sym:
            o.Symbol = sym.replace('font-family="osifont, Arial"', 'font-family="%s"' % family)


def order_groups(lay, titles):
    """The group boxes of a PM's layout put in the order of titles, in the places those groups had."""
    try:
        at, boxes = [], {}
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QtWidgets.QGroupBox) and w.title() in titles and w.title() not in boxes:
                at.append(i)
                boxes[w.title()] = w
        want = [boxes[t] for t in titles if t in boxes]
        for w in want:
            lay.removeWidget(w)
        for i, w in zip(at, want):
            lay.insertWidget(i, w)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PM group order: %s\n" % error)


ORIENT_ICONS = {"Dimetric": "VIEWORIENT_DIAMETRIC"}


def orient_look(b, name):
    ""
    b.setToolTip("*" + name)
    try:
        from . import icons
        icon = icons.family(ORIENT_ICONS.get(name, "VIEWORIENT_" + name.upper()))
        if icons.paints(icon):
            b.setIcon(icon)
            b.setIconSize(QtCore.QSize(24, 24))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
    except Exception as _fw_err:
        _fw_log("drawings.py:1558", _fw_err)


class _Panel:
    ""
    TITLE = "Drawing View"
    PIXMAP = "TechDraw_View"

    def __init__(self, page):
        try:
            from . import drawdimtools          # (drawings-land281: its click filter took the next pick)
            if drawdimtools.SMART:
                drawdimtools.SMART[0].done()
        except Exception as _fw_err:
            _fw_log("drawings.py:_Panel smart", _fw_err)
        self.page = page
        self.doc = page.Document
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDrawPM")
        self.form.setWindowTitle(self.TITLE)
        self.form.setProperty("swstyle_pm_title", self.TITLE)

        # (propertymanager hides the task box's own header row, PM pkg353)
        self.form.setProperty("swstyle_no_box_header", True)
        real = real_pixmap(self.PIXMAP)
        self.form.setWindowIcon(QtGui.QIcon(real or pixmap(self.PIXMAP)))
        if real:

            # command's own pixmap is a blank stand-in while TechDraw loads, so the header showed none: DR-1)
            self.form.setProperty("swstyle_pm_icon", real)
        self.lay = QtWidgets.QVBoxLayout(self.form)
        self.message = QtWidgets.QLabel("", self.form)
        self.message.setObjectName("SWDrawMessage")
        self.message.setWordWrap(True)
        mbox, ml = _group("Message", self.form)
        ml.addWidget(self.message)
        self.lay.addWidget(mbox)
        self.made = []
        self._after = []
        self.build()
        if self.LAYER:
            self._after.append(self._layer_group)
        for fn in self._after:
            try:
                fn()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s: %s\n" % (self.TITLE, error))
        if self.GROUP_ORDER:
            order_groups(self.lay, self.GROUP_ORDER)
        try:
            from . import drawdocprops      # the PM opens with the drawing's Document Properties defaults
            drawdocprops.pm_defaults(self)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: Document Properties: %s\n" % (self.TITLE, error))
        self.lay.addStretch(1)
        self.clicks = SheetClicks(page, self)
        self.doc.openTransaction(self.TITLE)

    def build(self):
        pass

    LAYER = False
    GROUP_ORDER = ()

    def _layer_group(self):
        from . import drawpmparts as PP, drawannot as DA
        PP.layer_group(self)
        self._kept_from = len(DA.KEPT)

    def _finish_layers(self):
        if not self.LAYER:
            return
        from . import drawpmparts as PP, drawannot as DA
        PP.finish_layers(self)
        name = PP.layer_of(self)
        if name != PP.NONE_LAYER:
            for view, tag in DA.KEPT[getattr(self, "_kept_from", len(DA.KEPT)):]:
                PP.layer_cosmetic(view, tag, name)

    def say(self, text):
        self.message.setText(text)

    def sheet_click(self, p):
        return False

    def sheet_move(self, p):
        pass

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def finish(self):
        pass

    def accept(self):
        try:
            self.finish()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (self.TITLE, error))
        try:
            _apply_format_font(self)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s font: %s\n" % (self.TITLE, error))
        try:
            self._finish_layers()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s layer: %s\n" % (self.TITLE, error))
        self.clicks.stop()
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self.clicks.stop()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


class _SourcePick:
    """The "Part/Assembly to Insert" group: the open parts and assemblies, and Browse..."""

    def source_group(self):
        box, lay = _group("Part/Assembly to Insert", self.form)
        self.sources = QtWidgets.QListWidget(box)
        self.sources.setObjectName("SWDrawSources")
        self.sources.setMaximumHeight(90)
        self.sources.setProperty("swFixedScope", True)   # a list of open documents to choose from, not picks
        docs = self.source_documents() if hasattr(self, "source_documents") else source_documents()
        for doc in docs:
            item = QtWidgets.QListWidgetItem(doc.Label)
            item.setData(QtCore.Qt.UserRole, doc.Name)
            self.sources.addItem(item)
        if self.sources.count():

            want = drawing_model(getattr(self, "doc", None))
            rows = [i for i in range(self.sources.count())
                    if want is not None and self.sources.item(i).data(QtCore.Qt.UserRole) == want.Name]
            self.sources.setCurrentRow(rows[0] if rows else 0)
        lay.addWidget(QtWidgets.QLabel("Open documents:", box))
        lay.addWidget(self.sources)
        browse = QtWidgets.QPushButton("Browse...", box)
        browse.setObjectName("SWDrawBrowse")
        browse.clicked.connect(self.browse)
        lay.addWidget(browse)
        self.lay.addWidget(box)

    def browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", "", "FreeCAD part (*.FCStd)")
        if not path:
            return
        doc = App.openDocument(path, hidden=False)
        App.setActiveDocument(self.doc.Name)
        item = QtWidgets.QListWidgetItem(doc.Label)
        item.setData(QtCore.Qt.UserRole, doc.Name)
        self.sources.addItem(item)
        self.sources.setCurrentItem(item)

    def source(self):
        item = self.sources.currentItem()
        if item is None:
            return None
        try:
            return App.getDocument(item.data(QtCore.Qt.UserRole))
        except Exception:
            return None


class Standard3ViewPanel(_SourcePick, _Panel):
    TITLE = "Standard 3 View"
    PIXMAP = "TechDraw_ProjectionGroup"

    def build(self):
        self.say("Select a part or assembly from the list or Browse; OK puts its Front, Top and Right views on "
                 "the sheet.")
        self.source_group()

    def finish(self):
        src = self.source()
        if src is None or not saved_source(src, self.doc):
            return
        g = standard_3_view(self.page, src)
        if g is not None:
            self.made.append(g)


def import_annotations_later(page, v, tries=40, design=True, mbd=False, hidden=True):
    """Import annotations: the model's dimensions (Design annotations) and its MBD dimensions (MBD dimension
    annotations) into view v once TechDraw has its lines (found in the background)."""
    def step(n=tries):
        try:
            v.getVertexByIndex(0)
            ready = True
        except Exception:
            ready = False
        if not ready and n > 0:
            QtCore.QTimer.singleShot(250, lambda: step(n - 1))
            return
        try:
            from . import drawannot
            made = list(drawannot.model_items(page, [v], hidden=hidden) or []) if design else []
            for dm in made:
                try:
                    dm.MeasureType = getattr(v, "SWDimensionType", "Projected")
                except Exception as _fw_err:
                    _fw_log("drawings.py:1751", _fw_err)
            if mbd:
                drawannot.pmi_items(page, [v], list(drawannot.PMI_DIMENSIONS))
            page.Document.recompute()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Import annotations: %s\n" % error)
    step()


MODEL_VIEW_PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Drawings"
CROSS = {"Top": (0, 1), "Isometric": (0, 3), "Left": (1, 0), "Front": (1, 1), "Right": (1, 2), "Back": (1, 3),
         "Bottom": (2, 1)}
MORE_VIEWS = ("Trimetric", "Dimetric")


def orient_frame(src, name):
    ""

    if name in ORIENTATIONS:
        return ORIENTATIONS[name]
    from . import drawpalette
    return drawpalette.orientation(src, drawpalette.NAMED + name)


def start_command_on_new():
    ""
    try:
        return App.ParamGet(MODEL_VIEW_PARAM).GetBool("StartModelView", True)
    except Exception:
        return True


def _palette_for(name):
    """Make Drawing from Part/Assembly: the View Palette shows that model. A palette already open (from the
    drawing made before) kept the model it showed, so Make Drawing from Part after one from an assembly
    offered the assembly's views."""
    from . import drawpalette
    try:
        shown = [p for p in drawpalette._PALETTE if p is not None and p.isVisible()]
    except Exception as _fw_err:
        _fw_log("drawings.py:palette for", _fw_err)
        shown = []
    if not shown:
        return _palette_shown()
    doc = App.getDocument(name) if name in App.listDocuments() else None
    for p in shown:
        try:
            if doc is not None and p.source.currentData() != doc.Name:
                p.refresh(prefer=doc)
        except Exception as _fw_err:
            _fw_log("drawings.py:palette refresh", _fw_err)
    return None


def _palette_shown():
    from . import drawpalette
    try:
        if any(p.isVisible() for p in drawpalette._PALETTE if p is not None):
            return
    except Exception as _fw_err:
        _fw_log("drawings.py:1780", _fw_err)
    try:
        drawpalette.show_palette()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Palette: %s\n" % error)


def _model_view_on_new(dname, pname):
    """The Model View PM on the new sheet, unless another PM opened meanwhile."""
    try:
        doc = App.getDocument(dname) if dname in App.listDocuments() else None
        page = doc.getObject(pname) if doc is not None else None
        if page is None or Gui.Control.activeDialog():
            return
        _show(ModelViewPanel(page))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Model View at new drawing: %s\n" % error)


def start_model_view(page):
    ""


    if page is None:
        return None
    try:
        from . import drawpalette
        for ms in (400, 1200, 2500):
            # the sheet's window (and the Task Pane's host with it) comes up after the format box: the
            # first opening could land on the window it replaced (PC 11-08), so try again until it shows
            QtCore.QTimer.singleShot(ms, _palette_shown)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Palette: %s\n" % error)
    if start_command_on_new():
        QtCore.QTimer.singleShot(800, lambda d=page.Document.Name, n=page.Name: _model_view_on_new(d, n))
    fit_while_opening(page)
    return None


class ModelViewPanel(_SourcePick, _Panel):
    ""
    TITLE = "Model View"
    PIXMAP = "TechDraw_View"

    def build(self):
        self.say("Select a part or assembly from which to create the view, then click Next.")
        nav = QtWidgets.QHBoxLayout()
        self.back_button = QtWidgets.QPushButton("< Back", self.form)
        self.back_button.setObjectName("SWDrawBack")
        self.next_button = QtWidgets.QPushButton("Next >", self.form)
        self.next_button.setObjectName("SWDrawNext")
        nav.addStretch(1)
        nav.addWidget(self.back_button)
        nav.addWidget(self.next_button)
        self.lay.addLayout(nav)
        # ---- page 1
        self.page1 = QtWidgets.QWidget(self.form)
        self.page1.setObjectName("SWDrawModelViewPage1")
        outer = self.lay
        self.lay = QtWidgets.QVBoxLayout(self.page1)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.source_group()
        box, lay = _group("Options", self.page1)
        self.start_new = QtWidgets.QCheckBox("Start command when creating\nnew drawing", box)    # fits 300 px
        self.start_new.setObjectName("SWDrawStartOnNew")
        self.start_new.setChecked(start_command_on_new())
        self.start_new.toggled.connect(
            lambda on: App.ParamGet(MODEL_VIEW_PARAM).SetBool("StartModelView", bool(on)))
        lay.addWidget(self.start_new)

        self.projected1 = QtWidgets.QCheckBox("Auto-start projected view", box)
        self.projected1.setObjectName("SWDrawAutoProjected1")
        self.projected1.setChecked(True)
        lay.addWidget(self.projected1)
        self.projected1.hide()
        self.lay.addWidget(box)
        box, lay = _group("Cosmetic Thread Display", self.page1)
        self.thread_high1 = QtWidgets.QRadioButton("High quality", box)
        self.thread_high1.setObjectName("SWDrawThreadHigh1")
        self.thread_draft1 = QtWidgets.QRadioButton("Draft quality", box)
        self.thread_draft1.setObjectName("SWDrawThreadDraft1")
        self.thread_high1.setChecked(True)
        lay.addWidget(self.thread_high1)
        lay.addWidget(self.thread_draft1)
        self.lay.addWidget(box)
        outer.addWidget(self.page1)
        # ---- page 2
        self.page2 = QtWidgets.QWidget(self.form)
        self.page2.setObjectName("SWDrawModelViewPage2")
        self.lay = QtWidgets.QVBoxLayout(self.page2)
        self.lay.setContentsMargins(0, 0, 0, 0)
        box, lay = _group("Reference Configuration", self.page2)
        self.config = QtWidgets.QComboBox(box)
        self.config.setObjectName("SWDrawConfiguration")
        self.config.addItem("Default")
        lay.addWidget(self.config)
        self.lay.addWidget(box)
        box, lay = _group("Orientation", self.page2)
        self.multiple = QtWidgets.QCheckBox("Create multiple views", box)
        self.multiple.setObjectName("SWDrawMultipleViews")
        self.multiple.toggled.connect(self.set_multiple)
        lay.addWidget(self.multiple)
        lay.addWidget(QtWidgets.QLabel("Standard views:", box))
        grid = QtWidgets.QGridLayout()
        self.orient = QtWidgets.QButtonGroup(box)
        names = list(CROSS) + list(MORE_VIEWS)
        for n, name in enumerate(names):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            orient_look(b, name)
            b.setCheckable(True)
            b.setObjectName("SWDrawOrient" + name)
            self.orient.addButton(b, n)
            if name in CROSS:
                grid.addWidget(b, *CROSS[name])
            else:
                b.hide()            # chosen from the More views list
            if name == "Front":
                b.setChecked(True)
        lay.addLayout(grid)
        lay.addWidget(QtWidgets.QLabel("More views:", box))
        self.more = QtWidgets.QListWidget(box)
        self.more.setObjectName("SWDrawMoreViews")
        self.more.setMaximumHeight(52)
        for name in MORE_VIEWS:
            it = QtWidgets.QListWidgetItem("*" + name)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked)
            self.more.addItem(it)
        self.more.itemChanged.connect(self.more_changed)
        lay.addWidget(self.more)
        self.preview = QtWidgets.QCheckBox("Preview", box)
        self.preview.setObjectName("SWDrawPreview")
        self.preview_pic = QtWidgets.QLabel(box)
        self.preview_pic.setObjectName("SWDrawPreviewPicture")
        self.preview_pic.hide()
        self.preview.toggled.connect(self.show_preview)
        self.orient.buttonClicked.connect(lambda *a: self.show_preview(self.preview.isChecked()))
        lay.addWidget(self.preview)
        lay.addWidget(self.preview_pic)
        self.lay.addWidget(box)
        box, lay = _group("Import options", self.page2)
        self.import_annotations = QtWidgets.QCheckBox("Import annotations", box)
        self.import_annotations.setObjectName("SWDrawImportAnnotations")
        self.design_annotations = QtWidgets.QCheckBox("Design annotations", box)
        self.design_annotations.setObjectName("SWDrawDesignAnnotations")
        self.design_annotations.setChecked(True)
        # live, never greyed: turning Design annotations on turns Import annotations on
        self.design_annotations.clicked.connect(
            lambda *_: self.design_annotations.isChecked() and not self.import_annotations.isChecked() and
            self.import_annotations.setChecked(True))
        lay.addWidget(self.import_annotations)
        lay.addWidget(self.design_annotations)
        self.lay.addWidget(box)
        box, lay = _group("Options", self.page2)
        self.projected = QtWidgets.QCheckBox("Auto-start projected view", box)
        self.projected.setObjectName("SWDrawAutoProjected")
        self.projected.setChecked(True)
        lay.addWidget(self.projected)
        self.lay.addWidget(box)
        save_form, self.form = self.form, self.page2
        mirror_group(self, "SWDraw")
        view_groups(self, None, "Sheet", 1.0, "Projected", "Draft quality", config=False, prefix="SWDraw")
        self.form = save_form

        boxes = {}
        for i in range(self.lay.count()):
            wdg = self.lay.itemAt(i).widget()
            if isinstance(wdg, QtWidgets.QGroupBox):
                boxes.setdefault(wdg.title(), wdg)
        at = self.lay.indexOf(boxes["Orientation"]) + 1 if "Orientation" in boxes else -1
        if at > 0:
            for title in ("Mirror", "Import options", "Display State", "Options"):
                b = boxes.get(title)
                if b is not None and b.parentWidget() is self.page2:
                    self.lay.removeWidget(b)
                    self.lay.insertWidget(at, b)
                    at += 1
        outer.addWidget(self.page2)
        self.lay = outer
        self.base = None
        self.next_button.clicked.connect(lambda: self.go_page(2))
        self.back_button.clicked.connect(lambda: self.go_page(1))
        self.sources.itemDoubleClicked.connect(lambda *a: self.go_page(2))
        self.thread_high1.toggled.connect(lambda on: (self.thread_high if on else self.thread_draft).setChecked(True))
        self.projected1.toggled.connect(lambda on: self.projected.isChecked() != on and self.projected.setChecked(on))
        self.projected.toggled.connect(lambda on: self.projected1.isChecked() != on and self.projected1.setChecked(on))
        self.go_page(1)

    def source_documents(self):
        ""
        return [d for d in source_documents() if d.FileName]

    def go_page(self, n):
        if n == 2 and self.source() is None:
            self.say("Select a part or assembly first (or Browse...).")
            return
        self.page1.setVisible(n == 1)
        self.page2.setVisible(n == 2)
        self.back_button.setVisible(n == 2)     # shown only where it goes somewhere (no greyed arrow)
        self.next_button.setVisible(n == 1)
        if n == 2:
            self.offer_flat_pattern()
            self.offer_named_views()
            self.say("Please select a named view from the list below and then place the view.\n"
                     "Note that the list of orientations corresponds to the named views saved in the model.")
        else:
            self.say("Select a part or assembly from which to create the view, then click Next.")
        self.current_page = n

    def more_changed(self, item):
        name = item.text().lstrip("*").replace("(A) Flat pattern", "Flat pattern")
        if item.checkState() == QtCore.Qt.Checked:
            for b in self.orient.buttons():
                if b.text() == name:
                    b.setChecked(True)
            if not self.multiple.isChecked():
                self.more.blockSignals(True)
                for i in range(self.more.count()):
                    if self.more.item(i) is not item:
                        self.more.item(i).setCheckState(QtCore.Qt.Unchecked)
                self.more.blockSignals(False)
        self.show_preview(self.preview.isChecked())

    def show_preview(self, on):
        self.preview_pic.setVisible(bool(on))
        if not on:
            return
        src = self.source()
        if src is None:
            return
        try:
            from . import drawpalette
            self.preview_pic.setPixmap(drawpalette.preview_icon(model_shapes(src), self.orientation(), 96,
                                                               orient_frame(src, self.orientation()))
                                       .pixmap(96, 96))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Model View preview: %s\n" % error)

    def offer_flat_pattern(self):
        ""
        try:
            from . import smflatview
            src = self.source()
            have = src is not None and smflatview.available(src)
        except Exception:
            have = False
        b = next((b for b in self.orient.buttons() if b.text() == "Flat pattern"), None)
        item = next((self.more.item(i) for i in range(self.more.count())
                     if self.more.item(i).text() == "(A) Flat pattern"), None)
        if have and b is None:
            b = QtWidgets.QToolButton(self.more.parentWidget())
            b.setText("Flat pattern")
            b.setCheckable(True)
            b.setObjectName("SWDrawOrientFlatPattern")
            b.hide()
            self.orient.addButton(b, len(self.orient.buttons()))
        if have and item is None:
            item = QtWidgets.QListWidgetItem("(A) Flat pattern")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            self.more.addItem(item)
        if not have and item is not None:
            self.more.takeItem(self.more.row(item))

    def offer_named_views(self):
        ""
        for i in reversed(range(self.more.count())):
            if self.more.item(i).data(QtCore.Qt.UserRole) == "named":
                self.more.takeItem(i)
        for b in [b for b in self.orient.buttons() if b.property("swNamedView")]:
            self.orient.removeButton(b)
            b.deleteLater()
        try:
            from . import drawpalette
            src = self.source()
            names = [n for n, _c in drawpalette.named_views(src)] if src is not None else []
        except Exception as _fw_err:
            _fw_log("drawings.py:named views", _fw_err)
            names = []
        for name in names:
            if name in ORIENTATIONS:
                continue
            b = QtWidgets.QToolButton(self.more.parentWidget())
            b.setText(name)
            b.setCheckable(True)
            b.setProperty("swNamedView", True)
            b.hide()
            self.orient.addButton(b, len(self.orient.buttons()))
            item = QtWidgets.QListWidgetItem(name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            item.setData(QtCore.Qt.UserRole, "named")
            self.more.addItem(item)

    def orientation(self):
        b = self.orient.checkedButton()
        return b.text() if b is not None else "Front"

    def orientations(self):
        return [b.text() for b in self.orient.buttons() if b.isChecked()] or ["Front"]

    def set_multiple(self, on):
        ""
        self.orient.setExclusive(not on)
        if not on:
            keep = self.orientation()
            for b in self.orient.buttons():
                b.setChecked(b.text() == keep)
        if on and self.projected.isChecked():
            self.projected.setChecked(False)     # several views at once: no projected view follows

    def dress(self, v):
        """The PM's Dimension Type, Cosmetic Thread Display, configuration and imported annotations on view v."""
        for name, val in (("SWDimensionType", "True" if self.dim_true.isChecked() else "Projected"),
                          ("SWCosmeticThreads", "High quality" if self.thread_high.isChecked() else "Draft quality"),
                          ("SWConfiguration", self.config.currentText()),
                          ("SWDisplayState", self.display_state.currentText())):
            if name not in v.PropertiesList:
                v.addProperty("App::PropertyString", name, "FreeCAD", "Model View option")
            setattr(v, name, val)
        how = mirror_choice(self)
        if how:
            from . import drawviews as DV
            try:
                DV.set_mirror(v, how)
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Mirror view: %s\n" % error)
        if self.import_annotations.isChecked() and self.design_annotations.isChecked():
            self.doc.recompute()
            import_annotations_later(self.page, v)

    MULTI_PLACES = {"Front": (0, 0), "Top": (0, 1), "Bottom": (0, -1), "Right": (1, 0), "Left": (-1, 0),
                    "Back": (2, 0), "Isometric": (1, 1), "Trimetric": (2, 1), "Dimetric": (-1, 1)}

    def place_multiple(self, shapes, p):
        ""
        box = None
        for o in shapes:
            try:
                b = o.Shape.BoundBox
            except Exception:
                continue
            box = App.BoundBox(b) if box is None else (box.add(b) or box)
        size = (box.DiagonalLength if box is not None else 50.0) * self._factor() * 0.8 + 15.0
        made = []
        for name in self.orientations():
            d, x = orient_frame(self.source(), name)
            i, j = self.MULTI_PLACES.get(name, (0, 0))
            s = 1.0 if third_angle(self.page) else -1.0
            if name in ("Top", "Bottom", "Right", "Left"):
                i, j = i * s, j * s
            v = new_view(self.page, shapes, _unit(d), _unit(x), (p[0] + i * size, p[1] + j * size), self._scale(),
                         self.style.currentText())
            self.dress(v)
            made.append(v)
        return made

    def _scale(self):
        """The custom scale, or None for Use sheet scale."""
        if self.use_custom.isChecked():
            s = parse_scale(self.scale_combo.currentText())
            return s if s and s > 0 else 1.0
        return None

    def sheet_move(self, p):
        ""

        try:
            if getattr(self, "current_page", 2) == 1 or self.multiple.isChecked() or \
                    self.orientation() == "Flat pattern":
                self.clicks.ghost(None)
                return
            src = self.source()
            if src is None:
                self.clicks.ghost(None)
                return
            key = (src.Name, self.orientation(), self._scale(), self.base is not None and self.projected.isChecked())
            if getattr(self, "_ghost_key", None) != key:
                self._ghost_key = key
                self._ghost_shapes = model_shapes(src)
                self._ghost_size = None
            if self.base is not None and self.projected.isChecked():
                projected_ghost(self.clicks, self.base, p, self._ghost_shapes, third_angle(self.page))
                return
            if self._ghost_size is None:
                d, x = orient_frame(src, self.orientation())
                self._ghost_size = ghost_size(self._ghost_shapes, d, x,
                                              placing_scale(self.page, self._ghost_shapes, self._scale()))
            self.clicks.ghost(p, self._ghost_size)
        except Exception as _fw_err:
            _fw_log("drawings.py:model view ghost", _fw_err)

    def _factor(self):
        s = self._scale()
        if s is not None:
            return s
        try:
            return float(self.page.Scale)
        except Exception:
            return 1.0

    def sheet_click(self, p):
        if getattr(self, "current_page", 2) == 1:
            if self.source() is None:
                self.say("Select a part or assembly first, then click Next.")
                return True
            self.go_page(2)          # a click on the sheet with a part picked: as Next, then place
        return self._place(p)

    def _place(self, p):
        src = self.source()
        if src is None:
            self.say("Select a part or assembly first.")
            return True
        if not saved_source(src, self.doc):
            return True
        shapes = model_shapes(src)
        if self.multiple.isChecked():
            made = self.place_multiple(shapes, p)
            self.made += made
            self.doc.recompute()
            self.say("%d views placed. Click to place them again, or OK." % len(made))
            return True
        if self.orientation() == "Flat pattern":
            from . import smflatview
            fv = smflatview.flat_view(src)
            v = new_view(self.page, [fv], _unit(fv.Normal), _unit(fv.XAxis), p, self._scale(), self.style.currentText())
            v.Label = "Flat pattern"
            if "SWFlatPattern" not in v.PropertiesList:
                v.addProperty("App::PropertyBool", "SWFlatPattern", "FreeCAD", "A flat pattern view")
            v.SWFlatPattern = True
            self.dress(v)
            try:
                from . import drawtables
                drawtables.flat_pattern_placed(self.page, v)
            except Exception as _fw_err:
                _fw_log("drawings.py:2116", _fw_err)
            self.base = v
            self.made.append(v)
            self.doc.recompute()
            self.say("Flat pattern placed. OK when done.")
            return True
        if self.base is None or not self.projected.isChecked():
            d, x = orient_frame(src, self.orientation())
            v = new_view(self.page, shapes, _unit(d), _unit(x), p, self._scale(), self.style.currentText())
            if self.orientation() not in ORIENTATIONS:
                _name_orientation(v, self.orientation())     # a named view (a saved section view shows cut)
            self.dress(v)
            self.base = v
            self.made.append(v)
            self.say("Click to place projected views from %s; OK when done." % v.Label)
            if self.projected.isChecked():

                # the Projected View PM opens on it (Use parent style / scale, Arrow); each click places another

                page, me = self.page, self

                def _projected():
                    if SHOWN and SHOWN[0] is me and Gui.Control.activeDialog():
                        panel = ProjectedViewPanel(page, v)
                        panel.keep_placing = True
                        _show(panel)
                QtCore.QTimer.singleShot(0, _projected)
        else:
            bx, by = view_position(self.base)
            d, x, name = projected_frame(self.base, p[0] - bx, p[1] - by, third_angle(self.page))
            v = new_view(self.page, shapes, d, x, aligned_place(name, p, (bx, by)), self._scale(),
                         self.style.currentText())
            follow_parent_scale(v, self.base)
            set_parent(v, self.base)
            self.made.append(v)
        self.doc.recompute()
        return True


def aligned_place(name, p, parent_at):
    ""
    if name in ("Right", "Left"):
        return p[0], parent_at[1]
    if name in ("Top", "Bottom"):
        return parent_at[0], p[1]
    return p


def follow_parent_scale(v, parent):
    ""
    if getattr(parent, "ScaleType", "") == "Page":
        v.ScaleType = "Page"
    else:
        v.ScaleType = "Custom"
        v.Scale = float(parent.getScale()) if hasattr(parent, "getScale") else float(parent.Scale)
    set_scale_mode(v, "Parent")


def flip_projected(page):
    ""

    moved = []
    doc = page.Document
    for v in views_of(page):
        if v.TypeId not in ("TechDraw::DrawViewPart",) or getattr(v, "SWAuxiliary", "") or \
                getattr(v, "SWFlatPattern", False) or getattr(v, "SWCutListItem", ""):
            continue
        parent = doc.getObject(getattr(v, "SWParent", "") or "")
        if parent is None or parent not in views_of(page):
            continue
        try:
            dot = abs(_unit(v.Direction).dot(_unit(parent.Direction)))
        except Exception as _fw_err:
            _fw_log("drawings.py:2204", _fw_err)
            continue
        if dot > 1e-6:
            continue                    # not an orthographic neighbour (an iso, a section...)
        px, py = view_position(parent)
        x, y = view_position(v)
        if abs(x - px) < 1e-6 and abs(y - py) < 1e-6:
            continue
        nx, ny = (2 * px - x, y) if abs(y - py) < abs(x - px) else (x, 2 * py - y)
        for prop, val in (("X", nx), ("Y", ny)):
            try:
                if v.ExpressionEngine and any(e[0] == prop for e in v.ExpressionEngine):
                    continue            # it follows its parent by an expression: leave that
            except Exception as _fw_err:
                _fw_log("drawings.py:2188", _fw_err)
            setattr(v, prop, val)
        moved.append(v)
    return moved


def set_parent(v, parent):
    """Remembers the view a view was made from (Default Alignment, Break Alignment)."""
    if "SWParent" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWParent", "FreeCAD", "the view this one was projected from")
    v.SWParent = parent.Name
    try:
        from . import drawviewcmds
        drawviewcmds.install_alignment()
    except Exception as _fw_err:
        _fw_log("drawings.py:2203", _fw_err)


def annotation_view_name(view):
    ""
    d = getattr(view, "Direction", None)
    names = {(0, 0, 1): "Top", (0, 0, -1): "Bottom", (0, -1, 0): "Front", (0, 1, 0): "Back", (1, 0, 0): "Right",
             (-1, 0, 0): "Left"}
    if d is not None:
        key = tuple(int(round(c)) if abs(abs(c) - round(abs(c))) < 1e-6 else 9 for c in (d.x, d.y, d.z))
        if key in names:
            return "(A) " + names[key]
    return "(A) " + getattr(view, "Label", "View")


def _import_group(panel, title="Options", prefix="SWView", parent=None):
    ""

    box, lay = _group(title, panel.form)
    lay.addWidget(QtWidgets.QLabel("Annotation view(s):", box))
    panel.annotation_views = QtWidgets.QListWidget(box)
    panel.annotation_views.setObjectName(prefix + "AnnotationViews")
    panel.annotation_views.setMaximumHeight(40)
    src = parent if parent is not None else getattr(panel, "parent", None)
    if src is not None:
        it = QtWidgets.QListWidgetItem(annotation_view_name(src), panel.annotation_views)
        it.setCheckState(QtCore.Qt.Checked)
        it.setFlags(QtCore.Qt.ItemIsEnabled)
    # drawings-land274 (NO DEAD CONTROLS): shown, not greyed: the view the annotations come from, read as a label
    panel.annotation_views.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
    panel.annotation_views.setFocusPolicy(QtCore.Qt.NoFocus)
    lay.addWidget(panel.annotation_views)
    panel.import_annotations = QtWidgets.QCheckBox("Import annotations", box)
    panel.import_annotations.setObjectName(prefix + "ImportAnnotations")
    panel.design_annotations = QtWidgets.QCheckBox("Design annotations", box)
    panel.design_annotations.setObjectName(prefix + "DesignAnnotations")
    panel.design_annotations.setChecked(False)
    panel.mbd_annotations = QtWidgets.QCheckBox("MBD dimension annotations", box)
    panel.mbd_annotations.setObjectName(prefix + "MBDAnnotations")
    panel.include_hidden = QtWidgets.QCheckBox("Include items from hidden features", box)
    panel.include_hidden.setObjectName(prefix + "IncludeHidden")
    for w in (panel.design_annotations, panel.mbd_annotations, panel.include_hidden):
        # live, never greyed: turning one on turns Import annotations on
        w.clicked.connect(lambda *_, w=w: w.isChecked() and not panel.import_annotations.isChecked() and
                          panel.import_annotations.setChecked(True))

    # Import annotations ticked with nothing under it picked: Design annotations comes on with it
    panel.import_annotations.clicked.connect(
        lambda on: on and not (panel.design_annotations.isChecked() or panel.mbd_annotations.isChecked()) and
        panel.design_annotations.setChecked(True))
    lay.addWidget(panel.import_annotations)
    lay.addWidget(panel.design_annotations)
    lay.addWidget(panel.mbd_annotations)
    lay.addWidget(panel.include_hidden)
    panel.lay.addWidget(box)
    return box


def run_import(panel, v):
    """The Import annotations choices of panel onto its new view v."""
    if getattr(panel, "import_annotations", None) is None:
        return False
    if not panel.import_annotations.isChecked():
        return False
    design, mbd = panel.design_annotations.isChecked(), panel.mbd_annotations.isChecked()
    # the view keeps its Import options (its Drawing View PM shows them, and changing them there imports again)
    for prop, val in (("SWImportAnnotations", True), ("SWImportDesign", design), ("SWImportDimXpert", mbd),
                      ("SWImportHidden", panel.include_hidden.isChecked())):
        try:
            if prop not in v.PropertiesList:
                v.addProperty("App::PropertyBool", prop, "FreeCAD", "Import annotations option")
            setattr(v, prop, bool(val))
        except Exception as _fw_err:
            _fw_log("drawings.py:2267", _fw_err)
    if design or mbd:
        import_annotations_later(panel.page, v, design=design, mbd=mbd, hidden=panel.include_hidden.isChecked())
    return True


def label_font_row(panel, lay, prefix):
    """[x] Document font and Font... (greyed while the document font is used): the view label's own font."""
    f = panel.form
    row = QtWidgets.QHBoxLayout()
    panel.doc_font = QtWidgets.QCheckBox("Document font", f)
    panel.doc_font.setObjectName(prefix + "DocumentFont")
    panel.doc_font.setChecked(True)
    panel.font_button = QtWidgets.QPushButton("Font...", f)
    panel.font_button.setObjectName(prefix + "FontButton")
    panel.label_font = None

    def pick():
        from . import drawpmparts as PP
        dlg = PP.ChooseFontDialog(panel.label_font[0] if panel.label_font else "osifont",
                                  height=float(panel.label_font[1]) if panel.label_font else 3.5)
        if dlg.exec_():
            r = dlg.result()
            panel.label_font = (r["family"], max(1.0, r["height"]))
            panel.doc_font.setChecked(False)     # a font picked here is the label's own (live, never greyed)
    panel.font_button.clicked.connect(pick)
    row.addWidget(panel.doc_font)
    row.addWidget(panel.font_button)
    lay.addLayout(row)


def apply_label_font(panel, view):
    """Document font off with a font picked: the view's label (SECTION A-A / DETAIL B, scale) drawn in that font
    under the view; TechDraw's own label then shows only while the view is picked."""
    if getattr(panel, "doc_font", None) is None or panel.doc_font.isChecked() or not panel.label_font:
        return None
    return label_in_font(view, *panel.label_font)


def label_in_font(view, family, size):
    from . import drawannot as DA, drawviews as DV
    doc = view.Document
    page = next((o for o in view.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return None
    for o in list(page.Views):
        if getattr(o, "SWLabelOf", "") == view.Name:
            doc.removeObject(o.Name)
    for name, val, kind in (("SWLabelFont", family, "App::PropertyString"), ("SWLabelSize", size, "App::PropertyFloat")):
        if name not in view.PropertiesList:
            view.addProperty(kind, name, "FreeCAD", "the view label's own font")
        setattr(view, name, val)
    lines = DA.location_text(view)[:2]
    a, b, c, d = DV.view_box(view) if view.TypeId != "TechDraw::DrawViewDetail" else DA._detail_box(view)
    body = "".join('<text x="0" y="%g" font-family="%s" font-size="%g" text-anchor="middle">%s</text>'
                   % (j * size * 1.4, DA._esc(family), size, DA._esc(t)) for j, t in enumerate(lines))
    obj = DA.svg_symbol(page, "ViewLabel", body, DA._text_width(max(lines, key=len)) / 2 + 5, ((a + c) / 2, b - 6),
                        "%s label" % view.Label, "ViewLabel")
    obj.addProperty("App::PropertyString", "SWLabelOf", "FreeCAD", "the view it labels")
    obj.SWLabelOf = view.Name
    try:
        view.ViewObject.KeepLabel = False
    except Exception as _fw_err:
        _fw_log("drawings.py:2331", _fw_err)
    doc.recompute()
    return obj


def _finish_child(panel, v):
    """What Projected and Auxiliary View do with the placed view: the PM's choices, the arrow, annotations."""
    apply_view_groups(panel, v, panel.parent)
    set_parent(v, panel.parent)
    panel.doc.recompute()
    if panel.arrow.isChecked():
        from . import drawviews as DV
        letter = panel.arrow_label.text().strip() or DV.take_label(panel.page)
        if letter == getattr(panel.page, "FreeWorksNextViewLabel", None):
            DV.take_label(panel.page)
        made = view_arrow(panel.page, panel.parent, v, letter)
        panel.made += list(made)
        _setp(v, "SWViewLetter", letter)
    run_import(panel, v)


def _setp(o, name, val):
    if name not in o.PropertiesList:
        o.addProperty("App::PropertyString", name, "FreeCAD", "FreeCAD")
    setattr(o, name, val)


class ProjectedPickPanel(_Panel):
    ""

    TITLE = "Projected View"
    PIXMAP = "TechDraw_ProjectionGroup"

    def build(self):
        self.say("Select a drawing view from which to create the projected view.")

    def sheet_click(self, p):
        from . import drawviews
        v = drawviews.view_at(self.page, p, 0.0)
        if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
            self.say("Select a drawing view from which to create the projected view.")
            return True
        page = self.page
        QtCore.QTimer.singleShot(0, lambda: _show(ProjectedViewPanel(page, v)))
        return True


class ProjectedViewPanel(_Panel):
    TITLE = "Projected View"
    PIXMAP = "TechDraw_ProjectionGroup"

    def __init__(self, page, parent):
        self.parent = parent
        super().__init__(page)

    def build(self):
        self.say("Click in the graphics area to place the new view.")
        arrow_group(self, self.page)
        _import_group(self)
        view_groups(self, self.parent, "Parent", float(self.parent.getScale()) if hasattr(self.parent, "getScale")
                    else float(self.parent.Scale), getattr(self.parent, "SWDimensionType", "") or "Projected",
                    getattr(self.parent, "SWCosmeticThreads", "") or "Draft quality")

        ref = self.form.findChild(QtWidgets.QGroupBox, "SWDrawGroup_ReferenceConfiguration")
        arrow = getattr(self, "arrow_box", None)
        if ref is not None and arrow is not None and self.lay.indexOf(ref) > self.lay.indexOf(arrow) >= 0:
            self.lay.removeWidget(ref)
            self.lay.insertWidget(self.lay.indexOf(arrow), ref)

    def sheet_move(self, p):
        try:
            projected_ghost(self.clicks, self.parent, p, third=third_angle(self.page))
        except Exception as _fw_err:
            _fw_log("drawings.py:projected ghost", _fw_err)

    def sheet_click(self, p):
        bx, by = view_position(self.parent)
        d, x, name = projected_frame(self.parent, p[0] - bx, p[1] - by, third_angle(self.page))
        v = new_view(self.page, self.parent.XSource or self.parent.Source, d, x, aligned_place(name, p, (bx, by)),
                     float(self.parent.getScale()) if hasattr(self.parent, "getScale") else float(self.parent.Scale),
                     self.style.currentText())
        _finish_child(self, v)
        self.made.append(v)
        self.doc.recompute()
        if getattr(self, "keep_placing", False):

            # projected view of it until OK or Esc (Drawing Basics video 1:40)
            self.say("Click to place more projected views, then OK.")
            return True

        QtCore.QTimer.singleShot(0, self.accept)
        return True

    def reject(self):
        if getattr(self, "keep_placing", False) and self.made:

            return self.accept()
        return _Panel.reject(self)


class AuxiliaryViewPanel(_Panel):
    TITLE = "Auxiliary View"
    PIXMAP = "TechDraw_ProjectionGroup"

    def __init__(self, page, parent, edge):
        self.parent, self.edge = parent, edge
        super().__init__(page)

    def build(self):
        if self.edge is None:

            self.say("Please select a Reference Edge to continue")
            _status("Select an edge, an arc, or a sketch line from which to unfold the view")
            box, lay = _group("Cosmetic Thread Display", self.form)
            self.thread_high = QtWidgets.QRadioButton("High quality", box)
            self.thread_high.setObjectName("SWAuxThreadHigh")
            self.thread_draft = QtWidgets.QRadioButton("Draft quality", box)
            self.thread_draft.setObjectName("SWAuxThreadDraft")
            self.thread_draft.setChecked(True)      # one picked, as the views' default (never both off)
            lay.addWidget(self.thread_high)
            lay.addWidget(self.thread_draft)
            self.lay.addWidget(box)
            return
        self.say("Click in the graphics area to place the new view.")
        arrow_group(self, self.page)
        self.flip = QtWidgets.QCheckBox("Flip direction", self.form)
        self.flip.setObjectName("SWViewArrowFlip")
        self.lay.itemAt(self.lay.count() - 1).widget().layout().addWidget(self.flip)
        _import_group(self)
        view_groups(self, self.parent, "Parent", float(self.parent.getScale()) if hasattr(self.parent, "getScale")
                    else float(self.parent.Scale), getattr(self.parent, "SWDimensionType", "") or "Projected",
                    getattr(self.parent, "SWCosmeticThreads", "") or "Draft quality")

    def getStandardButtons(self):
        if self.edge is None:
            return QtWidgets.QDialogButtonBox.Cancel
        return super().getStandardButtons()

    def pick_edge(self, p):
        """Page 1: the click picks the reference edge (a straight edge of a view); page 2 opens."""
        from . import drawannot as DA
        from . import drawviews as DV
        v = DV.view_at(self.page, p)
        if v is None:
            return True
        k = DV.view_scale(v)
        hit = DA.edge_at(v, DV.to_geometry(v, p), 3.0 / k)
        if hit is None:
            return True
        i, e = hit
        if type(getattr(e, "Curve", None)).__name__ not in ("Line", "LineSegment"):
            _status("Select an edge, an arc, or a sketch line from which to unfold the view")
            return True
        thread = "High quality" if self.thread_high.isChecked() else (
            "Draft quality" if self.thread_draft.isChecked() else "")
        page = self.page

        def page2():
            self.clicks.stop()
            self.doc.abortTransaction()
            Gui.Control.closeDialog()
            panel = AuxiliaryViewPanel(page, v, i)
            if thread:
                for w in panel.form.findChildren(QtWidgets.QRadioButton):
                    box = w.parent()
                    if w.text() == thread and getattr(box, "title", lambda: "")() == "Cosmetic Thread Display":
                        w.setChecked(True)
            Gui.Control.showDialog(panel)
        QtCore.QTimer.singleShot(0, page2)
        return True

    def sheet_click(self, p):
        if self.edge is None:
            return self.pick_edge(p)
        bx, by = view_position(self.parent)
        dx, dy = p[0] - bx, p[1] - by
        d, x = auxiliary_frame(self.parent, self.edge, dx, dy)
        if self.flip.isChecked():
            d, x = -d, -x
        scale = float(self.parent.getScale()) if hasattr(self.parent, "getScale") else float(self.parent.Scale)
        v = new_view(self.page, self.parent.XSource or self.parent.Source, d, x, p, scale, self.style.currentText())
        # an auxiliary view: labelled as Document Properties > Views > Auxiliary says (VIEW A)
        v.addProperty("App::PropertyString", "SWAuxiliary", "FreeCAD", "Auxiliary view letter")
        try:
            from . import drawviews as DV
            v.SWAuxiliary = DV.take_label(self.page)
        except Exception:
            v.SWAuxiliary = chr(ord("A") + len([o for o in self.doc.Objects if getattr(o, "SWAuxiliary", "")]) % 26)
        try:
            from . import drawdocprops as DDP
            DDP.label_view(v, dict(DDP.defaults(), **DDP.stored(self.doc)))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: auxiliary view label: %s\n" % error)
        _finish_child(self, v)
        try:
            from . import drawviewcmds as VC
            VC.install_alignment()
            if VC.keep_aligned(v):
                self.doc.recompute()
        except Exception as _fw_err:
            _fw_log("drawings.py:auxiliary aligned", _fw_err)
        self.made.append(v)
        self.doc.recompute()
        QtCore.QTimer.singleShot(0, self.accept)
        return True


# --------------------------------------------------------------------------- picks
def preselected_view(page):
    ""
    try:
        for sel in Gui.Selection.getSelectionEx("", 0):
            o = sel.Object
            if o is not None and o.isDerivedFrom("TechDraw::DrawViewPart") and o in views_of(page):
                return o
    except Exception as _fw_err:
        _fw_log("drawings.py:2527", _fw_err)
    return None


def picked_view_and_edge():
    """(the picked part view, its picked edge index or None), else (None, None)."""
    for sel in Gui.Selection.getSelectionEx("", 0):
        obj = sel.Object
        for sub in sel.SubElementNames or ("",):
            last = sub.split(".")[-1] if sub else ""
            target = obj
            if sub and "." in sub:
                try:
                    target = obj.getSubObject(sub.rsplit(".", 1)[0] + ".", retType=1) or obj
                except Exception:
                    target = obj
            if not target.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            if last.startswith("Edge"):
                try:
                    return target, int(last[4:])
                except ValueError as _fw_err:
                    _fw_log("drawings.py:2549", _fw_err)
            return target, None
    return None, None


VIEW_PM = []      # the Drawing View PM opened by picking a view (drawselect), when it is the open dialog


SHOWN = []      # the drawing PropertyManager _show opened last


def _ours_open():
    """The open task dialog is one of the drawing PropertyManagers (and no sketch is being edited)."""
    if not SHOWN:
        return False
    try:
        gd = Gui.ActiveDocument
        if gd is not None and gd.getInEdit() is not None:
            return False
    except Exception as _fw_err:
        _fw_log("drawings.py:2569", _fw_err)
    try:
        forms = SHOWN[0].form
        forms = forms if isinstance(forms, (list, tuple)) else [forms]
        return any(f is not None and f.isVisible() for f in forms)
    except Exception as _fw_err:
        _fw_log("drawings.py:2605", _fw_err)
        return False


def busy():
    ""

    if not Gui.Control.activeDialog():
        return False
    return not VIEW_PM and not _ours_open()


def end_open_pm():
    ""
    if not SHOWN or not Gui.Control.activeDialog():
        SHOWN[:] = []
        return
    panel = SHOWN[0]
    SHOWN[:] = []
    try:
        if getattr(panel, "made", None):
            panel.accept()
        else:
            panel.reject()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: ending the open PropertyManager: %s\n" % error)
    QtWidgets.QApplication.processEvents()


def _show(panel):
    if VIEW_PM:
        try:
            VIEW_PM[0].close_quietly()
        except Exception:
            VIEW_PM[:] = []
    for _ in range(3):              # an OK can start a follow-on PM (Model View -> Projected View): end that too
        if Gui.Control.activeDialog() and _ours_open():
            end_open_pm()
        else:
            break
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    Gui.Control.showDialog(panel)
    SHOWN[:] = [panel]
    _close_with_document(panel)
    _end_step_on_close(panel)
    return panel


def _end_step_on_close(panel):
    ""


    name = getattr(getattr(panel, "doc", None), "Name", None)
    if not name:
        return
    timer = QtCore.QTimer()
    timer.setInterval(250)

    def stop():
        timer.stop()
        try:
            _STEP_TIMERS.remove(timer)
        except ValueError as _fw_err:
            _fw_log("drawings.py:end step timer", _fw_err)

    def check():
        try:
            doc = App.listDocuments().get(name)
            if doc is None or not (SHOWN and SHOWN[0] is panel):
                return stop()
            if Gui.Control.activeDialog():
                return                                # still open (or a follow-on PM of its own)
            stop()
            keep = bool(getattr(panel, "made", None))
            if doc.HasPendingTransaction:
                try:
                    panel.clicks.stop()
                except Exception as _fw_err:
                    _fw_log("drawings.py:end step clicks", _fw_err)
                if keep:
                    doc.commitTransaction()
                else:
                    doc.abortTransaction()
                doc.recompute()
            # FreeCAD's own step for the command (its menu text) stays open when the PM is closed from outside
            close_command_step(keep)
            SHOWN[:] = []
        except Exception as _fw_err:
            _fw_log("drawings.py:end step", _fw_err)
            stop()

    timer.timeout.connect(check)
    _STEP_TIMERS.append(timer)
    timer.start()


_STEP_TIMERS = []


def close_command_step(keep=True):
    """The command's Undo step FreeCAD opened when the tool started (named after its menu text), closed once no
    PM is open: kept, or dropped when keep is False. Returns True when one was closed."""
    try:
        if Gui.Control.activeDialog() or not App.getActiveTransaction():
            return False
        App.closeActiveTransaction(not keep)
        return True
    except Exception as _fw_err:
        _fw_log("drawings.py:command step", _fw_err)
        return False


def _close_with_document(panel):
    ""

    name = getattr(getattr(panel, "doc", None), "Name", None)
    if not name:
        return
    timer = QtCore.QTimer()
    timer.setInterval(500)

    def check():
        if name in App.listDocuments():
            if Gui.Control.activeDialog():
                return
        else:
            try:
                still = (SHOWN and SHOWN[0] is panel) or (VIEW_PM and VIEW_PM[0] is panel)
                if Gui.Control.activeDialog() and still:
                    Gui.Control.closeDialog()       # only this drawing's PM, never one opened since for another doc
                if SHOWN and SHOWN[0] is panel:
                    SHOWN[:] = []
            except Exception as _fw_err:
                _fw_log("drawings.py:2643", _fw_err)
        timer.stop()
        try:
            _DOC_TIMERS.remove(timer)
        except ValueError as _fw_err:
            _fw_log("drawings.py:2648", _fw_err)
    timer.timeout.connect(check)
    _DOC_TIMERS.append(timer)
    timer.start()


_DOC_TIMERS = []


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawStandard3View": ("Standard 3 View", "TechDraw_ProjectionGroup",
                                    "Adds three standard, orthographic views (Front, Top, Right)."),
    "FreeWorks_DrawModelView": ("Model View", "TechDraw_View",
                                "Adds a view of a part or assembly, from a named orientation."),
    "FreeWorks_DrawProjectedView": ("Projected View", "TechDraw_ProjectionGroup",
                                    "Adds a view projected from the picked view, on the side you click."),
    "FreeWorks_DrawAuxiliaryView": ("Auxiliary View", "TechDraw_ProjectionGroup",
                                    "Adds a view square to the picked straight edge of a view."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": pixmap(self.pixmap)}

    def IsActive(self):
        page = active_page()
        if page is None or busy() or not sheet_shown(page):
            return False
        if self.name == "FreeWorks_DrawProjectedView":
            return picked_view_and_edge()[0] is not None or bool(views_of(page))
        if self.name == "FreeWorks_DrawAuxiliaryView":
            return bool(views_of(page))
        return True

    def Activated(self):
        page = active_page()
        if page is None:
            return
        sheet_defaults(page)
        if self.name == "FreeWorks_DrawStandard3View":
            _show(Standard3ViewPanel(page))
        elif self.name == "FreeWorks_DrawModelView":
            _show(ModelViewPanel(page))
        elif self.name == "FreeWorks_DrawProjectedView":
            v, _ = picked_view_and_edge()
            if v is None:
                vs = views_of(page)
                v = vs[0] if len(vs) == 1 else None
            if v is None:
                _show(ProjectedPickPanel(page))
                return
            _show(ProjectedViewPanel(page, v))
        elif self.name == "FreeWorks_DrawAuxiliaryView":
            v, e = picked_view_and_edge()
            if v is not None and e is not None:
                try:
                    ed = v.getEdgeByIndex(e)
                    if len(ed.Vertexes) < 2 or not hasattr(ed.Curve, "Direction") and \
                            type(ed.Curve).__name__ not in ("Line", "LineSegment"):
                        v = e = None
                except Exception as _fw_err:
                    _fw_log("drawings.py:2715", _fw_err)
            if v is None or e is None:

                _show(AuxiliaryViewPanel(page, None, None))
                return
            _show(AuxiliaryViewPanel(page, v, e))


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("drawings.py:2727", _fw_err)


def register():
    watch_saves()
    try:
        from . import drawshade
        drawshade.register()
    except Exception as _fw_err:
        _fw_log("drawings.py:2736", _fw_err)
    try:
        from . import drawhud
        drawhud.register()          # Heads-up View on a sheet: Zoom to Area, Previous View, 3D Drawing View
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: heads-up sheet commands: %s\n" % error)
    try:
        from . import drawthread
        drawthread.register()       # Insert > Annotations > Cosmetic Thread on a drawing
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing Cosmetic Thread: %s\n" % error)
    try:
        from . import drawauto
        drawauto.register()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Auto-Generate Drawing: %s\n" % error)
    try:
        from . import drawrefhl
        drawrefhl.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: referenced elements highlight: %s\n" % error)
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    QtCore.QTimer.singleShot(2500, drawn_command_icons)     # the drawn set, once every drawing command is there


# --------------------------------------------------------------------------- Make Drawing from Part/Assembly
SAVE_FIRST_ANSWER = [None]      # checks: "save" / "cancel" answers the box without showing it


def save_source_first(source):
    ""

    if source is None or source.FileName:
        return True
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setObjectName("FW_SaveSource")
    box.setWindowTitle("FreeCAD")
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setTextFormat(QtCore.Qt.RichText)
    box.setText('<span style="color:#1f5fa8; font-size:12pt;">Save this file?</span>')
    box.setInformativeText("The file must be saved before it is inserted into the drawing.")
    save = box.addButton("Save and Insert", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
    answer = SAVE_FIRST_ANSWER[0]
    if answer is None:
        box.exec()
        ok = box.clickedButton() is save
    else:
        ok = answer == "save"
    if not ok:
        return False
    return save_model(source)


def save_model(source):
    ""


    try:
        App.setActiveDocument(source.Name)
        Gui.ActiveDocument = Gui.getDocument(source.Name)
    except Exception as _fw_err:
        _fw_log("drawings.py:2799", _fw_err)
    try:
        from . import saveas
        if SAVE_AS_HOOK is not None:
            path = SAVE_AS_HOOK(source.Label + ".FCStd")
            if path:
                saveas.save_as(source, path, saveas.save_types(source)[0][0])
        else:
            saveas.save_as(source)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s not saved: %s\n" % (source.Label, error))
    try:
        if source.FileName:
            Gui.getDocument(source.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("drawings.py:2814", _fw_err)
    return bool(source.FileName)


class _FitWhileOpening(QtCore.QObject):
    """A new drawing's sheet fitted again each time its window changes size while the drawing opens (the View
    Palette and the PropertyManager open beside it after the first fit, which left the title block's right part
    under the palette: look audit BB38 DR-A). Stops after a few seconds."""
    LIVE = []

    def __init__(self, page, seconds=6.0):
        super().__init__()
        self.page = page
        self.view = page_view(page)
        if self.view is None:
            return
        self.view.viewport().installEventFilter(self)
        _FitWhileOpening.LIVE.append(self)
        QtCore.QTimer.singleShot(int(seconds * 1000), self.stop)

    def stop(self):
        try:
            if self.view is not None:
                self.view.viewport().removeEventFilter(self)
        except Exception as _fw_err:
            _fw_log("drawings.py:fit stop", _fw_err)
        self.view = None
        if self in _FitWhileOpening.LIVE:
            _FitWhileOpening.LIVE.remove(self)

    def eventFilter(self, obj, event):
        try:
            if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.Resize:
                pg = self.page
                QtCore.QTimer.singleShot(0, lambda: fit_page(pg))
        except Exception as _fw_err:
            _fw_log("drawings.py:fit resize", _fw_err)
        return False


def fit_while_opening(page):
    """Fit the new sheet now and whenever its window is resized in the next seconds."""
    def _go():
        try:
            if not any(f.page is page for f in _FitWhileOpening.LIVE):
                _FitWhileOpening(page)
            fit_page(page)
        except Exception as _fw_err:
            _fw_log("drawings.py:fit while opening", _fw_err)
    for ms in (300, 1000, 2800):
        QtCore.QTimer.singleShot(ms, _go)


def fit_page(page):
    """Zoom to Fit on the sheet's own window, whichever window is active."""
    try:
        gdoc = Gui.getDocument(page.Document.Name)
        for v in gdoc.mdiViewsOfType("TechDrawGui::MDIViewPage"):
            try:
                if v.getPage().Name != page.Name:
                    continue
            except Exception as _fw_err:
                _fw_log("drawings.py:2827", _fw_err)
            v.sendMessage("ViewFit")
            clear_of_pane(page)
            return True
    except Exception as _fw_err:
        _fw_log("drawings.py:2831", _fw_err)
    try:
        Gui.SendMsgToActiveView("ViewFit")
        clear_of_pane(page)
    except Exception as _fw_err:
        _fw_log("drawings.py:2835", _fw_err)
    return False


def clear_of_pane(page):
    ""


    v = page_view(page)
    if v is None:
        return False
    try:
        pane = Gui.getMainWindow().findChild(QtWidgets.QFrame, "SWTaskPane")
        if pane is None or not pane.isVisible() or getattr(pane, "floating", False):
            return False
        vp = v.viewport()
        vg = QtCore.QRect(vp.mapToGlobal(QtCore.QPoint(0, 0)), vp.size())
        pg = QtCore.QRect(pane.mapToGlobal(QtCore.QPoint(0, 0)), pane.size())
        if not vg.intersects(pg):
            return False
        cover = vg.right() - pg.left() + 1
        if cover <= 0 or cover > vg.width() * 0.6:
            return False
        sheet = v.scene().itemsBoundingRect()
        seen = v.mapFromScene(sheet).boundingRect()
        room = vg.width() - cover - 8
        if seen.right() <= room:
            return False
        f = min(1.0, room / float(max(1, seen.width())))
        if f < 1.0:
            v.scale(f, f)
        k = v.transform().m11() or 1.0
        c = sheet.center()
        v.centerOn(QtCore.QPointF(c.x() + (cover / 2.0) / k, c.y()))
        return True
    except Exception as _fw_err:
        _fw_log("drawings.py:clear_of_pane", _fw_err)
        return False


def fill_template_views(doc, source):
    ""


    bases = []
    for o in doc.Objects:
        if not o.isDerivedFrom("TechDraw::DrawViewPart") or o.isDerivedFrom("TechDraw::DrawViewDetail"):
            continue
        if o.isDerivedFrom("TechDraw::DrawViewSection") or getattr(o, "BaseView", None) is not None:
            continue
        if (getattr(o, "SWParent", "") or "") and doc.getObject(o.SWParent) is not None:
            continue
        bases.append(o)
    if not bases:
        return []
    try:
        from . import drawlayout
        return drawlayout.replace_model(bases, source)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing template views: %s\n" % error)
        return []


def make_drawing(source=None, path=None, palette=True, template=None):
    ""



    from . import newdoc
    source = source or newdoc.source_document()
    if source is None:
        return None
    if not save_source_first(source):
        return None
    if not newdoc._saved(source, "a drawing"):
        return None
    if template is None:
        try:
            from . import drawtemplates      # Default Templates > Prompt user to select document template
            template = drawtemplates.pick_drawing_template()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: drawing templates: %s\n" % error)
            template = ""
        if template is None:
            return None
    if template:
        from . import drawtemplates      # a drawing template: its sheets, format and properties
        doc = drawtemplates.open_drawing_template(template)
    else:
        stem = {k[0]: k[4] for k in newdoc.KINDS}["Drawing"]
        name = newdoc._next_name(stem)
        doc = App.newDocument(name)
        doc.Label = name
    if path:
        doc.saveAs(path)
        try:
            # App's save leaves the GUI document "modified" (title asterisk, Save prompt on close: ChatGPT C13-01)
            Gui.getDocument(doc.Name).Modified = False
        except Exception as _fw_err:
            _fw_log("drawings.py:2875", _fw_err)
    else:
        temp_save(doc)
    set_made_from(doc, source)
    if template:
        fill_template_views(doc, source)
    try:
        Gui.activateWorkbench("TechDrawWorkbench")
    except Exception as _fw_err:
        _fw_log("drawings.py:2882", _fw_err)
    pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"] if template else []
    if pages:
        page = pages[0]
    else:
        page = newdoc.new_sheet(doc, show=False)
        newdoc.ask_sheet_format(page)
    sheet_defaults(page)
    try:
        from . import drawsheet
        drawsheet.sw_names(doc)
    except Exception as _fw_err:
        _fw_log("drawings.py:2894", _fw_err)
    doc.recompute()
    newdoc.show_sheet(page)
    fit_while_opening(page)
    if palette:
        try:
            from . import drawpalette
            drawpalette.note_source(source)
            for ms in (400, 1200, 2500):
                QtCore.QTimer.singleShot(ms, lambda n=source.Name: _palette_for(n))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: View Palette: %s\n" % error)
    if not path:
        # a holding file only: closing asks to save, Ctrl+S asks where (the sheet set-up above cleared it)
        _modified(doc)
        QtCore.QTimer.singleShot(500, lambda: App.getDocument(doc.Name) and _modified(doc)
                                 if doc.Name in App.listDocuments() else None)
    return doc
