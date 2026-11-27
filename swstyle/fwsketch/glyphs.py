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
import FreeCADGui as Gui

from . import trace

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets

GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
VIEW = "User parameter:BaseApp/Preferences/Mod/Sketcher/View"

# The glyph types FreeCAD draws (EditModeConstraintCoinManager::iconTypeFromConstraint)
TYPES = ("Constraint_Horizontal", "Constraint_Vertical", "Constraint_PointOnObject", "Constraint_Tangent",
         "Constraint_Parallel", "Constraint_Perpendicular", "Constraint_EqualLength", "Constraint_Symmetric",
         "Constraint_Block")
LABEL_INDEX = 0                     # the SoDatumLabel of a dimension in its constraint's separator
ICON_INDEXES = (2, 5)               # the SoImage of a glyph (and of the second one)


def wanted():
    return App.ParamGet(GENERAL).GetBool("SolidWorksGlyphs", True)


def icon_size():
    """FreeCAD's glyph size: Mod/Sketcher/View ConstraintSymbolSize, else the application font's
    height in pixels (ViewProviderSketch::defaultApplicationFontSizePixels)."""
    size = App.ParamGet(VIEW).GetInt("ConstraintSymbolSize", 0)
    if size > 0:
        return size
    return int(QtGui.QFontMetricsF(QtWidgets.QApplication.font()).height())


def max_dpr():
    """BitmapFactory's getMaximumDPR: the cached pixmap holds size times this many pixels."""
    try:
        return max(s.devicePixelRatio() for s in QtGui.QGuiApplication.screens()) or 1.0
    except ValueError:
        return 1.0


def _symbol(p, type_, u):
    ""
    def line(x1, y1, x2, y2):
        p.drawLine(QtCore.QPointF(x1 * u, y1 * u), QtCore.QPointF(x2 * u, y2 * u))
    if type_ == "Constraint_Horizontal":
        line(3, 7.5, 13, 7.5)
    elif type_ == "Constraint_Vertical":
        line(7.5, 3, 7.5, 13)
    elif type_ == "Constraint_Parallel":
        line(3, 11, 9, 3)
        line(7, 13, 13, 5)
    elif type_ == "Constraint_Perpendicular":
        line(8, 3, 8, 12.5)
        line(3, 12.5, 13, 12.5)
    elif type_ == "Constraint_Tangent":
        p.drawEllipse(QtCore.QRectF(4 * u, 6 * u, 8 * u, 8 * u))
        line(2, 5.3, 14, 5.3)
    elif type_ == "Constraint_EqualLength":
        line(3, 6, 13, 6)
        line(3, 10, 13, 10)
    elif type_ == "Constraint_PointOnObject":
        p.drawEllipse(QtCore.QRectF(3 * u, 3 * u, 7 * u, 7 * u))
        p.drawEllipse(QtCore.QRectF(6 * u, 6 * u, 7 * u, 7 * u))
    elif type_ == "Constraint_Symmetric":
        line(8, 2.5, 8, 13.5)
        p.setBrush(QtGui.QColor(0, 0, 0))
        for pts in (((2, 5), (6, 8), (2, 11)), ((14, 5), (10, 8), (14, 11))):
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x * u, y * u) for x, y in pts]))
        p.setBrush(QtCore.Qt.NoBrush)
    elif type_ == "Constraint_Block":
        p.drawRect(QtCore.QRectF(4 * u, 7 * u, 8 * u, 6 * u))
        p.drawArc(QtCore.QRectF(5.5 * u, 3 * u, 5 * u, 7 * u), 0, 180 * 16)
    elif type_ == "SW_Collinear":
        line(1.5, 14.5, 6.5, 9.5)
        line(9.5, 6.5, 14.5, 1.5)
    elif type_ == "SW_EqualCurvature":

        p.drawArc(QtCore.QRectF(2 * u, 2.5 * u, 9 * u, 9 * u), 90 * 16, 90 * 16)
        path = QtGui.QPainterPath(QtCore.QPointF(6.5 * u, 2.5 * u))
        path.cubicTo(QtCore.QPointF(10 * u, 2.5 * u), QtCore.QPointF(12.5 * u, 4 * u), QtCore.QPointF(14.5 * u, 7.5 * u))
        p.drawPath(path)
        line(5, 10.5, 12, 10.5)
        line(5, 13.5, 12, 13.5)
    elif type_ == "SW_Patterned":
        for x, y in ((2.5, 9.5), (6, 6), (9.5, 2.5)):
            p.drawRect(QtCore.QRectF(x * u, y * u, 4 * u, 4 * u))
    elif type_ == "SW_Midpoint":
        line(1.5, 14.5, 6, 10)
        line(10, 6, 14.5, 1.5)
        p.drawRect(QtCore.QRectF(6 * u, 6 * u, 4 * u, 4 * u))
    else:
        return False
    return True


def glyph(type_, side):
    """A black square of side pixels with the symbol cut out (FreeCAD fills it with the glyph
    colour); None for a type with no symbol here."""
    image = QtGui.QImage(side, side, QtGui.QImage.Format_ARGB32_Premultiplied)
    image.fill(QtGui.QColor(0, 0, 0))
    p = QtGui.QPainter(image)
    p.setRenderHint(QtGui.QPainter.Antialiasing, False)
    u = side / 16.0
    pen = QtGui.QPen(QtGui.QColor(0, 0, 0), max(1.0, 1.4 * u), QtCore.Qt.SolidLine, QtCore.Qt.FlatCap,
                     QtCore.Qt.MiterJoin)
    p.setPen(pen)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
    known = _symbol(p, type_, u)
    p.end()
    return image if known else None


def _png(image):
    data = QtCore.QByteArray()
    buf = QtCore.QBuffer(data)
    buf.open(QtCore.QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


installed = []   # the cache keys this session filled, for tests


SIZES = range(8, 49)   # every size the glyph size setting is likely to take, and the font's


def install(sizes=None):
    """Fills FreeCAD's glyph cache with the squares for the glyph sizes; True when all are ours."""
    if not wanted():
        return False
    if sizes is None:
        # the size in use now; the other sizes a moment after the start (369 squares drawn at
        # start were 67 ms of it), before anyone can change the glyph size and open a sketch
        now = icon_size()
        try:
            from PySide import QtCore as _qc
            _qc.QTimer.singleShot(4000, lambda: install(sorted(set(SIZES) | {icon_size()})))
            sizes = [now]
        except Exception:
            sizes = sorted(set(SIZES) | {now})
    dpr = max_dpr()
    ours = True
    for size in sizes:
        side = max(4, int(round(size * dpr)))
        for type_ in TYPES:
            key = "%s%d" % (type_, size)
            if key in installed:
                continue
            try:
                Gui.addIcon(key, _png(glyph(type_, side)), "PNG")
                installed.append(key)
            except AssertionError:
                ours = False          # FreeCAD drew this one first
            except Exception:
                ours = False
    return ours


# --- clashing relations ----------------------------------------------------------------------
def _constraint_group(view):
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setName("ConstraintGroup")
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.apply(view.getSceneGraph())
    path = sa.getPath()
    return path.getTail() if path is not None else None


def _rgb(c):
    return tuple(round(v * 255) for v in c)


def _set_label(node, colour):
    try:
        if node.getTypeId().getName() != "SoDatumLabel":
            return False
        node.set("textColor %f %f %f" % colour)
        return True
    except Exception:
        return False


def _ids(info):
    """The 0-based constraint indexes a glyph stands for (its SoInfo: "7" or "5,7" when grouped)."""
    import re
    try:
        value = info.string.getValue()
        return {int(x) for x in re.findall(r"\d+", getattr(value, "getString", lambda: str(value))())}
    except Exception:
        return set()


def _set_icon(node, colour):
    """Recolours FreeCAD's glyph image (the square, and any number beside it) in the clash
    colour, keeping its shape. Pivy cannot hand the image over as bytes, so it goes through the
    field's text form: "w h nc" and one 0xRRGGBBAA per pixel."""
    from pivy import coin
    try:
        if not node.isOfType(coin.SoImage.getClassTypeId()):
            return False
        text = node.image.get()
        parts = getattr(text, "getString", lambda: str(text))().split()
        w, h, nc = int(parts[0]), int(parts[1]), int(parts[2])
        if nc != 4 or len(parts) < 3 + w * h:
            return False
        r, g, b = _rgb(colour)
        rgb = (r << 24) | (g << 16) | (b << 8)
        out = []
        for x in parts[3:3 + w * h]:
            v = int(x, 16)
            if v == MARK:
                out.append("0x%08x" % MARK)
            else:
                out.append("0x%08x" % (rgb | (v & 0xFF)) if v & 0xFF else "0x00000000")
        node.image.set("%d %d %d %s" % (w, h, nc, " ".join(out)))
        return True
    except Exception:
        return False


painted = {}     # constraint index: "label" / "icon", the last paint(), for tests
collinear = []


def _collinear_ids(sketch):
    ""
    out = set()
    try:
        geos = sketch.Geometry
        for i, c in enumerate(sketch.Constraints):
            if c.Type != "Tangent" or c.Second is None or c.Second < 0:
                continue
            a, b = c.First, c.Second
            if 0 <= a < len(geos) and 0 <= b < len(geos) and \
                    type(geos[a]).__name__ == "LineSegment" and type(geos[b]).__name__ == "LineSegment":
                out.add(i)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:257", _fw_err)
    return out


def _swap_square(node, type_):
    """Redraws the square of FreeCAD's glyph image with another symbol, in the square's colour;
    the number beside it stays. The image's rows run bottom up."""
    from pivy import coin
    try:
        if not node.isOfType(coin.SoImage.getClassTypeId()):
            return False
        text = node.image.get()
        parts = getattr(text, "getString", lambda: str(text))().split()
        w, h, nc = int(parts[0]), int(parts[1]), int(parts[2])
        if nc != 4 or len(parts) < 3 + w * h:
            return False
        px = [int(x, 16) for x in parts[3:3 + w * h]]
        rows = [r for r in range(h) if px[r * w] & 0xFF]          # the square's rows: column 0 is filled
        if not rows:
            return False
        r0, side = rows[0], len(rows)
        if side > w or rows != list(range(r0, r0 + side)):
            return False
        colour = px[r0 * w] & 0xFFFFFF00
        image = glyph(type_, side)
        if image is None:
            return False
        for j in range(side):
            y = side - 1 - j                                       # QImage rows run top down
            for x in range(side):
                a = QtGui.QColor.fromRgba(image.pixel(x, y)).alpha()
                px[(r0 + j) * w + x] = (colour | 0xFF) if a else 0
        node.image.set("%d %d %d %s" % (w, h, nc, " ".join("0x%08x" % v for v in px)))
        return True
    except Exception:
        return False


MARK = 0x000000FF
MAX_MARKED = 400        # glyph images filled per redraw at most (big sketches keep FreeCAD's speed)
_marked_cache = {}      # FreeCAD's image text -> the same image with its symbol filled


def _fill_mark(node):
    ""


    from pivy import coin
    try:
        if not node.isOfType(coin.SoImage.getClassTypeId()):
            return False
        text = node.image.get()
        text = getattr(text, "getString", lambda: str(text))()
        done = _marked_cache.get(text)
        if done is None:
            if text in _marked_values:
                return False
            parts = text.split()
            w, h, nc = int(parts[0]), int(parts[1]), int(parts[2])
            if nc != 4 or len(parts) < 3 + w * h:
                return False
            px = [int(x, 16) for x in parts[3:3 + w * h]]
            rows = [r for r in range(h) if px[r * w] & 0xFF]      # the square's rows: column 0 is filled
            if not rows:
                return False
            r0, side = rows[0], len(rows)
            if side > w or rows != list(range(r0, r0 + side)):
                return False
            changed = False
            for j in range(r0, r0 + side):
                base = j * w
                for x in range(side):
                    if not px[base + x] & 0xFF:
                        px[base + x] = MARK
                        changed = True
            if not changed:
                return False
            done = "%d %d %d %s" % (w, h, nc, " ".join("0x%08x" % v for v in px))
            if len(_marked_cache) > 200:
                _marked_cache.clear()
                _marked_values.clear()
            _marked_cache[text] = done
            _marked_values.add(done)
        node.image.set(done)
        return True
    except Exception:
        return False


_marked_values = set()  # images already filled (a second pass leaves them)


def fill_marks(view):
    ""
    if not wanted():
        return 0
    group = _constraint_group(view)
    if group is None:
        return 0
    n = seen = 0
    for i in range(group.getNumChildren()):
        sep = group.getChild(i)
        try:
            count = sep.getNumChildren()
        except Exception:
            continue
        for k in ICON_INDEXES:
            if count > k:
                if seen >= MAX_MARKED:
                    return n
                seen += 1
                if _fill_mark(sep.getChild(k)):
                    n += 1
    return n


def symmetric_points(sketch):
    ""

    out = []
    try:
        from .. import relationspm as RP
        for i, c in enumerate(sketch.Constraints):
            if c.Type != "Symmetric" or c.Second is None or c.Third is None:
                continue
            if RP.relation_name(sketch, c) != "Symmetric":
                continue
            out.append((i, (c.Second, int(c.SecondPos))))
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:symmetric_points", _fw_err)
    return out


SYMMETRIC_OFFSET = 4    # logical pixels right of and below the point, as pointglyphs.OFFSET


def _ratio(view):
    try:
        return view.graphicsView().viewport().devicePixelRatioF()
    except Exception:
        return 1.0


def _pad(node, n):
    """n see-through pixels left of and above a glyph image (its rows run bottom up), once."""
    try:
        text = node.image.get()
        text = getattr(text, "getString", lambda: str(text))()
        parts = text.split()
        w, h, nc = int(parts[0]), int(parts[1]), int(parts[2])
        if nc != 4 or n <= 0 or w == 0 or len(parts) < 3 + w * h:
            return False
        px = parts[3:3 + w * h]
        if all(int(px[(h - 1) * w + x], 16) & 0xFF == 0 for x in range(w)) and \
                all(int(px[r * w], 16) & 0xFF == 0 for r in range(h)):
            return False              # padded already (its top row and left column are empty)
        W, H = w + n, h + n
        out = []
        for r in range(H):
            if r >= h:
                out.extend(["0x00000000"] * W)          # the rows above (top, as rows run bottom up)
            else:
                out.extend(["0x00000000"] * n + px[r * w:(r + 1) * w])
        node.image.set("%d %d %d %s" % (W, H, nc, " ".join(out)))
        return True
    except Exception:
        return False


def paint_symmetric(view, sketch):
    ""



    done = []
    if not wanted():
        return done
    group = _constraint_group(view)
    if group is None:
        return done
    try:
        placement = sketch.getGlobalPlacement()
        size = icon_size()
    except Exception:
        return done
    for i, _second in symmetric_points(sketch):
        if i >= group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            if sep.getNumChildren() < 3 or sep.getChild(0).getTypeId().getName().getString() != "SoDatumLabel":
                continue
            c = sketch.Constraints[i]
            p1 = sketch.getPoint(c.First, int(c.FirstPos))
            label = sep.getChild(0)
            if label.pnts.getNum() >= 2:
                a = label.pnts[0]
                label.pnts.set1Value(1, a[0], a[1], a[2])
            # the glyph's centre: half a square plus the offset right of and below the point
            t = sep.getChild(1)
            z = t.translation.getValue()[2]
            t.translation.setValue(p1.x, p1.y, z)
            # the square's top left corner at the point, a few pixels off it whatever the zoom
            from pivy import coin
            img = sep.getChild(2)
            if img.isOfType(coin.SoImage.getClassTypeId()):
                img.horAlignment.setValue(coin.SoImage.LEFT)
                img.vertAlignment.setValue(coin.SoImage.TOP)
                _pad(img, int(round(SYMMETRIC_OFFSET * _ratio(view))))
            done.append(i)
        except Exception as _fw_err:
            _fw_log("fwsketch/glyphs.py:paint_symmetric", _fw_err)
    return done


def paint_collinear(view, sketch):
    ""
    collinear[:] = []
    if not wanted():
        return collinear
    ids = _collinear_ids(sketch)
    if not ids:
        return collinear
    group = _constraint_group(view)
    if group is None:
        return collinear
    for i in sorted(ids):
        if not 0 <= i < group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            n = sep.getNumChildren()
        except Exception:
            continue
        for k in ICON_INDEXES:
            mine = _ids(sep.getChild(k + 1)) if n > k + 1 else set()
            if mine and mine <= ids and n > k and _swap_square(sep.getChild(k), "SW_Collinear"):
                if i not in collinear:
                    collinear.append(i)
    return collinear


patterned = []


def paint_patterned(view, sketch):
    ""
    patterned[:] = []
    if not wanted():
        return patterned
    try:
        from .polygon import pattern_group
    except Exception:
        return patterned
    ids = {i for i, c in enumerate(sketch.Constraints)
           if c.Type == "Equal" and pattern_group(c.Name) is not None}
    if not ids:
        return patterned
    group = _constraint_group(view)
    if group is None:
        return patterned
    for i in sorted(ids):
        if not 0 <= i < group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            n = sep.getNumChildren()
        except Exception:
            continue
        for k in ICON_INDEXES:
            mine = _ids(sep.getChild(k + 1)) if n > k + 1 else set()
            if mine and mine <= ids and n > k and _swap_square(sep.getChild(k), "SW_Patterned"):
                if i not in patterned:
                    patterned.append(i)
    return patterned


grouped = {}     # constraint index: group number shown on its glyph, the last paint()


def group_numbers(sketch):
    ""

    import re
    keys, out = [], {}
    for i, c in enumerate(sketch.Constraints):
        m = re.match(r"FWGroup_(C?\d+)_\d+$", c.Name or "")
        if m:
            if m.group(1) not in keys:
                keys.append(m.group(1))
            out[i] = keys.index(m.group(1)) + 1
    return out


def _number_image(node, number):
    ""

    from pivy import coin
    try:
        if not node.isOfType(coin.SoImage.getClassTypeId()):
            return False
        text = node.image.get()
        parts = getattr(text, "getString", lambda: str(text))().split()
        w, h, nc = int(parts[0]), int(parts[1]), int(parts[2])
        if nc != 4 or len(parts) < 3 + w * h:
            return False
        px = [int(x, 16) for x in parts[3:3 + w * h]]
        rows = [r for r in range(h) if px[r * w] & 0xFF]
        if not rows:
            return False
        side = len(rows)
        colour = px[rows[0] * w] & 0xFFFFFF00
        font = QtGui.QFont(QtWidgets.QApplication.font())
        font.setPixelSize(max(6, int(side * 0.75)))
        font.setBold(True)
        label = "" if number is None else str(number)
        tw = int(QtGui.QFontMetrics(font).horizontalAdvance(label)) + 2 if label else 0
        W = side + tw
        img = QtGui.QImage(W, h, QtGui.QImage.Format_ARGB32)
        img.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(img)
        p.setFont(font)
        p.setPen(QtGui.QColor((colour >> 24) & 0xFF, (colour >> 16) & 0xFF, (colour >> 8) & 0xFF))
        p.drawText(QtCore.QRectF(side + 1, 0, tw, h), int(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom), label)
        p.end()
        out = []
        for r in range(h):                    # SoImage rows run bottom up, QImage rows top down
            y = h - 1 - r
            for x in range(W):
                if x < side and x < w:
                    out.append(px[r * w + x])
                else:
                    a = QtGui.QColor.fromRgba(img.pixel(x, y)).alpha()
                    out.append((colour | a) if a else 0)
        node.image.set("%d %d %d %s" % (W, h, nc, " ".join("0x%08x" % v for v in out)))
        return True
    except Exception:
        return False


def paint_grouped(view, sketch):
    """The group number on the glyphs of the relations in a Relation Group."""
    grouped.clear()
    if not wanted():
        return grouped
    nums = group_numbers(sketch)
    if not nums:
        return grouped
    group = _constraint_group(view)
    if group is None:
        return grouped
    for i, k in sorted(nums.items()):
        if not 0 <= i < group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            n = sep.getNumChildren()
        except Exception:
            continue
        for j in ICON_INDEXES:
            mine = _ids(sep.getChild(j + 1)) if n > j + 1 else set()
            if mine and all(nums.get(m) == k for m in mine) and n > j and _number_image(sep.getChild(j), k):
                grouped[i] = k
    return grouped


named = []       # constraint indexes whose name was taken off their glyph, the last paint()


def paint_named(view, sketch):
    ""

    named[:] = []
    if not wanted():
        return named
    ids = {i for i, c in enumerate(sketch.Constraints) if c.Name and i not in grouped}
    if not ids:
        return named
    group = _constraint_group(view)
    if group is None:
        return named
    for i in sorted(ids):
        if not 0 <= i < group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            n = sep.getNumChildren()
        except Exception:
            continue
        for j in ICON_INDEXES:
            mine = _ids(sep.getChild(j + 1)) if n > j + 1 else set()
            if mine and mine <= ids and n > j and _number_image(sep.getChild(j), None):
                if i not in named:
                    named.append(i)
    return named


_SELECTION_ONLY = [False]       # set while SelectionRepaint repaints


def place_hv(view, sketch):
    ""


    if not wanted() or _SELECTION_ONLY[0]:
        # a preselection or selection repaint: FreeCAD recolours the glyphs then but does not
        # move them, and a pass over every H/V glyph cost 80 ms a hover in a 640 H/V sketch
        # (review 1119 perf4)
        return 0
    group = _constraint_group(view)
    if group is None:
        return 0
    moved = 0
    constraints = sketch.Constraints
    for i, c in enumerate(constraints):
        if c.Type not in ("Horizontal", "Vertical") or c.First < 0 or int(c.FirstPos) != 0 \
                or c.Second not in (-2000, None) or i >= group.getNumChildren():
            continue
        sep = group.getChild(i)
        try:
            node = sep.getChild(ICON_INDEXES[0] - 1)
            if not hasattr(node, "translation"):
                continue
            t = node.translation.getValue().getValue()
        except Exception:
            continue
        off = max(abs(t[0]), abs(t[1]))
        want = (0.0, -off, t[2]) if c.Type == "Horizontal" else (off, 0.0, t[2])
        if off > 0.0 and (abs(t[0] - want[0]) > 1e-9 or abs(t[1] - want[1]) > 1e-9):
            node.translation.setValue(*want)
            moved += 1
    return moved


def _packed_rgb(name, fallback):
    try:
        v = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(name, fallback)
    except Exception:
        v = fallback
    return ((v >> 24) & 255) / 255.0, ((v >> 16) & 255) / 255.0, ((v >> 8) & 255) / 255.0


def merged_points(view):
    ""




    from pivy import coin
    green = _packed_rgb("ConstrainedIcoColor", 0x00CC33FF)
    line = _packed_rgb("EditedEdgeColor", 0x0000FFFF)
    changed = 0
    for layer in range(16):
        sa = coin.SoSearchAction()
        sa.setName("PointsMaterials_%d" % layer)
        sa.setInterest(coin.SoSearchAction.ALL)
        sa.apply(view.getSceneGraph())
        paths = sa.getPaths()
        if paths.getLength() == 0:
            break
        for k in range(paths.getLength()):
            m = paths[k].getTail()
            if not hasattr(m, "diffuseColor"):
                continue
            field = m.diffuseColor
            hits = []
            for i in range(field.getNum()):
                c = field[i].getValue()
                if all(abs(c[j] - green[j]) < 0.003 for j in range(3)):
                    hits.append(i)
            if not hits:
                continue
            field.enableNotify(False)
            try:
                for i in hits:
                    field.set1Value(i, coin.SbColor(*line))
            finally:
                field.enableNotify(True)
            field.touch()
            changed += len(hits)
    return changed


def paint(view, sketch, yellow, red):
    """Puts the clash colours on the dimensions and glyphs of the clashing relations (0-based
    constraint indexes). FreeCAD's own colours come back by themselves on its next redraw."""
    from . import scene
    from .. import teardown
    painted.clear()
    if not teardown.alive(sketch) or not teardown.alive(view):
        return painted          # the sketch's document closed before this repaint ran
    try:
        paint_collinear(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:516", _fw_err)
    try:
        place_hv(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:520", _fw_err)
    try:
        paint_patterned(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:524", _fw_err)
    try:
        paint_grouped(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:528", _fw_err)
    try:
        paint_named(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:532", _fw_err)
    try:
        merged_points(view)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:merged_points", _fw_err)
    try:            # Coincident / Concentric squares (FreeCAD draws none): a Qt overlay, no Coin node
        from . import pointglyphs
        pointglyphs.update(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:pointglyphs", _fw_err)
    try:
        fill_marks(view)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:fill_marks", _fw_err)
    try:
        paint_symmetric(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:symmetric", _fw_err)
    try:            # dimdisp-1127: Display As Linear / Foreshorten reshape FreeCAD's radius and diameter labels
        from .. import dimdisplay
        dimdisplay.paint(view, sketch)
    except Exception as _fw_err:
        _fw_log("fwsketch/glyphs.py:dimdisplay", _fw_err)
    if not yellow and not red:
        return painted
    trace.note("glyphs paint %s %s" % (list(yellow), list(red)))
    group = _constraint_group(view)
    if group is None:
        return painted
    constraints = sketch.Constraints
    clash = set(yellow) | set(red)

    conflict = getattr(scene, "conflict_color", lambda: scene.CONFLICT_COLOR)()
    unsolvable = getattr(scene, "unsolvable_color", lambda: scene.UNSOLVABLE_COLOR)()
    for indexes, colour in ((yellow, conflict), (red, unsolvable)):
        for i in indexes:
            if not 0 <= i < group.getNumChildren() or i >= len(constraints):
                continue
            sep = group.getChild(i)
            try:
                n = sep.getNumChildren()
            except Exception:
                continue
            if n > LABEL_INDEX and _set_label(sep.getChild(LABEL_INDEX), colour):
                painted[i] = "label"
                continue
            for k in ICON_INDEXES:
                # fix263: FreeCAD stacks the glyphs of one entity into one image (a clashing
                # Vertical on a Horizontal line: one square standing for both); it takes the clash
                # colour as soon as one of its relations clashes, else the clash could not be seen
                # (look audit AQ1: the clashing V glyph stayed green)
                ids = _ids(sep.getChild(k + 1)) if n > k + 1 else set()
                if ids and ids & clash and _set_icon(sep.getChild(k), colour):
                    painted[i] = "icon"
    return painted


class SelectionRepaint:
    """FreeCAD repaints the constraint colours on every preselection and selection change: the
    clash colours go back on a moment later."""

    def __init__(self, again):
        self.again = again
        self._pending = False
        Gui.Selection.addObserver(self)

    def stop(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("fwsketch/glyphs.py:577", _fw_err)

    def _later(self, *_args):
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._run)

    def _run(self):
        self._pending = False
        _SELECTION_ONLY[0] = True
        try:
            self.again()
        except Exception as _fw_err:
            _fw_log("fwsketch/glyphs.py:590", _fw_err)
        finally:
            _SELECTION_ONLY[0] = False

    setPreselection = removePreselection = addSelection = removeSelection = clearSelection = _later
    setSelection = _later
