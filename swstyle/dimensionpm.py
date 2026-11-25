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
import math
import re
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, relationspm, sketchtoolpm
from .widgets import alive

Qt = QtCore.Qt
PROPERTY = "FWDimensionStyles"
FAVORITES = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DimensionFavorites"
DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
LENGTH_UNITS = (("Millimeters", "mm", 1.0), ("Centimeters", "cm", 10.0), ("Meters", "m", 1000.0),
                ("Microns", "um", 0.001), ("Inches", "in", 25.4), ("Feet", "ft", 304.8))
TOLERANCES = ("None", "Basic", "Bilateral", "Limit", "Symmetric", "MIN", "MAX")
DOCUMENT = -1
PRECISIONS = (("None", 0), (".1", 1), (".12", 2), (".123", 3), (".1234", 4), (".12345", 5),
              (".123456", 6), (".1234567", 7), (".12345678", 8))
SYMBOLS = (("Diameter", "Ø"), ("Degree", "°"), ("Plus/Minus", "±"), ("Centerline", "℄"),
           ("Square", "□"), ("Counterbore", "⌴"), ("Countersink", "⌵"), ("Depth", "↧"))
ARROWS = ("Outside", "Inside", "Smart")
DEFAULT = {"upper": False, "tolerance": "None", "plus": 0.0, "minus": 0.0, "precision": 2, "tol_precision": 2,
           "above": "", "before": "", "after": "", "below": "", "dual": False, "dual_precision": 2,
           "arrows": "Smart", "leader": "", "override": False, "unit": "mm",
           "doc_font": True, "font": "", "read_only": False}
STYLE_KEYS = ("upper", "tolerance", "plus", "minus", "precision", "tol_precision", "above", "before", "after",
              "below", "dual", "dual_precision", "arrows", "override", "unit", "doc_font", "font")


def _around(before, middle, after):
    """Text before and after the value, a space between; none inside brackets (dimparens-1121:
    "(150.00)", as the Add Parentheses button writes it)."""
    head = before + ("" if before.endswith("(") else " ") if before else ""
    tail = ("" if after.startswith(")") else " ") + after if after else ""
    return head + middle + tail


PARENS = re.compile(r"\(\s*<DIM>\s*\)")


# --------------------------------------------------------------------------- styles kept in the sketch
def styles(sketch):
    try:
        return json.loads(getattr(sketch, PROPERTY, "") or "{}")
    except Exception:
        return {}


def unit_of(st, doc=None):
    ""

    if st.get("override"):
        for _n, u, f in LENGTH_UNITS:
            if u == st.get("unit"):
                return u, f
    try:
        from . import unitspage
        return unitspage.length_unit(doc)
    except Exception:
        return "mm", 1.0


def style_of(sketch, index):
    c = sketch.Constraints[index]
    out = dict(DEFAULT)
    own = styles(sketch).get(c.Name or "", {})
    if "precision" not in own and not is_angle(c):

        try:
            from . import docstyle
            out["precision"] = int(docstyle.part_style(sketch.Document)["precision"])
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:style_of", _fw_err)
    out.update(own)
    return out


def next_name(sketch):
    used = {k.Name for k in sketch.Constraints if k.Name}
    n = 1
    while "D%d" % n in used:
        n += 1
    return "D%d" % n


def shown_name(sketch, index):
    ""
    return sketch.Constraints[index].Name or next_name(sketch)


def _named(sketch, index):
    ""
    c = sketch.Constraints[index]
    if c.Name:
        return c.Name
    name = next_name(sketch)
    sketch.renameConstraint(index, name)
    return name


def set_style(sketch, index, **values):
    name = _named(sketch, index)
    if PROPERTY not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", PROPERTY, "FreeCAD",
                           "Dimension display settings (tolerance, precision, text...)")
        try:
            sketch.setEditorMode(PROPERTY, 2)
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:107", _fw_err)
    data = styles(sketch)
    entry = data.get(name, {})
    entry.update(values)
    if entry.get("precision") == DOCUMENT:
        entry.pop("precision")      # (Document): the document's decimals, also when they change later
    # an explicit precision is kept even when it is the default's: the document's may differ
    data[name] = {k: v for k, v in entry.items() if DEFAULT.get(k) != v or k == "precision"}
    setattr(sketch, PROPERTY, json.dumps(data, sort_keys=True))


def read_only(sketch, index):
    try:
        return bool(style_of(sketch, index).get("read_only"))
    except Exception:
        return False


def is_angle(c):
    return c.Type == "Angle"


def text_of(sketch, index):
    ""
    c = sketch.Constraints[index]
    st = style_of(sketch, index)
    if is_angle(c):
        value, unit = math.degrees(c.Value), "°"
    else:
        factor = unit_of(st, sketch.Document)[1]
        value, unit = shown_value(sketch, index) / factor, ""
    p = int(st["precision"])
    tp = int(st["tol_precision"])
    main = ("%%.%df" % p) % value + unit
    prefix = {"Radius": "R", "Diameter": "Ø"}.get(c.Type, "")
    if st["leader"] == "Radius":
        prefix = "R"
    elif st["leader"] in ("Diameter", "Linear"):
        prefix = "Ø"
    t = st["tolerance"]
    if t == "Basic":
        main = "[%s%s]" % (prefix, main)
        prefix = ""
    elif t == "Bilateral":
        main += " +%s/-%s" % (("%%.%df" % tp) % st["plus"], ("%%.%df" % tp) % st["minus"])
    elif t == "Symmetric":
        main += " ±" + ("%%.%df" % tp) % st["plus"]
    elif t == "Limit":
        main = "%s-%s" % (("%%.%df" % p) % (value + st["plus"]), ("%%.%df" % p) % (value - st["minus"]))
    elif t in ("MIN", "MAX"):
        main += " " + t
    out = prefix + main
    if st["dual"] and not is_angle(c):
        dual = 1.0 if unit_of(st, sketch.Document)[0] in ("in", "ft") else 25.4     # the other unit: mm for inches
        out += " [%s]" % (("%%.%df" % int(st["dual_precision"])) % (shown_value(sketch, index) / dual))
    out = _around(st["before"], out, st["after"])
    lines = [s for s in (st["above"], out, st["below"]) if s]
    text = "\n".join(lines)
    return text.upper() if st.get("upper") else text


def styled(sketch, index):
    """True when the dimension has display settings of its own (anything off the defaults)."""
    c = sketch.Constraints[index]
    entry = styles(sketch).get(c.Name or "", {})
    return any(k in STYLE_KEYS and v != DEFAULT[k] for k, v in entry.items())


# --------------------------------------------------------------------------- on the sketch itself
class Labels(QtCore.QObject):
    ""




    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.apply)
        self.timer.start()
        self.written = {}

    def apply(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        # fix233 (look audit U3): with units hidden, FreeCAD writes every dimension at full precision

        # rewritten too, not only dimensions with settings of their own.
        plain = _hide_units()
        if not plain and not (getattr(sketch, PROPERTY, "") or "").strip("{} "):
            return
        try:
            from pivy import coin
            gdoc = Gui.ActiveDocument
            view = gdoc.ActiveView if gdoc is not None else None
            if view is None or not hasattr(view, "getSceneGraph"):
                return
            kind = coin.SoType.fromName("SoDatumLabel")
            if kind.isBad():
                return
            search = coin.SoSearchAction()
            search.setType(kind)
            search.setInterest(coin.SoSearchAction.ALL)
            search.setSearchingAll(True)
            search.apply(view.getSceneGraph())
            paths = search.getPaths()
            # fix238: read the constraints and the styles once per pass, and keep each label's text
            # for a while: a drag in a 1000-line sketch redraws every label on every move, and
            # working each text out again took ~0.3 s per move (f75: 500 ms per drag step); kept 3 s
            cons = sketch.Constraints
            count = len(cons)
            entries = styles(sketch)
            own_names = {name for name, entry in entries.items()
                         if any(key in STYLE_KEYS and v != DEFAULT[key] for key, v in entry.items())}
            now = time.time()
            cache = self.__dict__.setdefault("texts", {})
            look = (getattr(sketch, PROPERTY, "") or "", sketch.Document.Name, sketch.Name)
            if now - self.__dict__.get("texts_at", 0.0) > 3.0 or look != self.__dict__.get("texts_for"):
                cache.clear()       # a style changed (or another sketch): every text again
                self.texts_at, self.texts_for = now, look

            snap = _Snapshot(sketch, cons)

            def text_for(k):
                c = cons[k]
                key = (k, c.Name, c.Type, c.Value, c.First, c.FirstPos, c.Second, c.SecondPos)
                text = cache.get(key)
                if text is None:
                    text = cache[key] = text_of(snap, k)
                return text

            for n in range(paths.getLength()):
                path = paths[n]
                if path.getLength() < 2:
                    continue
                k = path.getIndex(path.getLength() - 2)      # the label's group sits at the constraint's index
                if k >= count or cons[k].Type not in DIMENSIONAL:
                    continue
                field = path.getTail().getField("string")
                if field is None:
                    continue
                own = (cons[k].Name or "") in own_names
                if not own:
                    if not plain or field.getNum() != 1:
                        continue
                    shown = str(field.get()).strip().strip('"')
                    if shown == self.written.get(k):
                        continue
                    m = PLAIN.match(shown)
                    if m is None:
                        continue        # a name, an expression or a format of the user's own: left as it is
                    text = text_for(k)
                    if m.group(1):
                        text = "(%s)" % text     # a driven dimension keeps its brackets
                    if shown != text:
                        field.setValue(text)
                    self.written[k] = text
                    continue
                text = " ".join(text_for(k).split("\n"))
                if field.getNum() != 1 or text not in str(field.get()):
                    field.setValue(text)
                    self.written[k] = text
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:220", _fw_err)


class _Snapshot:
    """fix238: the sketch for reading only, with its Constraints and Geometry read once (each read
    of those properties copies the whole list: 1100 constraints and 1000 lines per dimension)."""

    def __init__(self, sketch, cons):
        self._sketch = sketch
        self.Constraints = cons
        self._geometry = None
        setattr(self, PROPERTY, getattr(sketch, PROPERTY, "") or "")

    @property
    def Geometry(self):
        if self._geometry is None:
            self._geometry = self._sketch.Geometry
        return self._geometry

    def __getattr__(self, name):
        return getattr(self._sketch, name)


_labels = None

# FreeCAD's own text of a dimension with units hidden: a number, maybe R or a diameter sign before it,
# a degree sign after it, in brackets when driven
PLAIN = re.compile(r"^(\()?\s*(?:R|\u2300|\u00d8|\u00f8)?\s*-?[0-9]+(?:[.,][0-9]+)?(?:e[-+]?[0-9]+)?\s*(?:\u00b0)?\s*\)?$")


def _hide_units():
    try:
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").GetBool("HideUnits", False)
    except Exception:
        return False


# --------------------------------------------------------------------------- Arc Condition
def arc_condition(sketch, index):
    """("Center" | "Min" | "Max", circle geo, (point geo, pos)) for a dimension from a circle's
    centre or edge to a point; None for any other dimension."""
    import Part
    c = sketch.Constraints[index]
    if c.Type not in ("Distance", "DistanceX", "DistanceY"):
        return None
    geos = sketch.Geometry

    def round_(g):
        return 0 <= g < len(geos) and isinstance(geos[g], (Part.Circle, Part.ArcOfCircle))

    def line_(g):
        return (0 <= g < len(geos) and isinstance(geos[g], Part.LineSegment)) or g in (-1, -2)
    if c.FirstPos == 3 and round_(c.First) and c.Second >= -2 and c.SecondPos in (1, 2, 3):
        return "Center", c.First, (c.Second, c.SecondPos)
    if c.SecondPos == 3 and round_(c.Second) and c.FirstPos in (1, 2, 3):
        return "Center", c.Second, (c.First, c.FirstPos)
    if c.Type != "Distance":
        return None
    if c.FirstPos == 3 and round_(c.First) and c.SecondPos == 0 and line_(c.Second):
        return "Center", c.First, (c.Second, 0)
    if round_(c.Second) and c.SecondPos == 0 and c.FirstPos in (1, 2, 3):
        st = style_of(sketch, index)
        return ("Max" if st.get("arc") == "Max" else "Min"), c.Second, (c.First, c.FirstPos)
    if round_(c.First) and c.FirstPos == 0 and c.SecondPos == 0 and line_(c.Second):
        st = style_of(sketch, index)
        return ("Max" if st.get("arc") == "Max" else "Min"), c.First, (c.Second, 0)
    return None


def _partner_gap(sketch, centre, pg, pp):
    """How far the circle's centre is from the other end of the dimension (a point, or a line)."""
    if pp == 0:
        if pg in (-1, -2):
            return abs(centre.y) if pg == -1 else abs(centre.x)
        ln = sketch.Geometry[pg]
        d = ln.EndPoint - ln.StartPoint
        n = App.Vector(-d.y, d.x, 0)
        n.normalize()
        return abs((centre - ln.StartPoint).dot(n))
    return (sketch.getPoint(pg, pp) - centre).Length


def _radius(sketch, g):
    return sketch.Geometry[g].Radius


def pair_extra(sketch, index):
    """Two circles dimensioned edge to edge (Shift at both): the diameter of each one whose Arc
    Condition is Max (its far edge); the sketch keeps the near-edge distance."""
    import Part
    c = sketch.Constraints[index]
    if c.Type != "Distance" or c.FirstPos != 0 or c.SecondPos != 0:
        return 0.0
    gs = sketch.Geometry

    def round_(g):
        return 0 <= g < len(gs) and isinstance(gs[g], (Part.Circle, Part.ArcOfCircle))
    if not (round_(c.First) and round_(c.Second)):
        return 0.0
    st = style_of(sketch, index)
    return 2.0 * gs[c.First].Radius * (st.get("arc") == "Max") + 2.0 * gs[c.Second].Radius * (st.get("arc2") == "Max")


def shown_value(sketch, index):
    """The dimension's value as the page shows it (Max adds the diameter)."""
    c = sketch.Constraints[index]
    cond = arc_condition(sketch, index)
    if cond and cond[0] == "Max":
        return c.Value + 2.0 * _radius(sketch, cond[1])
    return c.Value + pair_extra(sketch, index)


def set_shown_value(sketch, index, value):
    cond = arc_condition(sketch, index)
    if cond and cond[0] == "Max":
        value -= 2.0 * _radius(sketch, cond[1])
    else:
        value -= pair_extra(sketch, index)
    sketch.setDatum(index, App.Units.Quantity("%.12g mm" % value))


def set_arc_condition(sketch, index, kind):
    """Re-makes the dimension from the centre (Center) or to the edge (Min, Max), keeping where
    the geometry is; returns the dimension's new index."""
    import Sketcher
    cond = arc_condition(sketch, index)
    if cond is None or cond[0] == kind:
        return index
    old = sketch.Constraints[index]
    circle, (pg, pp) = cond[1], cond[2]
    centre = sketch.Geometry[circle].Center
    gap = _partner_gap(sketch, centre, pg, pp)
    r = _radius(sketch, circle)
    name, driving = old.Name, old.Driving
    st = style_of(sketch, index)
    sketch.delConstraint(index)
    if kind == "Center" and pp == 0:
        new = Sketcher.Constraint("Distance", circle, 3, pg, gap)
    elif kind == "Center":
        new = Sketcher.Constraint("Distance", circle, 3, pg, pp, gap)
    elif pp == 0:
        new = Sketcher.Constraint("Distance", circle, pg, abs(gap - r))
    else:
        new = Sketcher.Constraint("Distance", pg, pp, circle, abs(gap - r))
    k = sketch.addConstraint(new)
    if not driving:
        sketch.setDriving(k, False)
    if name:
        sketch.renameConstraint(k, name)
    set_style(sketch, k, **dict(st, arc=kind if kind != "Center" else ""))
    return k


def set_leader(sketch, index, kind):
    ""
    import Sketcher
    c = sketch.Constraints[index]
    if c.Type not in ("Radius", "Diameter"):
        return index
    want = "Radius" if kind == "Radius" else "Diameter"
    if c.Type != want:
        value = c.Value * (2.0 if want == "Diameter" else 0.5)
        name, driving = c.Name, c.Driving
        st = style_of(sketch, index)
        sketch.delConstraint(index)
        index = sketch.addConstraint(Sketcher.Constraint(want, c.First, value))
        if not driving:
            sketch.setDriving(index, False)
        if name:
            sketch.renameConstraint(index, name)
        set_style(sketch, index, **st)
    set_style(sketch, index, leader=kind)
    return index


# --------------------------------------------------------------------------- favourites
def favorites():
    try:
        return json.loads(App.ParamGet(FAVORITES).GetString("Favorites", "{}") or "{}")
    except Exception:
        return {}


def save_favorites(data):
    App.ParamGet(FAVORITES).SetString("Favorites", json.dumps(data, sort_keys=True))


# --------------------------------------------------------------------------- the page
# dimglyph-1121 (look audit, Beginners 1 / 16-minute videos): the reference Dimension PropertyManager shows
# pictures, not words: five star buttons in Style, and a glyph at the left of each Tolerance/Precision,
# Primary Value and Dimension Text field (the words move to the tooltips). Our own drawn art.
_dim_glyphs = {}


def _draw_dim_glyph(key, p):
    rp = relationspm
    blue = rp._blue()
    if key in ("tolerance", "plus", "minus"):
        mark = {"tolerance": "\u00b1", "plus": "+", "minus": "\u2212"}[key]
        rp._letter(p, "1.5", 0, 15, 6.5)
        font = p.font()
        font.setPixelSize(6)
        p.setFont(font)
        p.setPen(blue)
        p.drawText(QtCore.QPointF(5, 6.5), mark + ".1")
    elif key in ("precision", "tol_precision"):
        rp._letter(p, ("\u00b1" if key == "tol_precision" else "") + ".01", 3, 6.5, 6)
        rp._pen(p, blue, 1.0)
        rp._line(p, 2, 9, 14, 9)
        rp._letter(p, "x.xx", 1, 15.5, 6.5)
    elif key == "value":
        rp._pen(p, None, 1.0)
        rp._line(p, 1.5, 9.5, 6.5, 14.5)
        rp._line(p, 9.5, 1.5, 14.5, 6.5)
        rp._pen(p, blue, 1.4)
        rp._line(p, 4, 12, 12, 4)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(12.5, 3.5), QtCore.QPointF(8.5, 4.6), QtCore.QPointF(11.4, 7.5)]))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(3.5, 12.5), QtCore.QPointF(7.5, 11.4), QtCore.QPointF(4.6, 8.5)]))
    elif key == "text":
        rp._pen(p, blue, 1.2)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QtCore.QRectF(1, 3, 6, 10), 90 * 16, 180 * 16)
        p.drawArc(QtCore.QRectF(9, 3, 6, 10), -90 * 16, 180 * 16)
        rp._letter(p, "xx", 4, 10.5, 6.5)


def _dim_glyph(parent, key, text, field=None):
    """The 20 px picture left of a Dimension PM field; the words go to the tooltip."""
    icon = _dim_glyphs.get((key, relationspm._dark()))
    if icon is None:
        icon = _dim_glyphs[(key, relationspm._dark())] = relationspm._icon(lambda p, k=key: _draw_dim_glyph(k, p))
    label = QtWidgets.QLabel(parent)
    label.setPixmap(icon.pixmap(16, 16))
    label.setFixedSize(20, 20)
    label.setAlignment(Qt.AlignCenter)
    label.setToolTip(text)
    label.setAccessibleName(text)
    label.setProperty("fw_dim_glyph", key)
    if field is not None:
        field.setAccessibleName(text)
    return label


def _dim_spacer(parent):
    """An empty glyph column, so a field with no picture (the name) lines up with the others."""
    label = QtWidgets.QLabel(parent)
    label.setFixedSize(20, 20)
    label.setProperty("fw_dim_glyph", "")
    return label


def _fav_glyph(button, key):
    """Style: five star buttons (our drawn stars); the word stays the button's text and tooltip."""
    try:
        from . import holespec
        button.setIcon(holespec._favorite_icon("Defaults" if key == "Default" else key))
        button.setIconSize(QtCore.QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setProperty("fw_fav_icon", key)
    except Exception as _fw_err:
        _fw_log("dimensionpm.py:_fav_glyph", _fw_err)


class DimensionPage(sketchtoolpm.ToolPage):
    TITLE = "Dimension"
    ICON = "LAYOUT_SMART_DIM"
    PIXMAP = "Sketcher_Dimension"
    TRANSACTION = "Edit Dimension"

    def __init__(self, sketch, index, parent=None):
        self.index = index
        self.cname = sketch.Constraints[index].Name
        self._filling = True
        super().__init__(sketch, parent)
        self.setObjectName("SWRelationsPM")
        self._filling = False
        self.observer = _PageObserver(self)
        Gui.Selection.addObserver(self.observer)

    # ---------------------------------------------------------------- build
    def _tab_group(self, holder, title):
        g = relationspm.Group(title, holder)
        holder.layout().addWidget(g)
        return g

    def build(self):
        s, i = self.sketch, self.index
        c = s.Constraints[i]
        st = style_of(s, i)
        self.tabs = QtWidgets.QTabBar(self.body)
        self.tabs.setObjectName("SWDimensionTabs")
        for t in ("Value", "Leaders", "Other"):
            self.tabs.addTab(t)
        self.tabs.setExpanding(False)
        self.column.addWidget(self.tabs)
        self.pages = []
        for _t in range(3):
            w = QtWidgets.QWidget(self.body)
            lay = QtWidgets.QVBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            self.column.addWidget(w)
            self.pages.append(w)
        self.tabs.currentChanged.connect(self._tab)
        value, leaders, other = self.pages
        self.preview = QtWidgets.QLabel("", self.body)
        self.preview.setObjectName("SWDimensionPreview")
        self.preview.setContentsMargins(10, 4, 8, 4)
        self.column.insertWidget(self.column.indexOf(self.tabs), self.preview)
        self.preview.hide()

        # ---- Value: Favorites
        g = self._tab_group(value, "Style")
        self.favorite = QtWidgets.QComboBox(g.body)
        self.favorite.setObjectName("SWDimensionFavorite")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        row.addStretch(1)       # dimstyle-1121: the five star buttons sit centred over the list (videos)
        self.fav_buttons = {}
        for key, tip in (("Default", "Apply the default attributes to selected dimensions"),
                         ("Add", "Add or Update a Favorite"), ("Delete", "Delete a Favorite"),
                         ("Save", "Save a Favorite"), ("Load", "Load Favorites")):
            b = QtWidgets.QToolButton(g.body)
            b.setText(key)
            b.setToolTip(tip)
            b.setObjectName("SWDimensionFav" + key)
            _fav_glyph(b, key)
            b.clicked.connect(lambda checked=False, k=key: self._favorite_button(k))
            row.addWidget(b)
            self.fav_buttons[key] = b
        row.addStretch(1)
        g.content.addLayout(row)
        g.content.addWidget(self.favorite)
        self._fill_favorites()
        self.favorite.activated.connect(self._favorite_picked)

        # ---- Value: Tolerance/Precision
        g = self._tab_group(value, "Tolerance/Precision")
        form = QtWidgets.QFormLayout()
        self.tolerance = QtWidgets.QComboBox(g.body)
        self.tolerance.setObjectName("SWDimensionTolerance")
        self.tolerance.addItems(TOLERANCES)
        self.tolerance.setCurrentText(st["tolerance"])
        form.addRow(_dim_glyph(g.body, "tolerance", "Tolerance Type", self.tolerance), self.tolerance)
        self.plus = self._spin(g, st["plus"], 0.0, 1e4)
        self.plus.setObjectName("SWDimensionMaxVariation")
        form.addRow(_dim_glyph(g.body, "plus", "Maximum Variation", self.plus), self.plus)
        self.minus = self._spin(g, st["minus"], 0.0, 1e4)
        self.minus.setObjectName("SWDimensionMinVariation")
        form.addRow(_dim_glyph(g.body, "minus", "Minimum Variation", self.minus), self.minus)
        self.precision = self._precision(g, st["precision"], "SWDimensionPrecision", document=True)
        form.addRow(_dim_glyph(g.body, "precision", "Unit Precision", self.precision), self.precision)
        self.tol_precision = self._precision(g, st["tol_precision"], "SWDimensionTolPrecision")
        form.addRow(_dim_glyph(g.body, "tol_precision", "Tolerance Precision", self.tol_precision), self.tol_precision)
        g.content.addLayout(form)

        # ---- Value: Primary Value
        g = self._tab_group(value, "Primary Value")
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit("%s@%s" % (shown_name(s, i), s.Label), g.body)
        self.name.setObjectName("SWDimensionName")
        self.name.setToolTip("Name")
        form.addRow(_dim_spacer(g.body), self.name)
        self.value = QtWidgets.QDoubleSpinBox(g.body)
        self.value.setObjectName("SWDimensionValue")
        self.value.setRange(-1e7, 1e7)
        self.value.setDecimals(6 if not is_angle(c) else 4)
        self.value.setKeyboardTracking(False)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.value, 1)

        # This Configuration, All Configurations, Specify Configurations...
        self.config_scope = None
        self.config_button = QtWidgets.QToolButton(g.body)
        self.config_button.setObjectName("SWDimensionConfigurations")
        self.config_button.setText("This Configuration")
        self.config_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self.config_button)
        for key, label in (("this", "This Configuration"), ("all", "All Configurations"),
                           ("specify", "Specify Configurations...")):
            menu.addAction(label).triggered.connect(lambda _c=False, k=key: self._pick_scope(k))
        self.config_button.setMenu(menu)
        row.addWidget(self.config_button)
        try:
            from . import configs
            several = configs.several(s.Document)
        except Exception:
            several = False
        self.config_button.setVisible(several)
        if several:
            self.config_scope = "this"
        form.addRow(_dim_glyph(g.body, "value", "Value", self.value), row)

        self.equation = QtWidgets.QLineEdit(g.body)
        self.equation.setObjectName("SWDimensionEquation")
        self.equation.setPlaceholderText('= "Width" * 2')
        self.equation.setToolTip("An equation drives this dimension (Tools > Equations)")
        self.equation.editingFinished.connect(self._equation)
        form.addRow(_dim_spacer(g.body), self.equation)
        g.content.addLayout(form)

        # ---- Value: Dimension Text
        g = self._tab_group(value, "Dimension Text")
        self.texts = {}
        form = QtWidgets.QFormLayout()
        for key, label in (("above", "Above"), ("before", "Before <DIM>"), ("after", "After <DIM>"),
                           ("below", "Below")):
            e = QtWidgets.QLineEdit(st[key], g.body)
            e.setObjectName("SWDimensionText" + label.split()[0])
            e.hide()            # the four parts of the one box below
            self.texts[key] = e

        # text above and below, text on its line goes before and after (fix233, look audit U4)
        self.text_box = QtWidgets.QPlainTextEdit(g.body)
        self.text_box.setObjectName("SWDimensionTextBox")
        self.text_box.setTabChangesFocus(True)
        self.text_box.setFixedHeight(int(self.text_box.fontMetrics().lineSpacing() * 3.6))
        self._compose_text()
        self.text_box.textChanged.connect(self._text_typed)
        text_row = QtWidgets.QHBoxLayout()
        # dimparens-1121 (2024 "Tutorial For" video): the picture left of the box is the Add
        # Parentheses button
        glyph = _dim_glyph(g.body, "text", "Add Parentheses", self.text_box)
        self.parens = QtWidgets.QToolButton(g.body)
        self.parens.setObjectName("SWDimensionParentheses")
        self.parens.setCheckable(True)
        self.parens.setIcon(QtGui.QIcon(glyph.pixmap()))
        self.parens.setIconSize(QtCore.QSize(16, 16))
        self.parens.setFixedSize(22, 22)
        self.parens.setToolTip("Add Parentheses")
        self.parens.setProperty("fw_dim_glyph", "text")
        self.parens.setProperty("swToggle", True)
        glyph.deleteLater()
        self.text_box.setAccessibleName("Dimension Text")
        self.parens.toggled.connect(self._parentheses)
        self.text_box.textChanged.connect(self._sync_parens)
        self._sync_parens()
        text_row.addWidget(self.parens, 0, Qt.AlignTop)
        text_row.addWidget(self.text_box, 1)
        g.content.addLayout(text_row)
        self.upper = QtWidgets.QCheckBox("All uppercase", g.body)
        self.upper.setObjectName("SWDimensionUppercase")
        self.upper.setChecked(bool(st.get("upper")))
        self.upper.toggled.connect(self._changed)
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(2)
        for n, (tip, sym) in enumerate(SYMBOLS):
            b = QtWidgets.QToolButton(g.body)
            b.setText(sym)
            b.setToolTip(tip)
            b.setObjectName("SWDimensionSymbol" + tip.replace("/", ""))
            b.clicked.connect(lambda checked=False, t=sym: self._symbol(t))
            grid.addWidget(b, n // 4, n % 4)
        grid.setColumnStretch(4, 1)
        g.content.addLayout(grid)
        g.content.addWidget(self.upper)

        # ---- Value: Dual Dimension
        g = self._tab_group(value, "Dual Dimension")

        self.dual = QtWidgets.QCheckBox("Dual Dimension", g.header)
        self.dual.setObjectName("SWDimensionDual")
        self.dual.setChecked(st["dual"])
        f = self.dual.font()
        f.setBold(True)
        self.dual.setFont(f)
        g.header.layout().insertWidget(0, self.dual, 1)
        g.title.hide()
        form = QtWidgets.QFormLayout()
        self.dual_precision = self._precision(g, st["dual_precision"], "SWDimensionDualPrecision")
        form.addRow("Dual Precision (in)", self.dual_precision)
        g.content.addLayout(form)

        # ---- Leaders: Witness/Leader Display
        g = self._tab_group(leaders, "Witness/Leader Display")
        self.arrows = {}
        row = QtWidgets.QHBoxLayout()
        for key in ARROWS:
            r = QtWidgets.QRadioButton(key, g.body)
            r.setObjectName("SWDimensionArrows" + key)
            r.setChecked(st["arrows"] == key)
            r.toggled.connect(self._changed)
            row.addWidget(r)
            self.arrows[key] = r
        row.addStretch(1)
        g.content.addLayout(row)
        self.leaders = {}
        round_ = c.Type in ("Radius", "Diameter")
        row = QtWidgets.QHBoxLayout()
        shown = st["leader"] or c.Type
        for key in ("Radius", "Diameter", "Linear"):
            b = QtWidgets.QRadioButton(key, g.body)
            b.setObjectName("SWDimensionLeader" + key)
            b.setChecked(round_ and shown == key)
            b.setVisible(round_)
            b.clicked.connect(lambda checked=False, k=key: self._leader(k))
            row.addWidget(b)
            self.leaders[key] = b
        row.addStretch(1)
        g.content.addLayout(row)

        # ---- Leaders: Arc Condition
        g = self._tab_group(leaders, "Arc Condition")
        self.arc_group = g
        self.arcs = {}
        row = QtWidgets.QHBoxLayout()
        for key in ("Center", "Min", "Max"):
            b = QtWidgets.QRadioButton(key, g.body)
            b.setObjectName("SWDimensionArc" + key)
            b.clicked.connect(lambda checked=False, k=key: self._arc(k))
            row.addWidget(b)
            self.arcs[key] = b
        row.addStretch(1)
        g.content.addLayout(row)

        # ---- Other: Override Units
        g = self._tab_group(other, "Override Units")
        self.override = QtWidgets.QCheckBox("Override Units", g.body)
        self.override.setObjectName("SWDimensionOverrideUnits")
        self.override.setChecked(st["override"])
        g.content.addWidget(self.override)
        self.unit = QtWidgets.QComboBox(g.body)
        self.unit.setObjectName("SWDimensionUnit")
        for label, u, _f in LENGTH_UNITS:
            self.unit.addItem(label, u)
        self.unit.setCurrentIndex(max(0, self.unit.findData(unit_of(st, self.sketch.Document)[0])))
        g.content.addWidget(self.unit)

        # ---- Other: Text Fonts
        g = self._tab_group(other, "Text Fonts")
        self.doc_font = QtWidgets.QCheckBox("Use document font", g.body)
        self.doc_font.setObjectName("SWDimensionDocFont")
        self.doc_font.setChecked(st["doc_font"])
        g.content.addWidget(self.doc_font)
        self.font_button = QtWidgets.QPushButton("Font...", g.body)
        self.font_button.setObjectName("SWDimensionFont")
        self.font_button.clicked.connect(self._font)
        g.content.addWidget(self.font_button)

        # ---- Other: Options
        g = self._tab_group(other, "Options")
        self.read_only = QtWidgets.QCheckBox("Read only", g.body)
        self.read_only.setObjectName("SWDimensionReadOnly")
        self.read_only.setChecked(st["read_only"])
        g.content.addWidget(self.read_only)
        self.driven = QtWidgets.QCheckBox("Driven", g.body)
        self.driven.setObjectName("SWDimensionDriven")
        g.content.addWidget(self.driven)

        for w in (self.tolerance, self.unit, self.precision, self.tol_precision, self.dual_precision):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.plus, self.minus):
            w.valueChanged.connect(self._changed)
        for e in self.texts.values():
            e.editingFinished.connect(self._changed)
        for w in (self.dual, self.override, self.doc_font):
            w.toggled.connect(self._changed)
        self.read_only.toggled.connect(self._read_only)
        self.driven.toggled.connect(self._driven)
        self.value.valueChanged.connect(self._value)
        self.name.editingFinished.connect(self._rename)
        self._tab(0)
        self.refresh()

    def _spin(self, g, value, lo, hi):
        b = QtWidgets.QDoubleSpinBox(g.body)
        b.setRange(lo, hi)
        b.setDecimals(4)
        b.setSuffix(" mm")
        b.setValue(value)
        b.setKeyboardTracking(False)
        return b

    def _precision(self, g, value, name, document=False):
        b = QtWidgets.QComboBox(g.body)
        b.setObjectName(name)
        if document:

            try:
                from . import docstyle
                n = int(docstyle.part_style(self.sketch.Document)["precision"])
            except Exception:
                n = 2
            b.addItem("%s (Document)" % dict((v, k) for k, v in PRECISIONS).get(n, ".12"), DOCUMENT)
        for label, n in PRECISIONS:
            b.addItem(label, n)
        if document and not self._own_precision():
            b.setCurrentIndex(0)
        else:
            b.setCurrentIndex(max(0, b.findData(int(value))))
        return b

    def _own_precision(self):
        try:
            c = self.sketch.Constraints[self.index]
            return "precision" in styles(self.sketch).get(c.Name or "", {})
        except Exception:
            return False

    def _tab(self, n):
        for k, w in enumerate(self.pages):
            w.setVisible(k == n)

    # ---------------------------------------------------------------- fill
    def refresh(self):
        """The page shows the dimension as the sketch has it now."""
        s, i = self.sketch, self.index
        if i >= len(s.Constraints):
            return
        c = s.Constraints[i]
        st = style_of(s, i)
        self._filling = True
        try:
            angle = is_angle(c)
            unit, factor = unit_of(st, s.Document)
            unit = "°" if angle else unit
            self.value.setSuffix(" " + unit if not angle else "°")
            v = math.degrees(c.Value) if angle else shown_value(s, i) / factor
            if abs(self.value.value() - v) > 1e-9:
                self.value.setValue(v)
            eq = self._expression()
            self.value.setEnabled(not st["read_only"] and c.Driving and not eq)
            self.value.setToolTip("Read only" if st["read_only"] else
                                  ("A driven dimension shows the size; it does not set it" if not c.Driving else
                                   ("Σ An equation drives this dimension" if eq else "")))
            if hasattr(self, "equation") and not self.equation.hasFocus():
                self.equation.setText(self._shown_equation(eq) if eq else "")
                self.equation.setEnabled(not st["read_only"] and c.Driving)
            self.name.setText("%s@%s" % (shown_name(s, i), s.Label))
            self.driven.setChecked(not c.Driving)
            tol = self.tolerance.currentText()
            self.plus.setEnabled(tol in ("Bilateral", "Limit", "Symmetric"))
            self.minus.setEnabled(tol in ("Bilateral", "Limit"))
            self.tol_precision.setEnabled(tol in ("Bilateral", "Limit", "Symmetric"))
            self.dual_precision.setEnabled(self.dual.isChecked() and not angle)
            self.dual.setEnabled(not angle)
            self.unit.setEnabled(self.override.isChecked() and not angle)
            self.override.setEnabled(not angle)
            self.font_button.setEnabled(not self.doc_font.isChecked())
            cond = arc_condition(s, i)
            for key, b in self.arcs.items():
                b.setChecked(bool(cond) and cond[0] == key)
                b.setEnabled(bool(cond))
            self.arc_group.setVisible(bool(cond))
            round_ = c.Type in ("Radius", "Diameter")
            shown = st["leader"] or c.Type
            for key, b in self.leaders.items():
                b.setVisible(round_)
                b.setChecked(round_ and shown == key)
            self.preview.setText(text_of(s, i))
        finally:
            self._filling = False

    def _fill_favorites(self):
        self.favorite.blockSignals(True)
        self.favorite.clear()
        self.favorite.addItem("<None>")
        for name in sorted(favorites()):
            self.favorite.addItem(name)
        self.favorite.blockSignals(False)

    # ---------------------------------------------------------------- edits
    def _edit(self, work):
        if self._filling:
            return
        self.begin()
        try:
            work()
            self.sketch.solve()
            sketchtoolpm._refresh(self.sketch)
            if _labels is not None:
                QtCore.QTimer.singleShot(50, _labels.apply)
            self.show_note("")
        except Exception as error:
            self.show_note(str(error), True)
        self.cname = self.sketch.Constraints[self.index].Name
        self._keep_while_dimensioning()
        self.refresh()

    def _keep_while_dimensioning(self):
        """Smart Dimension still running, between dimensions (dimension review 11-19): the edit is
        kept now as its own undo step. The page's step replaced the tool's (one open step per
        document), and the tool's next pick aborts the step it believes is its own."""
        tool = _active_tool() if _smart_dimension_running() else None
        if tool is None or not self._open or getattr(tool, "indexes", None):
            return
        try:
            self.doc.commitTransaction()
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:keep", _fw_err)
            return
        self._open = False
        self._snapshot = None
        tool.open = False       # its step is gone; it opens a fresh one on its next pick

    def _style_now(self):
        return {"upper": self.upper.isChecked(),
                "tolerance": self.tolerance.currentText(), "plus": self.plus.value(), "minus": self.minus.value(),
                "precision": self.precision.currentData(), "tol_precision": self.tol_precision.currentData(),
                "above": self.texts["above"].text(), "before": self.texts["before"].text(),
                "after": self.texts["after"].text(), "below": self.texts["below"].text(),
                "dual": self.dual.isChecked(), "dual_precision": self.dual_precision.currentData(),
                "arrows": next((k for k, r in self.arrows.items() if r.isChecked()), "Smart"),
                "override": self.override.isChecked(), "unit": self.unit.currentData(),
                "doc_font": self.doc_font.isChecked(),
                "font": style_of(self.sketch, self.index).get("font", "")}

    def _changed(self, *args):
        self._edit(lambda: set_style(self.sketch, self.index, **self._style_now()))

    def _value(self, v):
        c = self.sketch.Constraints[self.index]
        st = style_of(self.sketch, self.index)
        if is_angle(c):
            work = lambda: self.sketch.setDatum(self.index, App.Units.Quantity("%.12g deg" % v))
        else:
            factor = unit_of(st, self.sketch.Document)[1]
            work = lambda: set_shown_value(self.sketch, self.index, v * factor)
        if self.config_scope is not None:
            # 2+ configurations: the value goes to the configurations picked on the button
            old = c.Value
            angle = is_angle(c)

            def work(base=work):
                from . import configs
                before = App.Units.Quantity("%.12g %s" % (math.degrees(old) if angle else old, "deg" if angle else "mm"))
                base()
                name = _named(self.sketch, self.index)
                now = self.sketch.Constraints[self.index].Value
                configs.set_value(self.sketch, "Constraints.%s" % name,
                                  App.Units.Quantity("%.12g %s" % (math.degrees(now) if angle else now, "deg" if angle else "mm")),
                                  self.config_scope, old=before)
        self._edit(work)

    def _paths(self):
        c = self.sketch.Constraints[self.index]
        out = [".Constraints[%d]" % self.index, "Constraints[%d]" % self.index]
        if c.Name:
            out = [".Constraints.%s" % c.Name, "Constraints.%s" % c.Name] + out
        return out

    def _expression(self):
        """The equation on the dimension ("" for none, and for the configuration table's own link)."""
        engine = dict(getattr(self.sketch, "ExpressionEngine", []) or [])
        for p in self._paths():
            if p in engine:
                return "" if self._table_link(engine[p]) else engine[p]
        return ""

    def _table_link(self, expr):
        try:
            from . import configmanager
            t = configmanager.table(self.sketch.Document)
            return t is not None and re.match(r"^\s*%s\.\w+\s*$" % re.escape(t.sheet.Name), expr or "") is not None
        except Exception:
            return False

    def _shown_equation(self, expr):
        try:
            from . import equations
            return "= " + equations.to_sw(self.sketch.Document, expr, owner=self.sketch)
        except Exception:
            return "= " + expr

    def _equation(self):
        text = self.equation.text().strip()
        old = self._expression()
        if text == (self._shown_equation(old) if old else ""):
            return
        right = text.lstrip("=").strip()

        def work():
            from . import equations
            engine = dict(getattr(self.sketch, "ExpressionEngine", []) or [])
            for p in self._paths():
                if p in engine:
                    self.sketch.setExpression(p, None)
            self.sketch.Document.recompute()
            name = _named(self.sketch, self.index)
            if right:
                try:
                    equations.accept_expression(self.sketch.Document, self.sketch, ".Constraints.%s" % name,
                                                equations.to_freecad(self.sketch.Document, right,
                                                                     target=(self.sketch, ".Constraints.%s" % name)), name)
                except ValueError:
                    for p, e in engine.items():
                        if p in self._paths():
                            self.sketch.setExpression(p, e)
                    self.sketch.Document.recompute()
                    raise
            else:
                # the dimension goes back to its configurations, when it has them
                try:
                    from . import configs, configmanager
                    t = configmanager.table(self.sketch.Document)
                    alias = configs._alias_for(self.sketch, "Constraints.%s" % name)
                    if t is not None and configs.column_of(t, alias) is not None:
                        self.sketch.setExpression(".Constraints.%s" % name, "%s.%s" % (t.sheet.Name, alias))
                except Exception as _fw_err:
                    _fw_log("dimensionpm.py:823", _fw_err)
            self.sketch.Document.recompute()
        self._edit(work)

    def _pick_scope(self, key):
        labels = {"this": "This Configuration", "all": "All Configurations"}
        if key in labels:
            self.config_scope = key
            self.config_button.setText(labels[key])
            return
        try:
            from . import configs

            def chosen(names):
                self.config_scope = list(names)
                self.config_button.setText("Specify Configurations")
                self.config_button.setToolTip("Specify Configurations: %s" % ", ".join(names))
            configs.specify(self.sketch.Document, chosen)
        except Exception as error:
            self.show_note(str(error), True)

    def _rename(self):
        text = self.name.text().split("@")[0].strip()
        c = self.sketch.Constraints[self.index]
        if not text or text == c.Name:
            return
        old = c.Name

        def work():
            data = styles(self.sketch)
            self.sketch.renameConstraint(self.index, text)
            if old and old in data:
                data[text] = data.pop(old)
                setattr(self.sketch, PROPERTY, json.dumps(data, sort_keys=True))
        self._edit(work)

    def _driven(self, on):
        sk = self.sketch
        try:
            sound = not (sk.RedundantConstraints or sk.ConflictingConstraints)
        except Exception:
            sound = False
        self._edit(lambda: sk.setDriving(self.index, not on))
        try:
            over = not on and sound and bool(sk.RedundantConstraints or sk.ConflictingConstraints)
        except Exception:
            over = False
        if over:

            # (dimension review 11-19, owner call 1). Tick Driven again to take it back.
            self.show_note("This dimension over-defines the sketch: tick Driven to make it driven again.", True)
            try:
                Gui.getMainWindow().showMessage("Over Defined", 5000)
            except Exception as _fw_err:
                _fw_log("dimensionpm.py:driven", _fw_err)

    def _read_only(self, on):
        self._edit(lambda: set_style(self.sketch, self.index, read_only=bool(on)))

    def _symbol(self, sym):
        box = getattr(self, "text_box", None)
        if box is not None:
            box.insertPlainText(sym)
            return
        e = self.texts["after"]
        for w in self.texts.values():
            if w.hasFocus():
                e = w
        e.insert(sym)
        self._changed()

    def _compose_text(self):
        box = getattr(self, "text_box", None)
        if box is None:
            return
        t = {k: e.text() for k, e in self.texts.items()}
        lines = [x for x in (t["above"],) if x]
        lines.append(_around(t["before"], "<DIM>", t["after"]))
        if t["below"]:
            lines.append(t["below"])
        text = "\n".join(lines)
        if box.toPlainText() != text:
            box.blockSignals(True)
            box.setPlainText(text)
            box.blockSignals(False)
        self._sync_parens()

    def _sync_parens(self):
        """Add Parentheses stays pressed while the text has (<DIM>)."""
        b = getattr(self, "parens", None)
        if b is not None and alive(b):
            b.blockSignals(True)
            b.setChecked(bool(PARENS.search(self.text_box.toPlainText())))
            b.blockSignals(False)

    def _parentheses(self, on):
        """Add Parentheses (dimparens-1121): brackets round <DIM> in the text, so the dimension reads
        (150.00); pressed again, they go."""
        text = self.text_box.toPlainText()
        if on and not PARENS.search(text):
            text = text.replace("<DIM>", "(<DIM>)", 1) if "<DIM>" in text else "(<DIM>)" + text
        elif not on:
            text = PARENS.sub("<DIM>", text, 1)
        self.text_box.setPlainText(text)

    def _text_typed(self):
        """The one box into its four parts; the dimension follows at once."""
        if self._filling:
            return
        text = self.text_box.toPlainText()
        lines = text.split("\n")
        at = next((n for n, x in enumerate(lines) if "<DIM>" in x), None)
        if at is None:
            parts = {"above": "", "before": "", "after": text.strip(), "below": ""}
        else:
            before, _, after = lines[at].partition("<DIM>")
            parts = {"above": "\n".join(lines[:at]).strip(), "before": before.strip(), "after": after.strip(),
                     "below": "\n".join(lines[at + 1:]).strip()}
        for k, v in parts.items():
            self.texts[k].setText(v)
        self._changed()

    def _leader(self, key):
        def work():
            self.index = set_leader(self.sketch, self.index, key)
        self._edit(work)

    def _arc(self, key):
        def work():
            self.index = set_arc_condition(self.sketch, self.index, key)
        self._edit(work)

    def _font(self):
        font, ok = QtWidgets.QFontDialog.getFont(QtGui.QFont(style_of(self.sketch, self.index).get("font") or
                                                             self.font().family()), self, "Font")
        if ok:
            self._edit(lambda: set_style(self.sketch, self.index, font=font.family()))

    # ---------------------------------------------------------------- favourites
    def _favorite_picked(self, n):
        name = self.favorite.itemText(n)
        fav = favorites().get(name)
        if fav:
            self._apply_style(fav)

    def _apply_style(self, st):
        self._edit(lambda: set_style(self.sketch, self.index, **{k: st.get(k, DEFAULT[k]) for k in STYLE_KEYS}))
        self._load_widgets()

    def _load_widgets(self):
        st = style_of(self.sketch, self.index)
        self._filling = True
        try:
            self.tolerance.setCurrentText(st["tolerance"])
            self.plus.setValue(st["plus"])
            self.minus.setValue(st["minus"])
            for box, key in ((self.precision, "precision"), (self.tol_precision, "tol_precision"),
                             (self.dual_precision, "dual_precision")):
                if box is self.precision and not self._own_precision():
                    box.setCurrentIndex(0)
                    continue
                box.setCurrentIndex(max(0, box.findData(int(st[key]))))
            for key, e in self.texts.items():
                e.setText(st[key])
            self._compose_text()
            self.upper.setChecked(bool(st.get("upper")))
            self.dual.setChecked(st["dual"])
            for key, r in self.arrows.items():
                r.setChecked(st["arrows"] == key)
            self.override.setChecked(st["override"])
            self.unit.setCurrentIndex(max(0, self.unit.findData(unit_of(st, self.sketch.Document)[0])))
            self.doc_font.setChecked(st["doc_font"])
        finally:
            self._filling = False
        self.refresh()

    def _favorite_button(self, key):
        data = favorites()
        if key == "Default":
            self._apply_style(DEFAULT)
            self.favorite.setCurrentIndex(0)
        elif key == "Add":
            current = self.favorite.currentText()
            name, ok = QtWidgets.QInputDialog.getText(self, "Add or Update a Favorite", "New Favorite name:",
                                                      text="" if current == "<None>" else current)
            if ok and name.strip():
                data[name.strip()] = {k: v for k, v in style_of(self.sketch, self.index).items() if k in STYLE_KEYS}
                save_favorites(data)
                self._fill_favorites()
                self.favorite.setCurrentText(name.strip())
        elif key == "Delete":
            name = self.favorite.currentText()
            if name in data:
                del data[name]
                save_favorites(data)
                self._fill_favorites()
        elif key == "Save":
            name = self.favorite.currentText()
            if name not in data:
                self.show_note("Pick a favorite to save.", True)
                return
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save a Favorite", name + ".fwfav",
                                                             "Favorites (*.fwfav)")
            if path:
                with open(path, "w") as f:
                    json.dump({name: data[name]}, f, indent=1)
        elif key == "Load":
            paths, _f = QtWidgets.QFileDialog.getOpenFileNames(self, "Load Favorites", "", "Favorites (*.fwfav)")
            for path in paths:
                try:
                    with open(path) as f:
                        data.update(json.load(f))
                except Exception as error:
                    self.show_note("Could not load %s: %s" % (path, error), True)
            save_favorites(data)
            self._fill_favorites()

    # ---------------------------------------------------------------- picks
    def selection_changed(self):
        ""

        if not alive(self):
            return
        k = picked_dimension(self.sketch)
        if k == self.index:
            return
        if k is not None:
            sketchtoolpm.ToolPage.accept(self)
            QtCore.QTimer.singleShot(0, lambda s=self.sketch, k=k: show(s, k))
        elif not _smart_dimension_running():
            sketchtoolpm.ToolPage.accept(self)

    def accept(self):

        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:983", _fw_err)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:987", _fw_err)
        sketchtoolpm.ToolPage.accept(self)

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("dimensionpm.py:994", _fw_err)


class _PageObserver:
    def __init__(self, page):
        self.page = page

    def _soon(self):
        page = self.page
        if page is not None and alive(page):
            QtCore.QTimer.singleShot(0, page.selection_changed)

    def addSelection(self, doc, obj, sub, pnt):
        self._soon()

    def removeSelection(self, doc, obj, sub):
        self._soon()

    def clearSelection(self, doc):
        self._soon()


# --------------------------------------------------------------------------- opening
def picked_dimension(sketch):
    """The index of the one dimension picked in the sketch (and nothing else), else None."""
    subs = relationspm.picked_subs(sketch)
    if len(subs) != 1 or not subs[0].startswith("Constraint"):
        return None
    try:
        k = int(subs[0][len("Constraint"):]) - 1
        return k if sketch.Constraints[k].Type in DIMENSIONAL else None
    except Exception:
        return None


def current():
    page = sketchtoolpm.current()
    return page if isinstance(page, DimensionPage) and alive(page) else None


def show(sketch, index):
    page = current()
    if page is not None and page.sketch is sketch and page.index == index:
        return page
    if contextbar.sketch_in_edit() is not sketch:
        return None
    page = DimensionPage(sketch, index)
    return page if sketchtoolpm.open_page(page) else None


def _smart_dimension_running():
    try:
        from .fwsketch import toolbase, dimension
        return isinstance(toolbase.active(), dimension.DimensionTool)
    except Exception:
        return False


class _Opener(QtCore.QObject):
    ""


    def __init__(self):
        super().__init__()
        self.tool = None
        self.placed = 0
        self.pending = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            self.tool, self.pending = None, None
            return
        if QtWidgets.QApplication.activeModalWidget() is not None or QtWidgets.QApplication.activePopupWidget():
            return
        tool = _active_tool() if _smart_dimension_running() else None
        if tool is not None:
            n = len(getattr(tool, "placed", []))
            if tool is not self.tool:
                self.tool, self.placed = tool, n
            elif n > self.placed:
                self.placed = n
                k = len(sketch.Constraints) - 1
                if k >= 0 and sketch.Constraints[k].Type in DIMENSIONAL:
                    self.pending = (sketch, k)
        else:
            self.tool = None
        other = sketchtoolpm.current()
        if other is not None and not isinstance(other, DimensionPage):
            return
        if self.pending is not None:
            placing = tool is not None and bool(getattr(tool, "indexes", None)) and getattr(tool, "open", False)
            if not placing:
                s, k = self.pending
                self.pending = None
                if s is sketch and k < len(sketch.Constraints):
                    show(sketch, k)
            return
        if tool is not None:
            return
        k = picked_dimension(sketch)
        if k is not None and other is None:
            show(sketch, k)


def _active_tool():
    try:
        from .fwsketch import toolbase
        return toolbase.active()
    except Exception:
        return None


_opener = None


def register():
    global _opener, _labels
    if _labels is None:
        try:
            _labels = Labels()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: dimension labels: %s\n" % error)
    if _opener is None:
        try:
            _opener = _Opener()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Dimension PropertyManager: %s\n" % error)
