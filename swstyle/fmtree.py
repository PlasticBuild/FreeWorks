# SPDX-License-Identifier: LGPL-2.1-or-later
""




























_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths, sketchstatus, treefolders
from .widgets import alive

Qt = QtCore.Qt

PARAM = "FeatureManagerLayout"
BODY = "PartDesign::Body"
ORIGIN = "App::Origin"
FOLDER_TYPE = "SWStyle::SolidBodies"

PLANES = ("XZ_Plane", "XY_Plane", "YZ_Plane")
HISTORY_SIZE = 10
SOON = 30            # ms from a change in FreeCAD's tree to the rows here


def enabled():
    return paths.params().GetBool(PARAM, True)


_LABEL_INDEX = [None, None]       # (document, {label: its first object}) while the tree is being rebuilt


def _label_index(doc):
    try:
        index = {}
        for o in doc.Objects:
            index.setdefault(o.Label, o)
        return index
    except Exception:
        return None


DRAWING_ANNOTATIONS = ("TechDraw::DrawViewDimension", "TechDraw::DrawViewDimExtent", "TechDraw::DrawViewBalloon",
                       "TechDraw::DrawLeaderLine", "TechDraw::DrawRichAnno", "TechDraw::DrawViewAnnotation",
                       "TechDraw::DrawWeldSymbol", "TechDraw::DrawTileWeld", "TechDraw::DrawHatch",
                       "TechDraw::DrawGeomHatch")


_DRAWING_SEEN = {}


def _drawing_doc(doc):
    """A drawing (sheets, no part bodies); kept per document until its object count changes."""
    try:
        objs = doc.Objects if doc is not None else []
        key = (doc.Name, len(objs)) if doc is not None else None
        if key is None:
            return False
        if _DRAWING_SEEN.get(doc.Name, (None,))[0] != key:
            types = {o.TypeId for o in objs}
            _DRAWING_SEEN[doc.Name] = (key, "TechDraw::DrawPage" in types and BODY not in types)
        return _DRAWING_SEEN[doc.Name][1]
    except Exception:
        return False


def _drawing_annotation(o):
    ""

    if o is None:
        return False
    try:
        if o.TypeId in DRAWING_ANNOTATIONS:
            return True
        return o.TypeId == "TechDraw::DrawViewSymbol" and bool(getattr(o, "SWAnnotation", "")) \
            and not getattr(o, "SWTable", "")
    except Exception:
        return False


def _object(doc, text):
    """The document object a row of FreeCAD's tree names (its label, without a sketch state)."""
    if doc is None or not text:
        return None
    index = _LABEL_INDEX[1] if _LABEL_INDEX[0] is doc else None
    for label in (text, sketchstatus.label_of(text)):
        if index is not None:       # a rebuild asks for every row: one pass over the labels, not a search for each
            found = index.get(label)
            if found is not None:
                return found
            continue
        try:
            found = doc.getObjectsByLabel(label)
        except Exception:
            found = []
        if found:
            return found[0]
    return None


SURFACE_FOLDER_TYPE = "SWStyle::SurfaceBodies"        # surfacebodies.py


def _is_folder(obj):
    """The Solid Bodies or the Surface Bodies folder."""
    return getattr(getattr(obj, "Proxy", None), "Type", None) in (FOLDER_TYPE, SURFACE_FOLDER_TYPE)


def _is_surface_folder(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == SURFACE_FOLDER_TYPE


TOP_FOLDERS = ("FreeWorksComments", "FreeWorksMarkups")     # comments.py, markup.py: under Annotations


def _is_top_folder(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) in TOP_FOLDERS


def _top_order(obj):
    return -2 + TOP_FOLDERS.index(getattr(obj.Proxy, "Type"))


def _tree_item_name(node):
    """The Hide/show tree items entry a row of the part belongs to, or None."""
    if node.src is None:
        if node.text in ("History", "Sensors", "Annotations"):
            return node.text
        return "Material" if node.text == NO_MATERIAL[0] else None
    o = node.obj
    if o is None:
        return None
    try:
        if _is_material(o):
            return "Material"
        if _is_equations(o):
            return "Equations"
        if o.TypeId == ORIGIN:
            return "Origin"
        if getattr(o, "Role", "") in PLANES:
            return "Default Planes"
        label = o.Label or ""
        if _is_folder(o):
            return "Surface Bodies" if _is_surface_folder(o) else "Solid Bodies"
        for name in ("Selection Sets", "Favorites", "Markups", "Tables", "Blocks", "Design Binder",
                     "Mate References", "Graphic Bodies"):
            if label.startswith(name):
                return name
        if label.startswith("MateReferences"):
            return "Mate References"        # the folder's own name in the tree (asmrefgeom.FOLDER)
    except Exception:
        return None
    return None


def _empty_row(node):
    """Automatic: a folder row with nothing in it is left out."""
    if node.src is None:
        return node.text in ("Sensors", "Annotations") and not node.children
    o = node.obj
    try:
        if o is not None and (o.isDerivedFrom("App::DocumentObjectGroup") or _is_folder(o)):
            return not node.children
    except Exception as _fw_err:
        _fw_log("fmtree.py:133", _fw_err)
    return False


def _is_cut_list(obj):
    ""
    return type(getattr(obj, "Proxy", None)).__name__ in ("CutListFolder", "SMCutListFolder")


def _is_lead(obj):
    ""

    if obj is None:
        return False
    if "SWWeldment" in obj.PropertiesList:
        return True
    if obj.TypeId == "App::DocumentObjectGroup" and obj.Name.startswith("SheetMetalFolder"):
        return True
    return False


def _is_material(obj):
    return obj.Name.startswith("Material") and not obj.TypeId.startswith(("PartDesign", "Sketcher", "Part::"))


# --------------------------------------------------------------------------- glyphs
def _glyph(draw):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(32, 32)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    draw(p)
    p.end()
    return QtGui.QIcon(pix)


def _history(p):
    p.setPen(QtGui.QPen(QtGui.QColor("#3c78b4"), 2.6))
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawEllipse(QtCore.QRectF(4, 4, 24, 24))
    p.drawLine(QtCore.QPointF(16, 16), QtCore.QPointF(16, 8))
    p.drawLine(QtCore.QPointF(16, 16), QtCore.QPointF(22, 19))


def _sensors(p):
    p.setPen(QtGui.QPen(QtGui.QColor("#2f8f4e"), 2.6))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QtCore.QRectF(12, 12, 8, 8))
    p.drawArc(QtCore.QRectF(6, 6, 20, 20), 30 * 16, 120 * 16)
    p.drawArc(QtCore.QRectF(6, 6, 20, 20), 210 * 16, 120 * 16)


def _annotations(p):
    p.setPen(QtGui.QPen(QtGui.QColor("#b8860b"), 2.6))
    p.setBrush(QtGui.QColor("#fff4cc"))
    p.drawRect(QtCore.QRectF(5, 6, 22, 20))
    font = QtGui.QFont()
    font.setBold(True)
    font.setPixelSize(16)
    p.setFont(font)
    p.drawText(QtCore.QRectF(5, 6, 22, 20), Qt.AlignCenter, "A")


def _material(p):
    p.setPen(QtGui.QPen(QtGui.QColor("#6b6b6b"), 2.2))
    gradient = QtGui.QLinearGradient(4, 4, 28, 28)
    gradient.setColorAt(0, QtGui.QColor("#f2f2f2"))
    gradient.setColorAt(1, QtGui.QColor("#9a9a9a"))
    p.setBrush(gradient)
    p.drawRect(QtCore.QRectF(5, 9, 22, 16))
    p.drawLine(QtCore.QPointF(9, 13), QtCore.QPointF(14, 13))


VIRTUAL = (("History", _history, "The part's latest features, newest first"),
           ("Sensors", _sensors, "Sensors watch a value of the part (right-click: Add Sensor)"),
           ("Annotations", _annotations, "The part's 3D annotations (none yet)"))


def _review(doc):
    """An assembly in Large Design Review (its saved graphics): an assembly's tree, no Material row."""
    try:
        from . import asmreview
        return asmreview.is_review(doc)
    except Exception:
        return False


NO_MATERIAL = ("Material <not specified>", _material, "No material given to the part yet")


def _is_sensor(obj):
    try:
        return obj is not None and type(getattr(obj, "Proxy", None)).__name__ == "Sensor" and "Alerting" in obj.PropertiesList
    except Exception:
        return False


def _is_annotation_folder(obj):
    ""
    try:
        return obj is not None and obj.TypeId == "App::DocumentObjectGroup" and obj.Label == "Annotations" \
            and not treefolders.is_folder(obj)
    except Exception:
        return False


def _is_equations(obj):
    try:
        from . import equations
        return equations.is_sheet(obj)
    except Exception:
        return False


DEPENDENT_GREY = "#8c8c8c"
_marked = {}


def _failed(obj):
    ""
    try:
        return obj is not None and "Invalid" in obj.State
    except Exception:
        return False


def _any_failed(doc):
    ""

    if doc is None:
        return False
    from . import tickcache
    try:
        return tickcache.get(("any_failed", doc.Name, len(doc.Objects)), lambda: _any_failed_now(doc))
    except Exception:
        return False


def _any_failed_now(doc):
    try:
        return any("Invalid" in o.State for o in doc.Objects)
    except Exception:
        return False


def _warned(obj):
    ""
    try:
        return obj is not None and obj.TypeId == "Sketcher::SketchObject" and "Invalid" not in obj.State \
            and bool(obj.RedundantConstraints)
    except Exception:
        return False


def _any_warned(doc):
    if doc is None:
        return False
    from . import tickcache
    try:
        return tickcache.get(("any_warned", doc.Name, len(doc.Objects)),
                             lambda: any(_warned(o) for o in doc.Objects))
    except Exception:
        return False


def _suppressed(obj):
    ""
    try:
        return obj is not None and bool(getattr(obj, "Suppressed", False))
    except Exception:
        return False


_greyed = {}


def _greyed_icon(icon, size=16):
    key = (icon.cacheKey(), size)
    done = _greyed.get(key)
    if done is None:
        if len(_greyed) > 300:
            _greyed.clear()
        im = icon.pixmap(size, size).toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
        for y in range(im.height()):
            for x in range(im.width()):
                c = QtGui.QColor.fromRgba(im.pixel(x, y))
                if c.alpha():
                    g = int(0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue())
                    g = (g + 2 * 150) // 3
                    im.setPixelColor(x, y, QtGui.QColor(g, g, g, c.alpha()))
        done = QtGui.QIcon(QtGui.QPixmap.fromImage(im))
        _greyed[key] = done
    return done


def _held_back(obj):
    ""



    try:
        if obj is None or "Invalid" in obj.State or not _any_failed(obj.Document):
            return False
        if "Touched" not in obj.State:
            return False
        from . import tickcache
        return tickcache.get(("held_back", obj.Document.Name, obj.Name),
                             lambda: any(_failed(o) for o in obj.OutListRecursive))
    except Exception:
        return False


def _mark(node, depth=0):
    ""

    if node is None or depth > 12:
        return None
    if not node.link:
        if _failed(node.obj):
            return "error"
    worst = "warning" if (not node.link and _warned(node.obj)) else None
    if node.link:
        return worst
    for child in node.children:
        below = _mark(child, depth + 1)
        if below == "error":
            return "error"
        worst = worst or below
    return worst


def _error_tip(node):
    """The tooltip of a row with an error or a warning (its own, else the first one under it)."""
    try:
        from . import rebuilderrors
    except Exception:
        return ""
    if node is None or node.obj is None:
        return ""
    tip = rebuilderrors.tooltip(node.obj)
    if tip or node.link:
        return tip
    for child in node.children:
        below = _error_tip(child)
        if below:
            return "%s: %s" % (child.obj.Label, below) if child.obj is not None else below
    return ""


def _with_error_mark(icon, size=16, warning=False):
    ""
    key = (icon.cacheKey(), warning)
    if key not in _marked:
        from .whatswrong import error_icon, warning_icon
        mark_icon = warning_icon if warning else error_icon
        pm = icon.pixmap(size, size)
        out = QtGui.QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.drawPixmap(0, 0, pm)
        mark = size * 0.6
        p.drawPixmap(QtCore.QRectF(0, size - mark, mark, mark).toRect(), mark_icon(int(mark)).pixmap(int(mark), int(mark)))
        p.end()
        if len(_marked) > 200:
            _marked.clear()
        _marked[key] = QtGui.QIcon(out)
    return _marked[key]


# --------------------------------------------------------------- Tree Display (fmmenu.TREE_DISPLAY)
_display = {"at": 0.0, "value": None}


def display():
    """Tree Display's ticks and FeatureManager > Show translated feature names (read every 0.5 s)."""
    import time
    now = time.monotonic()
    if _display["value"] is None or now - _display["at"] > 0.5:
        p = paths.params()
        try:
            from . import optionspages
            english = bool(optionspages.stored("FeatureManager", "Show translated feature names in FeatureManager tree",
                                               False))
        except Exception:
            english = False
        _display["value"] = {"names": p.GetBool("TreeShowNames", True),
                             "descriptions": p.GetBool("TreeShowDescriptions", False),
                             "components": p.GetBool("TreeComponentDescriptions", False),
                             "comment": p.GetBool("TreeCommentIndicator", True), "english": english}
        _display["at"] = now
    return _display["value"]


def display_text(obj, text):
    """A row's text as Tree Display says: the name, the description, or both; components with
    their description (Component Name and Description); the feature's own FreeCAD name after it
    when Show translated feature names is on."""
    d = display()
    try:
        desc = (obj.Label2 or "").strip()
    except Exception:
        desc = ""
    text = "" if text is None else str(text)
    component = obj.TypeId in ("App::Link", "App::LinkElement") or "AssemblyLink" in obj.TypeId
    if component and d["components"]:
        desc = component_description(obj) or desc
    if desc and (d["descriptions"] or (component and d["components"])):
        text = desc if not d["names"] and not component else "%s (%s)" % (text, desc)
    if d["english"] and obj.Name and obj.Name != obj.Label:
        text = "%s <%s>" % (text, obj.Name)
    return text


def component_description(obj):
    """Options > General > Custom property used as component description: that custom property of
    the component's own document."""
    try:
        from . import optionspages, customprops
        name = optionspages.stored("General", "Custom property used as component description", "Description")
        linked = obj.getLinkedObject(True)
        doc = linked.Document if linked is not None else None
        for n, _kind, value in customprops.read(doc):
            if n == name:
                return str(value)
    except Exception as _fw_err:
        _fw_log("fmtree.py:418", _fw_err)
    return ""


PATTERNS = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::MultiTransform",
            "PartDesign::Mirrored")


def pattern_tip(obj):
    """Options > Display > Display pattern information tooltips: a pattern row's instances and spacing."""
    if obj.TypeId not in PATTERNS:
        return ""
    try:
        from . import optionspages
        if not optionspages.stored("Display", "Display pattern information tooltips", True):
            return ""
    except Exception as _fw_err:
        _fw_log("fmtree.py:435", _fw_err)
    try:
        if obj.TypeId == "PartDesign::LinearPattern":
            n = int(obj.Occurrences)
            mode = str(getattr(obj, "Mode", "Extent"))
            if mode == "Spacing" and hasattr(obj, "Offset"):
                gap = obj.Offset.Value
            else:
                gap = obj.Length.Value / max(n - 1, 1)
            return "%s\nInstances: %d\nSpacing: %.4g mm" % (obj.Label, n, gap)
        if obj.TypeId == "PartDesign::PolarPattern":
            n = int(obj.Occurrences)
            return "%s\nInstances: %d\nAngle: %.4g deg" % (obj.Label, n, obj.Angle.Value)
        if obj.TypeId == "PartDesign::Mirrored":
            return "%s\nInstances: 2" % obj.Label
        return "%s\nPatterns: %d" % (obj.Label, len(getattr(obj, "Transformations", []) or []))
    except Exception:
        return ""


def _has_comment(obj):
    try:
        return bool((getattr(obj, "Comment", "") or "").strip())
    except Exception:
        return False


_commented = {}


COMMENT_STATUSES = ("Description", "High Priority", "Low Priority", "Complete", "Reminder")
COMMENT_DEFAULTS = {"Description": "#FFFFC0", "High Priority": "#FFC0CB", "Low Priority": "#D3D3D3",
                    "Complete": "#C0FFC0", "Reminder": "#C0E0FF"}


def comment_color(obj):
    """The comment's status colour (Document Properties > Model Display > Comment background colors),
    or None for a plain comment."""
    status = str(getattr(obj, "CommentStatus", "") or "")
    if status not in COMMENT_DEFAULTS:
        return None
    try:
        from . import optionspages
        return str(optionspages.doc_value(obj.Document, "Model Display", status, COMMENT_DEFAULTS[status]))
    except Exception:
        return COMMENT_DEFAULTS[status]


def _with_comment_mark(icon, size=16, color=None):
    """Show Comment Indicator: a small yellow note at the icon's top right (its status colour once
    the comment has one)."""
    key = (icon.cacheKey(), color)
    if key not in _commented:
        pm = icon.pixmap(size, size)
        out = QtGui.QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.drawPixmap(0, 0, pm)
        w = size * 0.45
        r = QtCore.QRectF(size - w, 0, w, w * 0.8)
        p.setPen(QtGui.QPen(QtGui.QColor("#7a5c00"), 1))
        p.setBrush(QtGui.QColor(color or "#ffd84d"))
        p.drawRect(r)
        p.drawLine(QtCore.QPointF(r.left() + 1.5, r.top() + r.height() * 0.4),
                   QtCore.QPointF(r.right() - 1.5, r.top() + r.height() * 0.4))
        p.end()
        if len(_commented) > 200:
            _commented.clear()
        _commented[key] = QtGui.QIcon(out)
    return _commented[key]


_lifted_icons = {}


def _opaque(pixmap):
    ""


    image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
    top = 0
    for y in range(image.height()):
        for x in range(image.width()):
            top = max(top, image.pixelColor(x, y).alpha())
    if top == 0:
        return pixmap
    scale = 255.0 / top if top < 200 else 1.0
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if not c.alpha():
                continue
            c.setAlpha(min(255, int(round(c.alpha() * scale))))
            h, sat, light, a = c.getHslF()
            if sat < 0.30 and light < 0.62:
                # grey ink still near the pane's own grey (FreeCAD's faded copy): light grey
                c = QtGui.QColor.fromHslF(max(h, 0.0), sat, 0.62 + 0.3 * light, a)
            image.setPixelColor(x, y, c)
    out = QtGui.QPixmap.fromImage(image)
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    return out


def _dark_icon(icon, size=16):
    """Dark and AMOLED: the row's icon with its dark grey ink lifted (style.readable_pixmap), as the
    CommandManager's are. FreeCAD's tree hands its own icons over unchanged, so dark outlines (the
    default planes' parallelograms, #555052 at a third of full opacity on the #494949 pane) all but
    vanished. Light: as it is."""
    try:
        from . import style
        if not style.dark() or icon is None or icon.isNull():
            return icon
        key = (icon.cacheKey(), size, style.current_theme())
        done = _lifted_icons.get(key)
        if done is None:
            if len(_lifted_icons) > 500:
                _lifted_icons.clear()
            dpr = 1.0
            try:
                dpr = QtWidgets.QApplication.instance().devicePixelRatio()
            except Exception as _fw_err:
                _fw_log("fmtree.py:dpr", _fw_err)
            pm = style.readable_pixmap(icon, size, dpr=dpr)
            done = _lifted_icons[key] = QtGui.QIcon(_opaque(pm))
        return done
    except Exception as _fw_err:
        _fw_log("fmtree.py:dark-icon", _fw_err)
        return icon


def _folder_back(obj):
    try:
        if obj is None or not treefolders.is_folder(obj):
            return False
        from . import rollbackbar, tickcache
        return tickcache.get(("folder back", obj.Document.Name, obj.Name), lambda: rollbackbar.folder_back(obj))
    except Exception as _fw_err:
        _fw_log("fmtree.py:folder-back", _fw_err)
        return False


_grey_icons = {}


def _grey_icon(icon, size=16):
    """The icon as Qt greys a disabled row's."""
    key = (icon.cacheKey(), size)
    done = _grey_icons.get(key)
    if done is None:
        if len(_grey_icons) > 200:
            _grey_icons.clear()
        out = QtGui.QIcon()
        for side in (size, size * 2):
            out.addPixmap(icon.pixmap(side, side, QtGui.QIcon.Disabled), QtGui.QIcon.Normal)
        done = _grey_icons[key] = out
    return done


_shared_icons = {}


def _shared_sketch(obj):
    ""
    try:
        if obj is None or obj.TypeId != "Sketcher::SketchObject":
            return False
        from . import confirmdelete
        users = confirmdelete._feature_users(obj)
        return len([f for f in users if f.TypeId != "Sketcher::SketchObject"]) > 1
    except Exception:
        return False


def _with_shared_mark(icon, size=16):
    ""
    key = icon.cacheKey()
    if key not in _shared_icons:
        pm = icon.pixmap(size, size)
        out = QtGui.QPixmap(pm.size())
        out.setDevicePixelRatio(pm.devicePixelRatio())
        out.fill(Qt.transparent)
        p = QtGui.QPainter(out)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.drawPixmap(0, 0, pm)
        p.setPen(QtGui.QPen(QtGui.QColor("#5a3a10"), 0.8))
        p.setBrush(QtGui.QColor("#f2c48d"))
        # the palm, then four fingers and a thumb
        p.drawRoundedRect(QtCore.QRectF(0.5, size * 0.66, size * 0.42, size * 0.3), 1.5, 1.5)
        for i in range(4):
            x = 0.9 + i * size * 0.095
            p.drawRoundedRect(QtCore.QRectF(x, size * 0.5, size * 0.08, size * 0.2), 0.8, 0.8)
        p.drawRoundedRect(QtCore.QRectF(size * 0.4, size * 0.7, size * 0.16, size * 0.08), 0.8, 0.8)
        p.end()
        if len(_shared_icons) > 100:
            _shared_icons.clear()
        _shared_icons[key] = QtGui.QIcon(out)
    return _shared_icons[key]


def _tree_hover(obj):
    """Hidden planes and sketches outlined in the view while their row is hovered (treehover)."""
    try:
        from . import treehover
        treehover.hover(obj)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree hover: %s\n" % error)


# --------------------------------------------------------------------------- the model
def _unfilled_component(node):
    obj = getattr(node, "obj", None)
    if obj is None or node.link or node.children or node.src is None:
        return False
    try:
        return obj.TypeId in ("App::Link", "App::LinkElement") or "AssemblyLink" in obj.TypeId
    except Exception:
        return False


_ROW = {}


def _row_size(text):
    ""

    key = "metrics"
    if key not in _ROW:
        try:
            spacing = App.ParamGet("User parameter:BaseApp/Preferences/TreeView").GetInt("ItemSpacing", 0)
        except Exception:
            spacing = 0
        fm = QtGui.QFontMetrics(QtWidgets.QApplication.font())
        _ROW[key] = (fm, max(16, fm.height()) + max(0, spacing))
        QtCore.QTimer.singleShot(2000, lambda: _ROW.pop(key, None))     # Options may change it
    fm, height = _ROW[key]
    return QtCore.QSize(16 + 6 + fm.horizontalAdvance(str(text or "")) + 8, height)


class Node:
    __slots__ = ("src", "parent", "children", "row", "text", "icon", "tip", "obj", "link", "number", "__weakref__")

    def __init__(self, parent=None, src=None, text=None, icon=None, tip=None, obj=None, link=False):
        self.parent, self.src, self.text, self.icon, self.tip = parent, src, text, icon, tip
        self.obj, self.link = obj, link
        self.children = []
        self.row = 0
        self.number = 0

    def add(self, child):
        child.parent = self
        child.row = len(self.children)
        self.children.append(child)
        return child

    def key(self):
        """Labels from the part down: what stays open across rebuilds."""
        parts, node = [], self
        while node is not None and node.parent is not None:
            parts.append((node.text or "") if node.src is None else
                         ("link:" if node.link else "") + sketchstatus.label_of(str(node.src.data(Qt.DisplayRole) or "")))
            node = node.parent
        return tuple(reversed(parts))



# Display, Decoration, ToolTip and Foreground): a layer that starts handling one takes it out of here.
_PLAIN_ROLES = frozenset(int(r) if not hasattr(r, "value") else r.value for r in (
    Qt.FontRole, Qt.TextAlignmentRole, Qt.BackgroundRole, Qt.CheckStateRole, Qt.SizeHintRole,
    Qt.StatusTipRole, Qt.WhatsThisRole, Qt.AccessibleTextRole, Qt.AccessibleDescriptionRole))
_BASE_DATA = [None]      # Model.data as the class defines it, before anyone wraps it


def _guard_model(cls):
    """data(), flags() and the other model calls never raise (after a document closes too): an exception out of them takes FreeCAD down (PySide 6.8
    crashes reporting it). Others patch Model.data (the assembly tree), so the guard goes round
    whatever is there when a tree is made."""
    for name, empty in (("data", None), ("flags", Qt.NoItemFlags), ("rowCount", 0), ("columnCount", 1),
                        ("index", QtCore.QModelIndex()), ("parent", QtCore.QModelIndex()),
                        ("hasChildren", False), ("mimeData", None), ("canDropMimeData", False),
                        ("dropMimeData", False), ("setData", False)):
        fn = getattr(cls, name, None)
        if fn is None:
            continue
        if getattr(fn, "_fw_guard", False):
            continue

        if name == "data":
            def guarded(self, index, role=Qt.DisplayRole, _fn=fn):
                try:
                    if (role if type(role) is int else getattr(role, "value", role)) in _PLAIN_ROLES:
                        # roles no layer over Model.data changes (they all look at the text, icon,
                        # tooltip or colour): straight to the row's own value, past the wrapper chain
                        # (Qt asks every row for these on every paint)
                        return _BASE_DATA[0](self, index, role)
                    return _fn(self, index, role)
                except Exception:
                    return None
        else:
            def guarded(self, *args, _fn=fn, _empty=empty):
                try:
                    return _fn(self, *args)
                except Exception:
                    return QtCore.QModelIndex() if isinstance(_empty, QtCore.QModelIndex) else _empty
        guarded._fw_guard = True
        setattr(cls, name, guarded)


class Model(QtCore.QAbstractItemModel):
    rebuilt = QtCore.Signal()

    def __init__(self, tree, parent=None):
        super().__init__(parent)
        _guard_model(type(self))
        self.tree = tree
        self.src = tree.model()
        self.root = Node()
        # Rows carry a number, not the node itself: Qt keeps indexes (selection, current row,
        # hover) past a rebuild, and a node pointer in one of them would point at a freed node
        # (an access violation in shiboken). A stale number finds nothing.
        self.ids = {}             # row number -> node, for this build
        self.serial = 0
        self.by_id = {}           # FreeCAD row (internal id) -> [nodes]
        self.part = None          # the part's node
        self.flat = None          # the body whose rows sit under the part, else None
        self.doc = None
        self.icons = {name: _glyph(draw) for name, draw, _tip in VIRTUAL + (NO_MATERIAL,)}
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(SOON)
        self.timer.timeout.connect(self.rebuild)
        self.src.rowsInserted.connect(self.soon)
        self.src.rowsRemoved.connect(self.soon)
        self.src.rowsMoved.connect(self.soon)
        self.src.layoutChanged.connect(self.soon)
        self.src.modelReset.connect(self.soon)
        self.src.dataChanged.connect(self._data)
        self.rebuild()

    def disconnect_source(self):
        for signal, slot in ((self.src.rowsInserted, self.soon), (self.src.rowsRemoved, self.soon),
                             (self.src.rowsMoved, self.soon), (self.src.layoutChanged, self.soon),
                             (self.src.modelReset, self.soon), (self.src.dataChanged, self._data)):
            try:
                signal.disconnect(slot)
            except Exception as _fw_err:
                _fw_log("fmtree.py:695", _fw_err)
        self.timer.stop()

    def soon(self, *args):
        self.timer.start()

    # ------------------------------------------------------------------ building
    def rebuild(self):
        self.timer.stop()
        self.beginResetModel()
        self.ids = {}
        try:
            _doc = App.ActiveDocument
            _LABEL_INDEX[:] = [_doc, _label_index(_doc) if _doc is not None else None]
        except Exception:
            _LABEL_INDEX[:] = [None, None]
        try:
            self._build()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: feature tree: %s\n" % error)
            self.root, self.by_id, self.part, self.flat = Node(), {}, None, None
            self.ids = {}
        finally:
            _LABEL_INDEX[:] = [None, None]
        self.endResetModel()
        self.rebuilt.emit()

    def _mirror(self, parent, index, doc, link=False, deep=True):
        node = parent.add(Node(src=QtCore.QPersistentModelIndex(index), link=link,
                               obj=_object(doc, index.data(Qt.DisplayRole))))
        self.by_id.setdefault(index.internalId(), []).append(node)
        if deep and not link:
            for child in self._children(index):
                self._mirror(node, child, doc)
            try:
                from . import sketchblocktree
                sketchblocktree.add_rows(self, node, Node)
            except Exception as _fw_err:
                _fw_log("fmtree.py:726", _fw_err)
        return node

    def _bodies_to_items(self, cut_node, solid, doc):
        """Each cut list item row gets its bodies' rows (from the Solid Bodies folder) when FreeCAD shows none."""
        rows = {}
        for i, _o in solid:
            for child in self._children(i):
                o = _object(doc, child.data(Qt.DisplayRole))
                if o is not None:     # a Solid Bodies row names its FreeCAD Body in Body (multibody.py)
                    key = getattr(o, "Body", None)
                    rows.setdefault(key if isinstance(key, str) and key else o.Name, []).append(child)
        for item in cut_node.children:
            o = item.obj
            if o is None or item.children:
                continue
            body = getattr(o, "Body", None)
            wanted = list(getattr(o, "Bodies", []) or []) or ([body] if body is not None else [])
            for b in wanted:
                for child in rows.get(getattr(b, "Name", ""), []):
                    self._mirror(item, child, doc)

    def _children(self, index):
        ""


        out = []
        drawing = _drawing_doc(self.doc or App.ActiveDocument)
        for row in range(self.src.rowCount(index)):
            child = self.src.index(row, 0, index)
            if not self.tree.isRowHidden(row, index):
                if drawing and _drawing_annotation(_object(self.doc or App.ActiveDocument,
                                                           child.data(Qt.DisplayRole))):
                    continue
                out.append(child)
                continue
            try:
                o = _object(self.doc or App.ActiveDocument, child.data(Qt.DisplayRole))
                from . import contours
                if o is not None and contours.is_helper(o):
                    out += self._children(child)
            except Exception as _fw_err:
                _fw_log("fmtree.py:764", _fw_err)
        return out

    def _shared_sketches(self, top):
        ""

        try:
            from . import contours
        except Exception:
            return
        sketch_nodes = {}
        self.shared = set()

        def walk(node):
            for c in node.children:
                if c.obj is not None and c.obj.TypeId == "Sketcher::SketchObject" and c.src is not None \
                        and not c.link:
                    sketch_nodes.setdefault(c.obj.Name, c)
                    if _shared_sketch(c.obj):
                        self.shared.add(c.obj.Name)
                walk(c)
        walk(top)

        def add(node):
            for c in list(node.children):
                o = c.obj
                if o is not None and not c.link and o.TypeId in contours.TYPES:
                    try:
                        sk = contours.sketch_of(o)
                    except Exception:
                        sk = None
                    have = sk is not None and any(x.obj is sk for x in c.children)
                    seen = sketch_nodes.get(sk.Name) if sk is not None else None
                    if sk is not None and not have and seen is not None and seen.src is not None:
                        row = Node(src=seen.src, obj=sk, link=True)
                        c.children.insert(0, row)
                        row.parent = c
                        for i, x in enumerate(c.children):
                            x.row = i
                        self.by_id.setdefault(QtCore.QModelIndex(seen.src).internalId(), []).append(row)
                add(c)
        add(top)

    def _doc_row(self, doc):
        """FreeCAD's tree row of the active document. A drawing named after its model (Draw1 becomes Bracket)
        shares the part's label, so among rows with the same label take the one whose rows are this
        document's objects, not the first one (the part's tree showed in the drawing's window)."""
        same = [i for i in self._children(QtCore.QModelIndex()) if i.data(Qt.DisplayRole) == doc.Label]
        if len(same) < 2:
            return same[0] if same else None
        names = {o.Name for o in doc.Objects}

        def mine(i):
            hits = 0
            for c in self._children(i):
                o = _object(doc, c.data(Qt.DisplayRole))
                if o is None or o.Name not in names or o.Document is not doc:
                    return -1
                hits += 1
            return hits
        scored = [(mine(i), n) for n, i in enumerate(same)]
        best = max(scored, key=lambda t: (t[0], -t[1]))
        if best[0] < 0:
            twins = [d for d in App.listDocuments().values() if d.Label == doc.Label]
            at = twins.index(doc) if doc in twins else 0
            return same[min(at, len(same) - 1)]
        return same[best[1]]

    def _build(self):
        self.root, self.by_id, self.part, self.flat = Node(), {}, None, None
        self.ids = {}
        doc = self.doc = App.ActiveDocument
        if doc is None:
            return
        part_index = self._doc_row(doc)
        if part_index is None:
            return
        part = self.part = self.root.add(Node(src=QtCore.QPersistentModelIndex(part_index), obj=None))
        self.by_id.setdefault(part_index.internalId(), []).append(part)
        rows = [(i, _object(doc, i.data(Qt.DisplayRole))) for i in self._children(part_index)]
        bodies = [(i, o) for i, o in rows if o is not None and o.TypeId == BODY]
        flat = bodies[0] if len(bodies) == 1 else None
        self.flat = flat[1] if flat else None

        drawing = not bodies and any(o is not None and o.TypeId == "TechDraw::DrawPage" for _i, o in rows)
        history = Node(text="History", icon=self.icons["History"], tip=VIRTUAL[0][2])
        if not drawing:
            part.add(history)
        folders = {}
        for name, _draw, tip in VIRTUAL[1:]:
            node = Node(text=name, icon=self.icons[name], tip=tip)
            if not drawing:          # a drawing has its own Annotations row: no virtual folders
                part.add(node)
            folders[name] = node

        inside = set()
        for i, o in rows:
            if _is_sensor(o):
                self._mirror(folders["Sensors"], i, doc)
                inside.add(o.Name)
            elif _is_annotation_folder(o):
                for child in self._children(i):
                    self._mirror(folders["Annotations"], child, doc)
                inside.add(o.Name)
        if inside:
            rows = [(i, o) for i, o in rows if o is None or o.Name not in inside]
        for name, node in folders.items():
            n = len(node.children)
            node.tip = ("%d %s" % (n, "sensor(s)" if name == "Sensors" else "annotation(s)")) if n else \
                dict((v[0], v[2]) for v in VIRTUAL)[name]

        firsts = [(i, o) for i, o in rows if o is not None and (_is_folder(o) or _is_material(o) or _is_equations(o)
                                                                or _is_top_folder(o) or _is_cut_list(o))]
        firsts.sort(key=lambda r: _top_order(r[1]) if _is_top_folder(r[1]) else
                    -0.75 if _is_surface_folder(r[1]) else -0.5 if _is_cut_list(r[1]) else
                    0 if _is_folder(r[1]) else 1 if _is_equations(r[1]) else 2)

        # item): the Solid Bodies folder row is left out and its body rows go under the items instead
        cut = [(i, o) for i, o in firsts if _is_cut_list(o)]
        solid = [(i, o) for i, o in firsts if _is_folder(o) and not _is_surface_folder(o)]
        skipped = solid if cut else []
        if skipped:
            firsts = [r for r in firsts if r not in solid]
        for i, o in firsts:
            node = self._mirror(part, i, doc)
            if (i, o) in cut and solid:
                self._bodies_to_items(node, solid, doc)
        if not drawing and not _review(doc) and not any(_is_material(o) for i, o in firsts):
            name, _draw, tip = NO_MATERIAL
            part.add(Node(text=name, icon=self.icons[name], tip=tip))
        features = []
        leads = [(i, o) for i, o in rows if flat is not None and _is_lead(o)]
        if flat is not None:
            features = self._lay_out_body(part, flat[0], flat[1], doc, leads)
        folder_rows = {o.Name: i for i, o in rows if treefolders.is_folder(o)}
        body_nodes = []
        for i, o in rows:
            if (i, o) in firsts or (i, o) in skipped or (flat is not None and o is flat[1]) or (o is not None and o.Name in folder_rows) \
                    or (i, o) in leads:
                continue
            node = self._mirror(part, i, doc)
            if o is not None and o.TypeId == BODY:
                features += [c for c in node.children]
                body_nodes.append(node)

        placed = set()
        if folder_rows:
            def folder_node(folder):
                node = Node(src=QtCore.QPersistentModelIndex(folder_rows[folder.Name]), obj=folder)
                self.by_id.setdefault(folder_rows[folder.Name].internalId(), []).append(node)
                return node
            for parent in ([part] if flat is not None else []) + body_nodes:
                placed.update(f.Name for f in treefolders.regroup(parent, folder_node) if f is not None)
            for name, i in folder_rows.items():
                if name not in placed:
                    self._mirror(part, i, doc, deep=False)
        # History: the latest solid features, newest first
        solids = []
        for node in features:
            o = node.obj
            if o is not None and o.isDerivedFrom("PartDesign::Feature") and o.TypeId != BODY:
                solids.append(node)
        for node in list(reversed(solids))[:HISTORY_SIZE]:
            index = QtCore.QModelIndex(node.src)
            if index.isValid():
                self._mirror(history, index, doc, link=True)
        self._tree_items(part)
        self._flat_folder(part)
        self._shared_sketches(part)

    def _flat_folder(self, part):
        ""
        try:
            from . import smflatten
            flats = [n for n in part.children if n.obj is not None and smflatten.is_flat_pattern(n.obj)]
        except Exception:
            return
        if not flats:
            return
        box = Node(text="Flat-Pattern", icon=QtGui.QIcon(":/icons/folder.svg"),
                   tip="The part's flat pattern")
        at = part.children.index(flats[0])
        rest = [n for n in part.children if n not in flats]
        part.children = []
        for n in rest[:at] + [box] + rest[at:]:
            part.add(n)
        for n in flats:
            box.add(n)

    def _tree_items(self, part):
        """Options > FeatureManager > Hide/show tree items (and the tree's Hide/Show Tree Items box):
        Show keeps a row, Hide takes it out, Automatic shows it only when it holds something."""
        try:
            from . import fmmenu
            defaults = dict(fmmenu.TREE_ITEMS)
        except Exception:
            return
        keep = []
        for node in part.children:
            name = _tree_item_name(node)
            state = paths.params().GetString("TreeItem." + name, defaults.get(name, "Automatic")) if name else "Show"
            if state == "Hide" or (state == "Automatic" and _empty_row(node)):
                self._forget(node)
                continue
            keep.append(node)
        if len(keep) != len(part.children):
            part.children = []
            for node in keep:
                part.add(node)

    def _forget(self, node):
        for child in node.children:
            self._forget(child)
        if node.src is not None:
            nodes = self.by_id.get(node.src.internalId())
            if nodes and node in nodes:
                nodes.remove(node)

    def _lay_out_body(self, part, body_index, body, doc, leads=()):
        """The body's rows under the part: the planes out of Origin, then Origin, then the leads
        (Sheet-Metal, Weldment), then the features. Returns the feature nodes."""
        origin = getattr(body, "Origin", None)
        roles = {}
        for feature in getattr(origin, "OriginFeatures", None) or []:
            roles[feature.Name] = getattr(feature, "Role", "")
        features = []
        for index in self._children(body_index):
            obj = _object(doc, index.data(Qt.DisplayRole))
            if obj is not None and obj.TypeId == ORIGIN:
                kids = [(i, _object(doc, i.data(Qt.DisplayRole))) for i in self._children(index)]
                planes = {roles.get(o.Name): i for i, o in kids if o is not None and roles.get(o.Name) in PLANES}
                for role in PLANES:
                    if role in planes:
                        self._mirror(part, planes[role], doc)

                # above, the origin point is the row itself, and the axes stay pickable in the view
                self._mirror(part, index, doc, deep=False)
                for i, _o in leads:
                    self._mirror(part, i, doc)
                leads = ()
            elif self._flat_view():
                # Show Flat Tree View: the sketches and other rows a feature holds sit before it, at its level
                for child in self._children(index):
                    self._mirror(part, child, doc)
                features.append(self._mirror(part, index, doc, deep=False))
            else:
                features.append(self._mirror(part, index, doc))
        for i, _o in leads:             # a body without Origin: they still show
            self._mirror(part, i, doc)
        return features

    @staticmethod
    def _flat_view():
        try:
            return paths.params().GetBool("TreeFlat", False)
        except Exception:
            return False

    # ------------------------------------------------------------------ the model's interface
    def _number(self, node):
        self.serial += 1
        self.ids[self.serial] = node
        return self.serial

    def _create(self, row, node):
        number = getattr(node, "number", 0)
        if not number or self.ids.get(number) is not node:
            number = node.number = self._number(node)
        return self.createIndex(row, 0, number)

    def node(self, index):
        """The node behind a row here; the root for no row, None for a row of an earlier build."""
        if not index.isValid():
            return self.root
        if index.model() is not self:
            return None
        return self.ids.get(index.internalId())

    def source(self, index):
        """FreeCAD's row behind a row here, else an invalid index."""
        node = self.node(index) if index.isValid() else None
        if node is None or node.src is None:
            return QtCore.QModelIndex()
        return QtCore.QModelIndex(node.src)

    def index_of(self, node):
        if node is None or node.parent is None:
            return QtCore.QModelIndex()
        return self._create(node.row, node)

    def index(self, row, column, parent=QtCore.QModelIndex()):
        node = self.node(parent)
        if node is None or column != 0 or row < 0 or row >= len(node.children):
            return QtCore.QModelIndex()
        return self._create(row, node.children[row])

    def parent(self, index=QtCore.QModelIndex()):
        if not index.isValid():
            return QtCore.QModelIndex()
        node = self.node(index)
        return self.index_of(node.parent) if node is not None else QtCore.QModelIndex()

    def hasChildren(self, parent=QtCore.QModelIndex()):
        ""

        if parent.isValid() and parent.column() != 0:
            return False
        node = self.node(parent)
        if node is None:
            return False
        return bool(node.children) or _unfilled_component(node)

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self.node(parent)
        return len(node.children) if node is not None else 0

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 1

    def data(self, index, role=Qt.DisplayRole):
        node = self.node(index) if index.isValid() else None
        if node is None:
            return None
        if role == Qt.SizeHintRole:
            return _row_size(self.data(index, Qt.DisplayRole))
        if node.src is not None:
            src = QtCore.QModelIndex(node.src)
            value = src.data(role) if src.isValid() else None
            if node.obj is not None and getattr(node.obj, "SWAnnotationsFolder", False):

                if role == Qt.DecorationRole:
                    return self.icons["Annotations"]
                if role == Qt.ForegroundRole:
                    return None
            if role == Qt.DisplayRole and node.obj is not None and node is not self.part:
                return display_text(node.obj, value)
            if role == Qt.ToolTipRole and node.obj is not None and node is not self.part:
                tip = _error_tip(node) or pattern_tip(node.obj)
                if tip:
                    return tip
            if role == Qt.DecorationRole and isinstance(value, QtGui.QPixmap):
                value = QtGui.QIcon(value)
            if role in (Qt.DecorationRole, Qt.ForegroundRole) and _folder_back(node.obj):

                if role == Qt.ForegroundRole:
                    return QtGui.QBrush(QtWidgets.QApplication.palette().color(QtGui.QPalette.Disabled,
                                                                             QtGui.QPalette.Text))
                if isinstance(value, QtGui.QPixmap):
                    value = QtGui.QIcon(value)
                if isinstance(value, QtGui.QIcon):
                    return _grey_icon(_dark_icon(value))
            if role == Qt.DecorationRole and isinstance(value, QtGui.QIcon):
                part = node is self.part
                value = _dark_icon(value)
                if not part and not node.link and _suppressed(node.obj):
                    value = _greyed_icon(value)
                mark = _mark(node) if not part else \
                    ("error" if _any_failed(self.doc) else "warning" if _any_warned(self.doc) else None)
                if mark == "error":
                    return _with_error_mark(value)
                if mark == "warning":
                    return _with_error_mark(value, warning=True)
                if not part and display()["comment"] and _has_comment(node.obj):
                    return _with_comment_mark(value, color=comment_color(node.obj))
                if not part and node.obj is not None and node.obj.Name in getattr(self, "shared", ()):
                    return _with_shared_mark(value)
                return value
            if role == Qt.ForegroundRole and (_held_back(node.obj) or (not node.link and _suppressed(node.obj))):
                return QtGui.QBrush(QtGui.QColor(DEPENDENT_GREY))
            if role == Qt.FontRole and isinstance(value, QtGui.QFont) and value.strikeOut() and _suppressed(node.obj):
                value = QtGui.QFont(value)
                value.setStrikeOut(False)
            return value
        if role == Qt.DisplayRole:
            return node.text
        if role == Qt.DecorationRole:
            return node.icon
        if role == Qt.ToolTipRole:
            return node.tip
        return None

    def setData(self, index, value, role=Qt.EditRole):
        src = self.source(index)
        if not src.isValid():
            return False
        return self.src.setData(src, value, role)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsDropEnabled           # empty space: out of a folder
        node = self.node(index)
        if node is None:
            return Qt.NoItemFlags
        if node.src is None:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable
        src = QtCore.QModelIndex(node.src)
        flags = self.src.flags(src) if src.isValid() else Qt.ItemIsEnabled
        if node.link:
            flags &= ~Qt.ItemIsEditable
        flags &= ~(Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)

        if not node.link and node.obj is not None:
            if treefolders.is_folder(node.obj):
                flags |= Qt.ItemIsDropEnabled
            elif treefolders._body_of(node.obj) is not None:
                flags |= Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
        elif node is self.part:
            flags |= Qt.ItemIsDropEnabled
        return flags

    # ------------------------------------------------------------------ dragging into folders
    MIME = "application/x-freeworks-features"

    def supportedDropActions(self):
        return Qt.MoveAction

    def supportedDragActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, indexes):
        names = []
        for index in indexes:
            node = self.node(index)
            if node is not None and node.obj is not None and not node.link and node.obj.Name not in names:
                names.append(node.obj.Name)
        data = QtCore.QMimeData()
        data.setData(self.MIME, QtCore.QByteArray("\n".join(names).encode()))
        return data

    def _dropped(self, data):
        if self.doc is None or not data.hasFormat(self.MIME):
            return []
        names = bytes(data.data(self.MIME)).decode().split("\n")
        return [o for o in (self.doc.getObject(n) for n in names if n) if o is not None]

    def _drop_folder(self, parent):
        """The folder a drop onto parent puts features in, else None (out of their folder)."""
        node = self.node(parent) if parent.isValid() else None
        while node is not None and node is not self.root:
            if node.obj is not None and not node.link and treefolders.is_folder(node.obj):
                return node.obj
            node = node.parent
        return None

    def _reorder_target(self, row, parent):
        ""
        node = self.node(parent) if parent.isValid() else self.root
        if node is None:
            return None, False
        if row < 0:
            target, after = node, True             # dropped on a feature: it goes under it
        elif node.children:
            target, after = (node.children[row], False) if row < len(node.children) else (node.children[-1], True)
        else:
            return None, False
        obj = target.obj if target is not None and not target.link else None
        if obj is None or treefolders.is_folder(obj) or treefolders._body_of(obj) is None:
            return None, False
        return obj, after

    def _says(self, text):
        try:
            Gui.getMainWindow().statusBar().showMessage(text, 4000)
        except Exception as _fw_err:
            _fw_log("fmtree.py:1191", _fw_err)

    def _tag(self, text):
        ""

        try:
            if text:
                QtWidgets.QToolTip.showText(QtGui.QCursor.pos() + QtCore.QPoint(16, 8), text)
            else:
                QtWidgets.QToolTip.hideText()
        except Exception as _fw_err:
            _fw_log("fmtree.py:1202", _fw_err)
        self.drag_tag = text

    def _above(self, target, after):
        """The feature a reorder drop lands under: the target itself, or the one above it."""
        if after:
            return target
        for node in self._nodes_of(target):
            sibs = node.parent.children if node.parent is not None else []
            i = sibs.index(node) if node in sibs else -1
            for prev in reversed(sibs[:max(i, 0)]):
                if prev.obj is not None and not prev.link:
                    return prev.obj
        return None

    def _nodes_of(self, obj):
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node.obj is obj and not node.link:
                yield node
            stack.extend(node.children)

    @staticmethod
    def _label(obj):
        return getattr(obj, "Label", "") or getattr(obj, "Name", "")

    def canDropMimeData(self, data, action, row, column, parent):
        ok, text = self._can_drop(data, row, parent)
        self._tag(text if ok else "")
        return ok

    def _can_drop(self, data, row, parent):
        objs = self._dropped(data)
        if not objs:
            return False, ""
        folder = self._drop_folder(parent)
        if folder is not None:
            return treefolders.can_move_into(folder, objs), "Move into " + self._label(folder)
        from . import reorder
        target, after = self._reorder_target(row, parent)
        if treefolders.can_move_out(objs):
            if target is not None and target not in objs and treefolders.folder_of(target) is not treefolders.folder_of(objs[0]) \
                    and reorder.can_move(objs, target, after):
                above = self._above(target, after)
                return True, ("Move below " + self._label(above)) if above is not None else ("Move above " + self._label(target))
            return True, "Move out of the folder"
        if target is None or target in objs:
            return False, ""
        why = reorder.why_not(objs, target, after)
        if why:
            self._says("Cannot reorder: " + why)
            return False, ""
        above = self._above(target, after)
        return True, ("Move below " + self._label(above)) if above is not None else ("Move above " + self._label(target))

    def dropMimeData(self, data, action, row, column, parent):
        objs = self._dropped(data)
        ok = bool(objs) and self.canDropMimeData(data, action, row, column, parent)
        self._tag("")
        if not ok:
            return False
        folder = self._drop_folder(parent)
        if folder is not None:
            done = treefolders.move_into(folder, objs)
        elif treefolders.can_move_out(objs):
            from . import reorder
            target, after = self._reorder_target(row, parent)
            far = target is not None and target not in objs and treefolders.folder_of(target) is not treefolders.folder_of(objs[0]) \
                and reorder.can_move(objs, target, after)

            done = reorder.move(objs, target, after) if far else treefolders.move_out(objs)
        else:
            from . import reorder
            target, after = self._reorder_target(row, parent)
            done = reorder.move(objs, target, after)
        if done:
            self.soon()
        return False        # the rows come back from the rebuild, nothing to remove here

    def _data(self, first, last, roles=()):
        # FreeCAD's tree sends a change for every row it touches, thousands of times in a big
        # recompute or a batch of inserts; the rows are gathered and repainted once when events
        # run again (each row and its parents once), not once per change (profile 11-12: 15k calls)
        if first.column() != 0:
            return
        parent = first.parent()
        dirty = self.__dict__.setdefault("_dirty", {})
        for row in range(first.row(), last.row() + 1):
            key = self.src.index(row, 0, parent).internalId()
            if key not in self.by_id:
                continue
            if key not in dirty:
                dirty[key] = set(roles) if roles else None      # None: every role
            elif dirty[key] is not None:
                if roles:
                    dirty[key].update(roles)
                else:
                    dirty[key] = None
        if dirty and not self.__dict__.get("_flush_due"):
            self._flush_due = True
            QtCore.QTimer.singleShot(0, self._flush_data)

    def _flush_data(self):
        self._flush_due = False
        dirty, self._dirty = self.__dict__.get("_dirty", {}), {}
        ups = set()
        try:
            for key, roles in dirty.items():
                for node in self.by_id.get(key, ()):        # looked up now: a rebuild may have come between
                    index = self.index_of(node)
                    if not index.isValid():
                        continue
                    self.dataChanged.emit(index, index, sorted(roles) if roles else [])
                    self._mark_parents(node, ups)
        except RuntimeError as _fw_err:
            _fw_log("fmtree.py:1318", _fw_err)

    def _mark_parents(self, node, ups):
        ""

        up = node.parent
        while up is not None and up is not self.root and id(up) not in ups:
            ups.add(id(up))
            i = self.index_of(up)
            if i.isValid():
                self.dataChanged.emit(i, i, [Qt.DecorationRole, Qt.ToolTipRole])
            up = up.parent

    def nodes_for(self, src):
        return self.by_id.get(src.internalId(), [])

    def body_rows(self, every=False, view=None):
        """For the rollback bar: (document, body, row) where each body's features are listed."""
        out = []
        if self.doc is None or self.part is None:
            return out
        if self.flat is not None:
            out.append((self.doc, self.flat, self.index_of(self.part)))
        for node in self.part.children:
            try:
                is_body = node.obj is not None and node.obj.TypeId == BODY
            except Exception:
                is_body = False     # deleted while its document closes, before the next rebuild
            if is_body:
                out.append((self.doc, node.obj, self.index_of(node)))
        if view is not None and not every:
            out = [r for r in out if view.isExpanded(r[2])]
        return out


# --------------------------------------------------------------------------- the view
_BASE_DATA[0] = Model.data


PICK_OWNER_LIMIT = 60     # element picks looked up per change (a box pick of hundreds keeps FreeCAD's rows)


def _key(obj):
    try:
        return (obj.Document.Name, obj.Name)
    except Exception:
        return None


def pick_owners():
    ""





    out = {}
    try:
        sels = Gui.Selection.getSelectionEx("", 1)
    except Exception:
        return out
    try:
        from . import suppress
    except Exception as _fw_err:
        _fw_log("fmtree.py:pick_owners", _fw_err)
        return out
    asked = 0
    for sel in sels:
        try:
            obj = sel.Object
            subs = list(sel.SubElementNames) or [""]
        except Exception:
            continue
        key = _key(obj)
        if key is None:
            continue
        owners, moved = [], False
        for sub in subs:
            found = obj
            if suppress._short(sub) and asked < PICK_OWNER_LIMIT:
                asked += 1
                try:
                    found = suppress.owner(obj, sub) or obj
                except Exception as _fw_err:
                    _fw_log("fmtree.py:pick_owners", _fw_err)
                    found = obj
            if found is not obj:
                moved = True
            if not any(o is found for o in owners):
                owners.append(found)
        if moved:
            prev = out.get(key)
            if prev is None:
                out[key] = owners
            else:
                prev.extend(o for o in owners if not any(p is o for p in prev))
    return out


class _SelectionObserver:
    def __init__(self, timer):
        self.timer = timer

    def _soon(self, *args):
        try:
            self.timer.start()
        except RuntimeError as _fw_err:
            _fw_log("fmtree.py:1365", _fw_err)

    addSelection = removeSelection = setSelection = clearSelection = _soon


def part_suffix(doc):
    ""

    try:
        from . import asmui
        if asmui._assembly() is not None:
            return ""           # an assembly's top row is drawn by asmui
        cfg_on, state_on = asmui.tree_names()
    except Exception:
        cfg_on, state_on = True, True
    if doc is None or not (cfg_on or state_on) or not _alive(doc):
        return ""
    try:
        if any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects) and \
                not any(o.TypeId == BODY for o in doc.Objects):
            return ""           # a drawing's top row is its name only: no configuration, no display state
    except Exception as _fw_err:
        _fw_log("fmtree.py:suffix-drawing", _fw_err)
    cfg = "Default"
    try:
        from . import configmanager
        t = configmanager.table(doc)
        if t is not None:
            cfg = t.active() or cfg
    except Exception as _fw_err:
        _fw_log("fmtree.py:suffix-cfg", _fw_err)
    state = None
    try:
        from . import displaystates
        state = displaystates.active(doc)
    except Exception as _fw_err:
        _fw_log("fmtree.py:suffix-state", _fw_err)
    out = ""
    if cfg_on:
        out += " (%s)" % cfg
    if state_on:
        out += " <%s>" % (state or "<%s>_Display State 1" % cfg)
    return out


class FeatureTree(QtWidgets.QTreeView):
    ""

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        try:
            fm = self.fm
            if fm.part is None or self.state() == QtWidgets.QAbstractItemView.EditingState and \
                    self.currentIndex() == index:
                return
            if fm.index_of(fm.part) != index:
                return
            suffix = part_suffix(getattr(fm, "doc", None) or App.ActiveDocument)
            if not suffix:
                return
            # the configuration and display state are drawn after the name; the row's own text
            # (which renames, menus and checks read) stays the part's name
            opt = QtWidgets.QStyleOptionViewItem(option)
            self.itemDelegate(index).initStyleOption(opt, index)
            opt.rect = self.visualRect(index)
            text_rect = self.style().subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, self)
            metrics = QtGui.QFontMetrics(opt.font)
            left = text_rect.left() + metrics.horizontalAdvance(opt.text) + 3
            rect = QtCore.QRect(left, text_rect.top(), max(0, self.viewport().width() - left), text_rect.height())
            selected = bool(opt.state & QtWidgets.QStyle.State_Selected)
            role = QtGui.QPalette.HighlightedText if selected else QtGui.QPalette.Text
            painter.save()
            painter.setFont(opt.font)
            painter.setPen(opt.palette.color(role))
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(suffix, Qt.ElideRight, rect.width()))
            painter.restore()
        except Exception as _fw_err:
            _fw_log("fmtree.py:part-suffix", _fw_err)

    def dragLeaveEvent(self, event):
        self.fm._tag("")
        super().dragLeaveEvent(event)

    def __init__(self, shell, tree):
        super().__init__(tree.parentWidget())
        self.setObjectName("SWFeatureTree")
        self.shell = shell
        self.tree = tree
        self.fm = Model(tree, self)
        self.setModel(self.fm)
        self.setHeaderHidden(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed)
        self.setExpandsOnDoubleClick(False)
        self.setMouseTracking(True)

        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setUniformRowHeights(True)
        self.setAttribute(Qt.WA_Hover, True)
        self._copy_look()
        try:
            from . import treerowlook
            self.setItemDelegate(treerowlook.RowDelegate(self))
        except Exception as _fw_err:
            _fw_log("fmtree.py:treerowlook", _fw_err)
        self.open = set()           # keys of the open rows
        self.seen = set()           # keys already given their first open/closed state
        self._syncing = False
        self._hover = None
        self.expanded.connect(lambda i: self._remember(i, True))
        self.expanded.connect(self._fill_component)
        self.collapsed.connect(lambda i: self._remember(i, False))
        self.fm.rebuilt.connect(self._after_rebuild)
        self.fm.modelAboutToBeReset.connect(self._before_rebuild)
        self.selectionModel().selectionChanged.connect(self._push)
        # FreeCAD's tree changes its rows one at a time (300 picks: 300 signals): one pull after them
        self.tree.selectionModel().selectionChanged.connect(self._pull_soon)
        # FreeCAD changes its tree's rows with the signals blocked at times (clearing the selection):
        # its selection itself says when to look again
        self._pull_timer = QtCore.QTimer(self)
        self._pull_timer.setSingleShot(True)
        self._pull_timer.setInterval(0)
        self._pull_timer.timeout.connect(self._pull)
        self._observer = _SelectionObserver(self._pull_timer)
        Gui.Selection.addObserver(self._observer)
        tree.installEventFilter(self)
        self._after_rebuild()
        try:
            from . import displaypane
            displaypane.attach(self)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Display Pane: %s\n" % error)
        self.place()
        self.show()
        self.raise_()

    def _copy_look(self):
        tree = self.tree
        self.setFont(tree.font())
        self.setIconSize(tree.iconSize())
        self.setIndentation(tree.indentation())

        self.setRootIsDecorated(False)
        self.setFrameShape(tree.frameShape())
        self.setVerticalScrollMode(tree.verticalScrollMode())
        self.setAlternatingRowColors(tree.alternatingRowColors())

    def fm_body_rows(self, every=False):
        return self.fm.body_rows(every, None if every else self)

    # ------------------------------------------------------------------ place
    def place(self):
        tree = self.tree
        if not alive(tree):
            return
        if self.parentWidget() is not tree.parentWidget():
            self.setParent(tree.parentWidget())
            self.show()
        if self.geometry() != tree.geometry():
            self.setGeometry(tree.geometry())
        self.setVisible(tree.isVisible())
        self.raise_()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is self.tree:
            t = event.type()
            if t in (QtCore.QEvent.Move, QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.Hide,
                     QtCore.QEvent.ParentChange, QtCore.QEvent.ZOrderChange):
                QtCore.QTimer.singleShot(0, self.place)
        return False

    # ------------------------------------------------------------------ open rows
    def _fill_component(self, index):
        """Opening a component opens its row in FreeCAD's tree too: FreeCAD then makes the part's
        rows, and the rebuild shows them here (the row stays open: _remember)."""
        node = self.fm.node(index)
        if node is None or not _unfilled_component(node):
            return
        src = QtCore.QModelIndex(node.src)
        if src.isValid() and alive(self.tree):
            self.tree.expand(src)

    def _remember(self, index, on):
        if self._syncing:
            return
        node = self.fm.node(index)
        if node is None:
            return
        key = node.key()
        (self.open.add if on else self.open.discard)(key)

    def _before_rebuild(self):
        self._scroll = self.verticalScrollBar().value()

    def _after_rebuild(self):
        self._syncing = True
        try:
            def walk(parent):
                for row in range(self.fm.rowCount(parent)):
                    index = self.fm.index(row, 0, parent)
                    node = self.fm.node(index)
                    if node is None or not node.children:
                        continue
                    key = node.key()
                    if key not in self.seen:
                        self.seen.add(key)
                        if node is self.fm.part or (node.obj is not None and node.obj.TypeId in (BODY, "TechDraw::DrawPage")):
                            self.open.add(key)      # the part and its bodies list their features
                    if key in self.open:
                        self.expand(index)
                    walk(index)
            walk(QtCore.QModelIndex())
            self._pull()
        finally:
            self._syncing = False
        if getattr(self, "_filter_text", ""):
            self.fm_filter(self._filter_text)
        scroll = getattr(self, "_scroll", None)
        if scroll is not None:
            QtCore.QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(scroll))

    def updateGeometries(self):
        super().updateGeometries()
        # QTreeView sets the viewport margins here: keep the Display Pane's room on the right
        right = getattr(self, "_pane_margin", 0)
        if right:
            top = (0 if self.isHeaderHidden() else self.header().height()) + getattr(self, "_pane_top", 0)
            self.setViewportMargins(0, top, right, 0)

    # ------------------------------------------------------------------ the filter box (leftpane)
    def fm_filter(self, text):
        ""

        self._filter_text = text = (text or "").strip()
        needle = text.lower()

        def label(index):
            return str(index.data(Qt.DisplayRole) or "").lower()

        from . import treefilter      # the funnel menu's modes: names, tags, descriptions, comments
        whole = not treefilter.hierarchy_only()

        def hit(index):
            node = self.fm.node(index)
            return treefilter.matches(getattr(node, "obj", None), label(index), needle)

        def visit(parent, shown=False):
            any_kept = False
            for row in range(self.fm.rowCount(parent)):
                index = self.fm.index(row, 0, parent)
                match = bool(needle) and hit(index)
                below = visit(index, shown or (match and whole))
                keep = not needle or shown or match or below
                self.setRowHidden(row, parent, not keep)
                if needle and below:
                    self.expand(index)
                any_kept = any_kept or keep
            return any_kept

        part = self.fm.index_of(self.fm.part) if self.fm.part is not None else QtCore.QModelIndex()
        if part.isValid():
            visit(part)
        return [index.data(Qt.DisplayRole) for index in self.fm_shown()]

    def fm_shown(self):
        """The rows under the part the filter leaves (for checks)."""
        out = []
        part = self.fm.index_of(self.fm.part) if self.fm.part is not None else QtCore.QModelIndex()

        def walk(parent):
            for row in range(self.fm.rowCount(parent)):
                if self.isRowHidden(row, parent):
                    continue
                index = self.fm.index(row, 0, parent)
                out.append(index)
                walk(index)
        if part.isValid():
            walk(part)
        return out

    # ------------------------------------------------------------------ selection both ways
    def _push(self, *args):
        """A pick here selects the same rows in FreeCAD's tree, which selects the objects."""
        if self._syncing:
            return
        selection = QtCore.QItemSelection()
        try:    # fwsketch hook (fix64): a block row picks the block's entities
            from . import sketchblocktree
            if any(sketchblocktree.picked(self.fm.node(i)) for i in self.selectionModel().selectedRows()
                   if self.fm.node(i) is not None and self.fm.node(i).src is None):
                return
        except Exception as _fw_err:
            _fw_log("fmtree.py:1588", _fw_err)
        first = None
        for index in self.selectionModel().selectedRows():
            src = self.fm.source(index)
            if src.isValid():
                selection.select(src, src)
                if first is None:
                    first = src
        self._syncing = True
        try:
            flags = QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows
            self.tree.selectionModel().select(selection, flags)
            if first is not None:
                self.tree.selectionModel().setCurrentIndex(first, QtCore.QItemSelectionModel.NoUpdate)
        finally:
            self._syncing = False

    def _pull_soon(self, *args):
        if self._syncing:
            return          # our own push coming back
        self._pull_timer.start()

    def _pull(self, *args):
        """FreeCAD's selection (its tree's rows) shows here, on the rows that are not History links."""
        if self._syncing and args:
            return
        was = self._syncing
        self._syncing = True
        try:
            selection = QtCore.QItemSelection()
            first = None
            owners = pick_owners()      # a face picked in the view: the feature that made it, not the Tip
            lit = set()

            def light(node):
                nonlocal first
                if node is None or id(node) in lit:
                    return
                lit.add(id(node))
                index = self.fm.index_of(node)
                if not index.isValid():
                    return
                selection.select(index, index)
                if first is None:
                    first = index

            def owner_node(obj):
                return next(iter(self.fm._nodes_of(obj)), None)

            for src in self.tree.selectionModel().selectedRows():
                found = self.fm.nodes_for(src)
                nodes = [n for n in found if not n.link] or found[:1]
                for node in nodes[:1]:
                    moved = owners.pop(_key(node.obj), None) if node.obj is not None else None
                    if moved is None:
                        light(node)
                        continue
                    for obj in moved:
                        light(node if obj is node.obj else owner_node(obj))
            for moved in owners.values():       # picks whose row FreeCAD's tree did not light
                for obj in moved:
                    light(owner_node(obj))
            if first is None and not self.selectionModel().hasSelection():
                return          # nothing picked, nothing shown: no work
            flags = QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows
            self.selectionModel().select(selection, flags)
            if first is not None:
                self.selectionModel().setCurrentIndex(first, QtCore.QItemSelectionModel.NoUpdate)
                self.scrollTo(first)
        finally:
            self._syncing = was

    # ------------------------------------------------------------------ the pointer
    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        key = QtCore.QPersistentModelIndex(index) if index.isValid() else None
        if key == self._hover:
            return
        self._hover = key
        node = self.fm.node(index) if index.isValid() else None
        obj = node.obj if node is not None else None
        Gui.Selection.clearPreselection()
        if obj is not None:
            # as FreeCAD's tree does on its rows (its own way reads the pointer over its rows)
            try:
                Gui.Selection.setPreselection(obj, "", 0, 0, 0, 1)
            except Exception as _fw_err:
                _fw_log("fmtree.py:1655", _fw_err)
        _tree_hover(obj)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._hover is not None:
            self._hover = None
            Gui.Selection.clearPreselection()
            _tree_hover(None)

    def mousePressEvent(self, event):

        index = self.indexAt(event.position().toPoint())
        self._slow = None
        if event.button() == Qt.LeftButton and index.isValid() and \
                not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)):
            obj = self._row_obj(index)
            picked = {self._row_obj(i) for i in self.selectionModel().selectedIndexes()}
            if obj is not None and picked == {obj}:
                self._slow = obj
        super().mousePressEvent(event)

    def _row_obj(self, index):
        node = self.fm.node(index) if index.isValid() else None
        obj = getattr(node, "obj", None) if node is not None else None
        try:
            return obj if obj is not None and obj.Document is not None else None
        except Exception:
            return None

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        obj, self._slow = getattr(self, "_slow", None), None
        if not getattr(self, "_slow_rename", True):
            return                  # Options: Edit name with slow double click is off
        if obj is None or self.state() == QtWidgets.QAbstractItemView.DraggingState:
            return
        if self._row_obj(self.indexAt(event.position().toPoint())) is not obj:
            return
        self._slow_token = token = object()

        def go():
            if getattr(self, "_slow_token", None) is not token:
                return              # a double click came: it opens the feature instead
            try:
                if self.state() != QtWidgets.QAbstractItemView.EditingState and obj.Document is not None:
                    self.fm_rename(obj)
            except Exception as _fw_err:
                _fw_log("fmtree.py:1703", _fw_err)
        QtCore.QTimer.singleShot(QtWidgets.QApplication.doubleClickInterval() + 50, go)

    def setEditTriggers(self, triggers):
        """Options' "Edit name with slow double click" (optionsextras) asks for Qt's SelectedClicked.
        The view keeps F2 for Qt and does the slow double-click itself (mouseReleaseEvent), which a
        double-click cancels: Qt's own would also rename after a quick double-click."""
        V = QtWidgets.QAbstractItemView
        def bits(x):
            return int(x.value if hasattr(x, "value") else x)
        self._slow_rename = bool(bits(triggers) & bits(V.SelectedClicked))
        super().setEditTriggers(V.EditTrigger(bits(triggers) & bits(V.EditKeyPressed)))

    def mouseDoubleClickEvent(self, event):
        self._slow_token = None
        self._slow = None       # Qt sends the second click's press too: its release must not start a rename
        index = self.indexAt(event.position().toPoint())
        node = self.fm.node(index) if index.isValid() else None
        if node is None or node.obj is None:
            if index.isValid():
                self.setExpanded(index, not self.isExpanded(index))
            return
        try:
            from . import featuredimshow
            if not node.link and featuredimshow.tree_double_click(node.obj):
                return
        except Exception as _fw_err:
            _fw_log("fmtree.py:1730", _fw_err)
        from . import contextbar, freezebar
        if not freezebar.can_edit(node.obj):
            return
        if not contextbar._open(node.obj):
            self.setExpanded(index, not self.isExpanded(index))

    def contextMenuEvent(self, event):
        ""
        index = self.indexAt(event.pos())
        node = self.fm.node(index) if index.isValid() else None
        target = None
        if node is not None and node.obj is not None and _is_material(node.obj) or \
                node is not None and node.src is None and (node.text or "").startswith("Material"):
            target = ("material", str(index.data(Qt.DisplayRole) or ""))     # also "Material <not specified>"
        elif node is not None and node.obj is not None and _is_folder(node.obj):
            target = ("surfaces" if _is_surface_folder(node.obj) else "bodies", str(index.data(Qt.DisplayRole) or ""))
        elif node is not None and node.src is None and (node.text or "") in ("History", "Sensors", "Annotations"):
            target = (node.text.lower(), node.text)
        elif node is not None and node.src is None and node.text == "Flat-Pattern" and \
                any(n.obj is not None for n in node.children):
            target = ("flatfolder", node.text)          # pkg257: the sheet metal Flat-Pattern folder row
        elif node is not None and node.src is None and (node.text or "") == "Flat-Pattern" and \
                any(getattr(c, "obj", None) is not None for c in getattr(node, "children", [])):
            # look-audit smmenus-1120: the sheet metal Flat-Pattern folder row (_flat_folder) opened nothing;
            # it opens its Flat-Pattern1's menu (Flatten, Export to DXF / DWG, ...)
            target = next(c.obj for c in node.children if getattr(c, "obj", None) is not None)
        elif node is not None and node.src is None:
            try:
                from . import sketchblocktree
                sketchblocktree.menu(node, event.globalPos(), self)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: block row menu: %s\n" % error)
            event.accept()
            return
        elif node is not None and node.obj is not None:
            target = node.obj
        elif node is not None and node is self.fm.part:
            target = self.fm.doc
        elif node is None and self.fm.doc is not None:
            target = ("blank", "")
        if target is not None:
            try:
                from . import fmmenu
                if isinstance(target, tuple):
                    target = fmmenu.Folder(target[0], self.fm.doc, target[1])
                if fmmenu.show(self.shell, target, event.globalPos(), self) is not None:
                    event.accept()
                    return
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: FeatureManager menu not shown: %s\n" % error)
        src = self.fm.source(index) if index.isValid() else QtCore.QModelIndex()
        tree = self.tree
        if src.isValid():
            tree.scrollTo(src)
            pos = tree.visualRect(src).center()
        else:
            pos = QtCore.QPoint(2, max(2, tree.viewport().height() - 2))
        menu_event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, event.globalPos(),
                                             event.modifiers())
        QtWidgets.QApplication.sendEvent(tree.viewport(), menu_event)

    # ------------------------------------------------------------------ for fmmenu
    def _node_of(self, obj):
        """The row of a document object, or the part row for the document."""
        if obj is None or isinstance(obj, App.Document):
            return self.fm.part
        todo = list(self.fm.root.children)
        while todo:
            node = todo.pop(0)
            if node.obj is obj and not node.link:
                return node
            todo.extend(node.children)
        return None

    def fm_native_menu(self, obj, global_pos):
        """FreeCAD's own tree menu for obj's row (the FreeCAD submenu's last item; Shift+right-click)."""
        node = self._node_of(obj) if obj is not None else None
        index = self.fm.index_of(node) if node is not None else QtCore.QModelIndex()
        src = self.fm.source(index) if index.isValid() else QtCore.QModelIndex()
        tree = self.tree
        if src.isValid():
            tree.scrollTo(src)
            pos = tree.visualRect(src).center()
        else:
            pos = QtCore.QPoint(2, max(2, tree.viewport().height() - 2))
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, global_pos, Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(tree.viewport(), event)
        return True

    def fm_reveal(self, obj):
        """Go To: open the folders above the row and scroll it into view."""
        node = self._node_of(obj)
        index = self.fm.index_of(node) if node is not None else QtCore.QModelIndex()
        if not index.isValid():
            return
        parent = index.parent()
        while parent.isValid():
            self.expand(parent)
            parent = parent.parent()
        self.scrollTo(index)

    def fm_rename(self, obj):
        ""
        node = self._node_of(obj)
        index = self.fm.index_of(node) if node is not None else QtCore.QModelIndex()
        if index.isValid():
            self.fm_reveal(obj)
            self.setCurrentIndex(index)
            if self.edit(index, QtWidgets.QAbstractItemView.AllEditTriggers, None):
                return
        from . import fmmenu
        fmmenu.rename(None, obj)        # no row to edit: the Rename box

    def remove(self):
        try:
            Gui.Selection.removeObserver(self._observer)
        except Exception as _fw_err:
            _fw_log("fmtree.py:1840", _fw_err)
        self._pull_timer.stop()
        try:
            self.tree.removeEventFilter(self)
            self.tree.selectionModel().selectionChanged.disconnect(self._pull_soon)
        except Exception as _fw_err:
            _fw_log("fmtree.py:1846", _fw_err)
        self.fm.disconnect_source()
        self.hide()
        self.setParent(None)
        self.deleteLater()


def visible_row(label):
    """(viewport, rect) of the row showing label in the tree on screen, the ordered one when it is
    up, else None: for scripts that click rows by label."""
    from . import shell as shell_module
    manager = getattr(shell_module.shell(), "feature_manager", None)
    view = getattr(manager, "view", None)
    if view is None or not alive(view):
        return None
    model = view.fm

    def walk(parent):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            node = model.node(index)
            if not node.link:
                text = str(index.data(Qt.DisplayRole) or "")
                bare = text.split(" <")[0]
                if node.obj is not None and (getattr(node.obj, "Label2", "") or "") and bare.endswith(")"):
                    bare = bare[:-len(" (%s)" % node.obj.Label2)] if bare.endswith(" (%s)" % node.obj.Label2) else bare
                if label in (text, bare, sketchstatus.label_of(text), sketchstatus.label_of(bare)):
                    return index
                found = walk(index)
                if found is not None:
                    return found
        return None
    index = walk(QtCore.QModelIndex())
    if index is None:
        return None
    parent = index.parent()
    while parent.isValid():
        view.expand(parent)
        parent = parent.parent()
    view.scrollTo(index)
    return view.viewport(), view.visualRect(index)


class FeatureManager(QtCore.QObject):
    ""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.view = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self._doc = None
        self.tick()

    def _tree(self):
        """FreeCAD's tree, also while the flyout tree has borrowed it from the pane."""
        pane = getattr(self.shell, "left_pane", None)
        tree = pane.tree_widget() if pane is not None and alive(pane) else None
        if tree is None and self.view is not None and alive(self.view) and alive(self.view.tree):
            tree = self.view.tree
        return tree

    def tick(self):
        tree = self._tree()
        if not (self.shell.enabled and enabled()) or tree is None or not alive(tree):
            self.drop()
            return
        if self.view is not None and (not alive(self.view) or self.view.tree is not tree):
            self.drop()
        if self.view is None:
            self.view = FeatureTree(self.shell, tree)
        else:
            self.view.place()
        doc = App.ActiveDocument
        name = doc.Name if doc is not None else None
        if name != self._doc:
            self._doc = name
            self.view.fm.soon()

    def drop(self):
        view = self.view
        if view is not None and alive(view):
            view.remove()
        elif view is not None:
            # its Qt object went with its parent: the selection observer would stay registered for good
            try:
                Gui.Selection.removeObserver(view._observer)
            except Exception as _fw_err:
                _fw_log("fmtree.py:1937", _fw_err)
        self.view = None

    def remove(self):
        self.timer.stop()
        self.drop()
