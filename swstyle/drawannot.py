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

from . import drawings as D
from . import drawviews as DV
from . import drawlive as DL

V = App.Vector
CENTER_STYLE = 4      # TechDraw line style: dash-dot (center line)
PHANTOM_STYLE = 5     # TechDraw line style: dash-dot-dot (phantom: datum plane traces)
THIN_WEIGHT = 0.18


# --------------------------------------------------------------------------- view geometry

def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def edges(view):
    out = []
    i = 0
    while True:
        try:
            out.append((i, view.getEdgeByIndex(i)))
        except Exception:
            return out
        i += 1


def vertices(view):
    out = []
    i = 0
    while True:
        try:
            out.append((i, view.getVertexByIndex(i).Point))
        except Exception as _fw_err:
            _fw_log("drawannot.py:67", _fw_err)
            return out
        i += 1


def circles(view):
    """(edge index, centre, radius) of the view's full circles and arcs."""
    out = []
    for i, e in edges(view):
        c = e.Curve
        if type(c).__name__ == "Circle":
            out.append((i, V(c.Center.x, c.Center.y, 0), c.Radius))
    return out


def round_edges(view):
    ""

    full, halves, arcs = [], [], []
    groups = []                    # TechDraw may split one arc in pieces: pieces of one circle go together
    for i, e in edges(view):
        c = e.Curve
        if type(c).__name__ != "Circle":
            continue
        centre = V(c.Center.x, c.Center.y, 0)
        closed = e.isClosed() or len(e.Vertexes) < 2
        span = 2 * math.pi if closed else abs(e.LastParameter - e.FirstParameter)
        g = next((g for g in groups if (g[1] - centre).Length < 1e-6 and abs(g[2] - c.Radius) < 1e-6), None)
        if g is None:
            groups.append([i, centre, c.Radius, span])
        else:
            g[3] += span
    for i, centre, r, span in groups:
        item = (i, centre, r)
        if span > 2 * math.pi - 1e-3:
            full.append(item)
        elif abs(span - math.pi) < 1e-3:
            halves.append(item)
        else:
            arcs.append(item)
    slots, used = [], set()
    for a in range(len(halves)):
        for b in range(a + 1, len(halves)):
            if a in used or b in used:
                continue
            if abs(halves[a][2] - halves[b][2]) < 1e-6 and (halves[a][1] - halves[b][1]).Length > 1e-6:
                slots.append((halves[a], halves[b]))
                used.update((a, b))
    arcs += [h for n, h in enumerate(halves) if n not in used]
    return {"holes": full, "slots": slots, "fillets": arcs}


def circle_under(page, p, reach):
    """(view, (index, centre, radius)) of the circle within reach (sheet mm) of sheet point p, looking through
    every view under p (view boxes can overlap); (first view or None, None) when none is hit."""
    vs = DV.views_at(page, p)
    for v in vs:
        k = DV.view_scale(v) or 1.0
        hit = circle_at(v, DV.to_geometry(v, p), reach / k)
        if hit is not None:
            return v, hit
    return (vs[0] if vs else None), None


def circle_at(view, g, tol):
    """The circle of view whose rim is nearest geometry point g, within tol."""
    best = None
    for i, c, r in circles(view):
        dist = abs(math.hypot(g[0] - c.x, g[1] - c.y) - r)
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, i, c, r)
    return best[1:] if best else None


def line_at(view, g, tol):
    """The straight edge of view nearest geometry point g, within tol: (index, start, end)."""
    best = None
    for i, e in edges(view):
        if type(e.Curve).__name__ not in ("Line", "LineSegment") or len(e.Vertexes) < 2:
            continue
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        dist = _dist_seg(g, a, b)
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, i, a, b)
    return best[1:] if best else None


def _dist_seg(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a.x) * dx + (p[1] - a.y) * dy) / L2))
    return math.hypot(p[0] - a.x - t * dx, p[1] - a.y - t * dy)


def _styled(view, tag, style=CENTER_STYLE, weight=THIN_WEIGHT):
    try:
        ce = view.getCosmeticEdge(tag)
        fmt = ce.Format
        if isinstance(fmt, dict):                 # FreeCAD 1.1: {'style', 'weight', 'color', 'visible'}
            fmt = dict(fmt)
            fmt["style"] = style
            if weight:
                fmt["weight"] = weight
            ce.Format = fmt
        else:
            fmt = list(fmt) if isinstance(fmt, tuple) else fmt
            if isinstance(fmt, list) and fmt:
                fmt[0] = style
                if weight and len(fmt) > 1:
                    fmt[1] = weight
                ce.Format = tuple(fmt)
        view.replaceCosmeticEdge(ce) if hasattr(view, "replaceCosmeticEdge") else None
    except Exception as _fw_err:
        _fw_log("drawannot.py:174", _fw_err)
    return tag


class quiet_view:
    """with quiet_view(view): many cosmetic lines at once. TechDraw redraws the whole view for each cosmetic line
    made or restyled; on a big view (50 parts, 400 edges) that was about 6 s for one center mark and 20 minutes
    for Auto insert's center marks on 12 views. Hidden meanwhile, the view is drawn once, at the end (0.08 s a
    mark). A view hidden already, or one inside another quiet_view, is left as it is."""

    def __init__(self, view):
        self.view = view
        self.vo = None

    def __enter__(self):
        _BATCH[0] += 1
        try:
            vo = self.view.ViewObject
            if vo is not None and vo.Visibility:
                vo.Visibility = False
                self.vo = vo
        except Exception as _fw_err:
            _fw_log("drawannot.py:quiet_view", _fw_err)
        return self

    def __exit__(self, *exc):
        _BATCH[0] -= 1
        if _BATCH[0] <= 0:
            _BATCH[0] = 0
            _CENTRES.clear()
        if self.vo is not None:
            try:
                self.vo.Visibility = True
            except Exception as _fw_err:
                _fw_log("drawannot.py:quiet_view show", _fw_err)
        return False


_BATCH = [0]
_CENTRES = {}


def _model_centre(view):
    """DV.model_centre, kept for the view while a quiet_view batch runs: the model does not change meanwhile, and
    it cost 35 ms a call on a 50-part view (one call per center mark)."""
    if not _BATCH[0]:
        return DV.model_centre(view)
    key = view.Name
    if key not in _CENTRES:
        _CENTRES[key] = DV.model_centre(view)
    return V(_CENTRES[key])


def _tags(view, name):
    if not hasattr(view, name):
        view.addProperty("App::PropertyStringList", name, "FreeCAD", "Annotations made of cosmetic lines")
    return list(getattr(view, name))


KEPT = []      # (view, cosmetic tag) of every annotation line made this session (PMs put them on a layer)


def _keep(view, name, tags):
    _tags(view, name)
    setattr(view, name, list(getattr(view, name)) + [t for t in tags if t])
    KEPT.extend((view, t) for t in tags if t)


# --------------------------------------------------------------------------- Center Mark
SOLID_STYLE = 1


def center_mark(view, centre, radius, size=2.5, extended=None, gap=1.5, angle=0.0, font=None):
    ""



    if extended is None or font is None:
        page = None
        try:
            page = next((p for p in view.InList if p.TypeId == "TechDraw::DrawPage"), None)
        except Exception as _fw_err:
            _fw_log("drawannot.py:center_mark page", _fw_err)
        if extended is None:
            try:
                from . import drawdocprops as DDP
                extended = bool(DDP.row(view.Document, "Centerlines/Center Marks", "Extended lines", True))
            except Exception:
                extended = True
        if font is None:
            font = page is None or _standard(page) != "ANSI"
    with quiet_view(view):
        return _center_mark(view, centre, radius, size, extended, gap, angle, font)


def _center_mark(view, centre, radius, size, extended, gap, angle, font):
    k = DV.view_scale(view)
    s = size / k
    tags = []
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    style = CENTER_STYLE if font else SOLID_STYLE
    out = radius + gap / k
    split = extended and out > 2 * s + 1e-6
    arm = max(s, out) if extended and not split else s      # a small hole: the cross itself runs past the rim
    for dx, dy in ((ca, sa), (-sa, ca)):
        a = V(centre.x - dx * arm, centre.y - dy * arm, 0)
        b = V(centre.x + dx * arm, centre.y + dy * arm, 0)
        tags.append(_styled(view, view.makeCosmeticLine(a, b), style))
        if split:
            for sgn in (1, -1):         # past the gap, out beyond the circle
                a = V(centre.x + sgn * dx * 2 * s, centre.y + sgn * dy * 2 * s, 0)
                b = V(centre.x + sgn * dx * out, centre.y + sgn * dy * out, 0)
                tags.append(_styled(view, view.makeCosmeticLine(a, b), style))
    _keep(view, "SWCenterMarks", tags)
    _remember_mark(view, tags, centre, radius, size, extended, gap, angle, font)
    return tags


def _remember_mark(view, tags, centre, radius, size, extended, gap, angle, font):
    """A center mark keeps the model point it marks (SWCenterMarkAnchors), so it follows its hole when the
    model changes (follow_center_marks)."""
    try:
        d, x, y = D.view_frame(view)
        p = _model_centre(view) + x * centre.x + y * centre.y
        rows = list(getattr(view, "SWCenterMarkAnchors", []) or [])
        rows.append("%s|%.6g,%.6g,%.6g|%.6g|%.6g|%d|%.6g|%.6g|%d" % (
            ",".join(tags), p.x, p.y, p.z, radius, size, bool(extended), gap, angle, bool(font)))
        if "SWCenterMarkAnchors" not in view.PropertiesList:
            view.addProperty("App::PropertyStringList", "SWCenterMarkAnchors", "FreeCAD", "center marks' model points")
            view.setPropertyStatus("SWCenterMarkAnchors", ["Hidden"])
        view.SWCenterMarkAnchors = rows
    except Exception as error:
        App.Console.PrintLog("FreeCAD: center mark anchor: %s\n" % error)


def has_center_mark(view, centre):
    ""

    try:
        d, x, y = D.view_frame(view)
        p = _model_centre(view) + x * centre.x + y * centre.y
        live = set(getattr(view, "SWCenterMarks", []) or [])
        for row in list(getattr(view, "SWCenterMarkAnchors", []) or []):
            parts = row.split("|")
            if len(parts) < 2 or not any(t in live for t in parts[0].split(",") if t):
                continue
            q = V(*[float(t) for t in parts[1].split(",")])
            if (q - p).Length < 1e-4:
                return True
    except Exception as _fw_err:
        _fw_log("drawannot.py:has_center_mark", _fw_err)
    return False


def drop_center_mark(view, centre):
    ""


    try:
        d, x, y = D.view_frame(view)
        p = _model_centre(view) + x * centre.x + y * centre.y
        live = list(getattr(view, "SWCenterMarks", []) or [])
        rows = list(getattr(view, "SWCenterMarkAnchors", []) or [])
        for row in rows:
            parts = row.split("|")
            tags = [t for t in parts[0].split(",") if t] if parts else []
            if len(parts) < 2 or not any(t in live for t in tags):
                continue
            if (V(*[float(t) for t in parts[1].split(",")]) - p).Length >= 1e-4:
                continue
            for t in tags:
                try:
                    view.removeCosmeticEdge(t)
                except Exception as _fw_err:
                    _fw_log("drawannot.py:drop_center_mark", _fw_err)
            view.SWCenterMarks = [t for t in live if t not in tags]
            view.SWCenterMarkAnchors = [r for r in rows if r is not row]
            return True
    except Exception as _fw_err:
        _fw_log("drawannot.py:drop_center_mark", _fw_err)
    return False


def follow_center_marks(view):
    ""

    _BATCH[0] += 1                       # the model centre found once for all the marks (35 ms each on a big view)
    try:
        return _follow_center_marks(view)
    finally:
        _BATCH[0] -= 1
        if _BATCH[0] <= 0:
            _BATCH[0] = 0
            _CENTRES.clear()


def _follow_center_marks(view):
    rows = list(getattr(view, "SWCenterMarkAnchors", []) or [])
    if not rows:
        return False
    circs = circles(view)
    out, changed = [], False
    for row in rows:
        try:
            tags, p, radius, size, ext, gap, angle, font = row.split("|")
            tags = [t for t in tags.split(",") if t]
            p = V(*[float(v) for v in p.split(",")])
            radius = float(radius)
            g = _project(view, p)
            best = min((c for _i, c, r in circs if abs(r - radius) < 1e-3),
                       key=lambda c: (c - g).Length, default=None) if radius > 0 else None
            if best is not None and (best - g).Length < 20.0:
                g = best
            old = view.getCosmeticEdge(tags[0]) if tags else None
            if old is None:
                out.append(row)
                continue
            mid = V((old.Start.x + old.End.x) / 2, (old.Start.y + old.End.y) / 2, 0)
            if (mid - g).Length < 1e-4:
                out.append(row)
                continue
            for t in tags:
                try:
                    view.removeCosmeticEdge(t)
                except Exception as _fw_err:
                    _fw_log("drawannot.py:262", _fw_err)
            kept = [t for t in (getattr(view, "SWCenterMarks", []) or []) if t not in tags]
            view.SWCenterMarks = kept
            view.SWCenterMarkAnchors = out + rows[rows.index(row) + 1:]
            center_mark(view, V(g.x, g.y, 0), radius, float(size), bool(int(ext)), float(gap), float(angle), bool(int(font)))
            new_rows = list(view.SWCenterMarkAnchors)
            out.append(new_rows[-1])
            changed = True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: center mark follow: %s\n" % error)
            out.append(row)
    if changed:
        view.SWCenterMarkAnchors = out
    return changed


def connection_line(view, a, b):
    tag = _styled(view, view.makeCosmeticLine(V(a.x, a.y, 0), V(b.x, b.y, 0)))
    _keep(view, "SWCenterMarks", [tag])
    return tag


def pattern_circle(view, centres):
    """The circle through three or more centres (Circular center mark), else None."""
    if len(centres) < 3:
        return None
    (x1, y1), (x2, y2), (x3, y3) = [(c.x, c.y) for c in centres[:3]]
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return None
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    tag = _styled(view, view.makeCosmeticCircle(V(ux, uy, 0), r))
    _keep(view, "SWCenterMarks", [tag])
    return V(ux, uy, 0), r


def _circle_through(centres):
    """(centre, radius) of the circle through the first three centres, else None."""
    (x1, y1), (x2, y2), (x3, y3) = [(c.x, c.y) for c in centres[:3]]
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return None
    ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
    uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
    return V(ux, uy, 0), math.hypot(x1 - ux, y1 - uy)


def marked(view, centre):
    return any((c - centre).Length < 1e-6 for c in getattr(view, "_fw_marked", []))


class CenterMarkPanel(D._Panel):
    TITLE = "Center Mark"
    LAYER = True
    GROUP_ORDER = ("Auto Insert", "Manual Insert Options", "Display Attributes", "Angle", "Layer")
    PIXMAP = "TechDraw_ExtensionCircleCenterLines"

    def build(self):
        self.say("Click circles or arcs in a view to put center marks on them.")
        box, lay = D._group("Manual Insert Options", self.form)
        row = QtWidgets.QHBoxLayout()
        self.kind = QtWidgets.QButtonGroup(box)
        for n, k in enumerate(("Single", "Linear", "Circular")):
            b = QtWidgets.QToolButton(box)
            b.setText(k)
            b.setCheckable(True)
            b.setObjectName("SWCenterMark" + k)
            b.setToolTip({"Single": "Single Center Mark", "Linear": "Linear Center Mark",
                          "Circular": "Circular Center Mark"}[k])
            self.kind.addButton(b, n)
            row.addWidget(b)
            b.setChecked(n == 0)
        lay.addLayout(row)
        self.connect = QtWidgets.QCheckBox("Connection lines", box)
        self.connect.setObjectName("SWCenterMarkConnect")
        self.connect.setChecked(True)
        lay.addWidget(self.connect)

        self.circ_lines = QtWidgets.QCheckBox("Circular lines", box)
        self.circ_lines.setObjectName("SWCenterMarkCircularLines")
        self.circ_lines.setChecked(True)
        self.radial = QtWidgets.QCheckBox("Radial lines", box)
        self.radial.setObjectName("SWCenterMarkRadialLines")
        self.radial.setChecked(True)
        self.base_mark = QtWidgets.QCheckBox("Base center mark", box)
        self.base_mark.setObjectName("SWCenterMarkBase")
        self.base_mark.setChecked(True)
        for w in (self.circ_lines, self.radial, self.base_mark):
            lay.addWidget(w)

        def shown(*_):
            kind = self.kind.checkedButton().text() if self.kind.checkedButton() else "Single"
            self.connect.setVisible(kind == "Linear")
            for w in (self.circ_lines, self.radial, self.base_mark):
                w.setVisible(kind == "Circular")
            self.chain = []
        self.kind.buttonClicked.connect(shown)
        shown()
        self.lay.addWidget(box)
        box, lay = D._group("Auto Insert", self.form)
        self.auto = QtWidgets.QCheckBox("For all holes", box)
        self.auto.setObjectName("SWCenterMarkAllHoles")
        self.auto.toggled.connect(self.all_holes)
        lay.addWidget(self.auto)
        self.auto_fillets = QtWidgets.QCheckBox("For all fillets", box)
        self.auto_fillets.setObjectName("SWCenterMarkAllFillets")
        self.auto_fillets.toggled.connect(lambda on: self.all_of("fillets", on))
        lay.addWidget(self.auto_fillets)
        self.auto_slots = QtWidgets.QCheckBox("For all slots", box)
        self.auto_slots.setObjectName("SWCenterMarkAllSlots")
        self.auto_slots.toggled.connect(lambda on: self.all_of("slots", on))
        lay.addWidget(self.auto_slots)
        self.lay.addWidget(box)
        box, lay = D._group("Display Attributes", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Mark size:", box))
        self.size = QtWidgets.QDoubleSpinBox(box)
        self.size.setObjectName("SWCenterMarkSize")
        self.size.setRange(0.1, 100)
        self.size.setValue(2.5)
        self.size.setSuffix("mm")
        row.addWidget(self.size)
        lay.addLayout(row)
        self.extended = QtWidgets.QCheckBox("Extended lines", box)
        self.extended.setObjectName("SWCenterMarkExtended")
        lay.addWidget(self.extended)
        self.font = QtWidgets.QCheckBox("Centerline font", box)
        self.font.setObjectName("SWCenterMarkFont")
        self.font.setChecked(True)
        lay.addWidget(self.font)

        self.docdef = QtWidgets.QCheckBox("Use document defaults", box)
        self.docdef.setObjectName("SWCenterMarkDocDefaults")
        lay.insertWidget(0, self.docdef)
        try:
            from . import drawdocprops as DDP
            self._doc_size = float(DDP.row(self.doc, "Centerlines/Center Marks", "Size", self.size.value()))
            self._doc_ext = bool(DDP.row(self.doc, "Centerlines/Center Marks", "Extended lines", True))
        except Exception:
            self._doc_size, self._doc_ext = self.size.value(), True

        def docdef(on):
            # NO DEAD CONTROLS: Mark size / Extended lines stay live; using one turns Use document defaults off
            if on:
                self.size.setValue(self._doc_size)
                self.extended.setChecked(self._doc_ext)
        self.docdef.toggled.connect(docdef)
        self.docdef.setChecked(True)
        DL.sets(self.docdef, False, self.size, self.extended)
        self.lay.addWidget(box)
        box, lay = D._group("Angle", self.form)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWCenterMarkAngle")
        self.angle.setRange(-360, 360)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")                # as every other PM (drawings-land281)
        lay.addWidget(self.angle)
        self.lay.addWidget(box)
        self.chain = []         # (view, centre) of the Linear / Circular set so far

    def mark(self, view, centre, radius):
        done = getattr(view, "_fw_marked_tags", None)
        key = (view.Name, round(centre.x, 6), round(centre.y, 6))
        made = self.__dict__.setdefault("done", {})
        settings = (round(self.size.value(), 6), self.extended.isChecked(), round(self.angle.value(), 6),
                    self.font.isChecked())
        if made.get(key) == settings:
            return False            # already drawn with these settings on this page
        made[key] = settings
        if has_center_mark(view, centre):

            drop_center_mark(view, centre)
            self.say("Center mark updated.")
        center_mark(view, centre, radius, self.size.value(), self.extended.isChecked(),
                    angle=self.angle.value(), font=self.font.isChecked())
        return True

    def sheet_click(self, p):
        view, hit = circle_under(self.page, p, 2.0)
        if view is None:
            self.say("Click a circle or an arc inside a drawing view.")
            return True
        if hit is None:
            self.say("Click on a circle or an arc.")
            return True
        i, c, r = hit
        self.mark(view, c, r)
        kind = self.kind.checkedButton().text()
        if kind != "Single":
            self.chain = [(v, cc) for v, cc in self.chain if v is view]
            if self.chain and kind == "Linear" and self.connect.isChecked():
                connection_line(view, self.chain[-1][1], c)
            self.chain.append((view, c))
            if kind == "Circular":
                self.circular(view, c)
        self.doc.recompute()
        return True

    def circular(self, view, c):
        """The Circular set: from its third mark on, the pattern circle, a radial line to each mark and the
        base center mark at the pattern's centre."""
        centres = [cc for _, cc in self.chain]
        if len(centres) < 3:
            return
        done = self.__dict__.setdefault("circ_done", {})
        state = done.get(view.Name)
        if state is None:
            got = _circle_through(centres)
            if got is None:
                return
            mid, r = got
            if self.circ_lines.isChecked():
                tag = _styled(view, view.makeCosmeticCircle(V(mid.x, mid.y, 0), r))
                _keep(view, "SWCenterMarks", [tag])
            if self.base_mark.isChecked():
                center_mark(view, mid, 0.0, self.size.value(), False, angle=self.angle.value(), font=self.font.isChecked())
            state = done[view.Name] = (mid, set())
            todo = centres
        else:
            todo = [c]
        mid, joined = state
        if self.radial.isChecked():
            for cc in todo:
                key = (round(cc.x, 6), round(cc.y, 6))
                if key not in joined:
                    joined.add(key)
                    connection_line(view, mid, cc)

    def all_holes(self, on):
        self.all_of("holes", on)

    def all_of(self, kind, on):
        if not on:
            return
        for view in DV.D.views_of(self.page):
            try:
                found = round_edges(view)[kind]
            except Exception:
                continue
            for item in found:
                if kind == "slots":
                    (i1, c1, r1), (i2, c2, r2) = item
                    self.mark(view, c1, r1)
                    self.mark(view, c2, r2)
                    joined = self.__dict__.setdefault("joined", set())
                    pair = (view.Name, round(c1.x, 6), round(c1.y, 6), round(c2.x, 6), round(c2.y, 6))
                    if pair not in joined:              # For all slots ticked again: not a second line
                        joined.add(pair)
                        connection_line(view, c1, c2)
                else:
                    self.mark(view, item[1], item[2])
        self.doc.recompute()


# --------------------------------------------------------------------------- Centerline
CENTERLINE_OVER = [2.0]      # Document Properties > Centerlines/Center Marks > Centerlines extension


def centerline(view, a1, b1, a2, b2, over=None):
    """The centerline half-way between segments a1-b1 and a2-b2 (view geometry), over sheet mm past their ends."""
    over = CENTERLINE_OVER[0] if over is None else over
    k = DV.view_scale(view)
    d = V(b1.x - a1.x, b1.y - a1.y, 0)
    if d.Length < 1e-9:
        raise ValueError("the first edge has no length")
    d = d * (1.0 / d.Length)
    e2 = V(b2.x - a2.x, b2.y - a2.y, 0)
    if e2.Length < 1e-9 or abs(abs(d.dot(e2 * (1.0 / e2.Length))) - 1) > 1e-3:
        raise ValueError("the edges are not parallel")
    mid = (a1 + b1 + a2 + b2) * 0.25
    ts = [d.dot(p - mid) for p in (a1, b1, a2, b2)]
    t0, t1 = min(ts) - over / k, max(ts) + over / k
    tag = _styled(view, view.makeCosmeticLine(mid + d * t0, mid + d * t1))
    _keep(view, "SWCenterlines", [tag])
    return tag


def auto_centerlines(view, over=None):
    with quiet_view(view):
        return _auto_centerlines(view, over)


def _auto_centerlines(view, over=None):
    ""


    over = CENTERLINE_OVER[0] if over is None else over
    k = DV.view_scale(view)
    tags = []
    have = {(round(a.x, 3), round(a.y, 3), round(b.x, 3), round(b.y, 3)) for a, b in _centerline_ends(view)}
    axes = []          # [direction, point on it, lo, hi] of each axis line in the view
    for o in DV.source_shapes(view):
        try:
            faces = o.Shape.Faces
        except Exception:
            continue
        for f in faces:
            srf = f.Surface
            if type(srf).__name__ not in ("Cylinder", "Cone"):
                continue
            try:
                u0, u1, v0, v1 = f.ParameterRange
                a3 = f.valueAt((u0 + u1) / 2, v0)
                b3 = f.valueAt((u0 + u1) / 2, v1)
                ax = srf.Axis
                c = srf.Center if hasattr(srf, "Center") else srf.Apex
                a3 = c + ax * ax.dot(a3 - c)
                b3 = c + ax * ax.dot(b3 - c)
            except Exception:
                continue
            pa, pb = _project(view, a3), _project(view, b3)
            d = pb - pa
            if d.Length < 1e-6:
                continue
            d = d * (1.0 / d.Length)
            if d.x < -1e-9 or (abs(d.x) < 1e-9 and d.y < 0):
                d = d * -1.0
            for line in axes:
                n = V(-line[0].y, line[0].x, 0)
                if abs(abs(line[0].dot(d)) - 1) < 1e-6 and abs((pa - line[1]).dot(n)) < 1e-4:
                    ts = [(p - line[1]).dot(line[0]) for p in (pa, pb)]
                    line[4].append((min(ts), max(ts)))
                    break
            else:
                axes.append([d, pa, 0, 0, [tuple(sorted(((pa - pa).dot(d), (pb - pa).dot(d))))]])
    for d, p0, _lo, _hi, spans in axes:
        spans.sort()
        merged = []
        for lo, hi in spans:          # overlapping or touching spans on one axis make one centerline
            if merged and lo <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        for lo, hi in merged:
            a, b = p0 + d * (lo - over / k), p0 + d * (hi + over / k)
            if (round(a.x, 3), round(a.y, 3), round(b.x, 3), round(b.y, 3)) in have or \
                    (round(b.x, 3), round(b.y, 3), round(a.x, 3), round(a.y, 3)) in have:
                continue
            tag = _styled(view, view.makeCosmeticLine(a, b))
            _keep(view, "SWCenterlines", [tag])
            tags.append(tag)
    return tags


def _centerline_ends(view):
    out = []
    for t in list(getattr(view, "SWCenterlines", []) or []):
        try:
            ce = view.getCosmeticEdge(t)
            out.append((ce.Start, ce.End))
        except Exception as _fw_err:
            _fw_log("drawannot.py:600", _fw_err)
    return out


class CenterlinePanel(D._Panel):
    TITLE = "Centerline"
    LAYER = True
    PIXMAP = "TechDraw_2LineCenterLine"

    def build(self):
        self.say("Click two edges of a view (the sides of a cylinder or a slot) to put a centerline between them.")
        box, lay = D._group("Auto Insert", self.form)
        self.auto = QtWidgets.QCheckBox("Select View", box)
        self.auto.setObjectName("SWCenterlineSelectView")
        self.auto.setToolTip("Click a view: centerlines on all its cylinders, cones and slots seen from the side.")
        self.auto.toggled.connect(lambda on: self.say("Click a view to put centerlines on all its cylindrical "
                                                      "faces." if on else "Click two edges of a view (the sides "
                                                      "of a cylinder or a slot) to put a centerline between them."))
        lay.addWidget(self.auto)
        self.lay.addWidget(box)
        self.first = None

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if view is not None and self.auto.isChecked():
            tags = auto_centerlines(view)
            self.doc.recompute()
            self.say("%d centerline%s added. Click another view, or OK." % (len(tags), "" if len(tags) == 1 else "s"))
            return True
        if view is None:
            self.say("Click an edge inside a drawing view.")
            return True
        k = DV.view_scale(view)
        hit = line_at(view, DV.to_geometry(view, p), 2.0 / k)
        if hit is None:
            self.say("Click on a straight edge.")
            return True
        if self.first is None or self.first[0] is not view:
            self.first = (view, hit)
            self.say("Click the second edge.")
            return True
        (_, (i1, a1, b1)), (i2, a2, b2) = self.first, hit
        self.first = None
        if i1 == i2:
            self.say("Click a second, different edge.")
            return True
        try:
            centerline(view, a1, b1, a2, b2)
        except ValueError as error:
            self.say("%s. Click two parallel edges." % str(error).capitalize())
            return True
        self.doc.recompute()
        self.say("Centerline added. Click two more edges, or OK.")
        return True


# --------------------------------------------------------------------------- dimensions
_SPEC = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[wWfeEgG]")


def set_text(dim, text):
    """dim's text. TechDraw draws an empty label for a text with no number format in it (FreeCAD 1.1): such a
    text (the Hole Wizard's callout, its values written out) is shown as it is (Arbitrary)."""
    plain = not _SPEC.search(text.replace("%%", ""))
    if plain:
        dim.Arbitrary = True        # first, then the text (TechDraw warns on a text without a format)
    dim.FormatSpec = text
    if not plain and dim.Arbitrary:
        dim.Arbitrary = False


def dimension(page, view, kind, refs, at=None, fmt=None):
    """A TechDraw dimension of kind (Distance, DistanceX, DistanceY, Radius, Diameter) on view's refs."""
    doc = page.Document
    dim = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
    dim.Type = kind
    dim.MeasureType = "Projected"
    dim.References2D = [(view, r) for r in refs]
    if fmt:
        set_text(dim, fmt)
    page.addView(dim)
    if at is not None:
        dim.X, dim.Y = at
    return dim


def _project0(view, p):
    return _project(view, p)


def _project(view, p):
    """3D model point -> view geometry (unscaled, centred)."""
    q = view.projectPoint(p) - view.projectPoint(_model_centre(view))
    return V(q.x, q.y, 0)


def _vertex_near(view, q, verts, tol=1e-3):
    for i, p in verts:
        if abs(p.x - q.x) < tol and abs(p.y - q.y) < tol:
            return "Vertex%d" % i
    return None


def _vertex_in_line(q, verts, kind, tol=1e-3):
    """The view vertex nearest q with q's x (DistanceX) or y (DistanceY), else None."""
    best = None
    for i, p in verts:
        same = abs(p.x - q.x) < tol if kind == "DistanceX" else abs(p.y - q.y) < tol
        if same:
            dd = (p - q).Length
            if best is None or dd < best[0]:
                best = (dd, i)
    return "Vertex%d" % best[1] if best else None


def _circle_near(view, c, r, tol=1e-3):
    for i, cc, rr in circles(view):
        if abs(rr - r) < tol and (cc - c).Length < tol:
            return "Edge%d" % i
    return None


def _geo_point(sk, gi, pos):
    """Global point of sketch geometry gi at pos (1 start, 2 end, 3 centre)."""
    g = sk.Geometry[gi]
    if pos == 1:
        p = g.StartPoint
    elif pos == 2:
        p = g.EndPoint
    elif pos == 3:
        p = g.Center
    else:
        return None
    return sk.getGlobalPlacement().multVec(p)


def model_sketches(view, hidden=True):
    ""

    out = []
    for o in DV.source_shapes(view):
        doc = o.Document
        for s in doc.Objects:
            if s.TypeId != "Sketcher::SketchObject":
                continue
            if not hidden:
                users = [u for u in s.InList if u.TypeId.startswith("PartDesign::") and u.TypeId != "PartDesign::Body"]
                if users and all(not getattr(u, "Visibility", True) and getattr(u, "Suppressed", False) for u in users):
                    continue
                if any(getattr(u, "Suppressed", False) for u in users):
                    continue
            out.append(s)
        break
    return out


def part_of_hole(view, c, r, others):
    ""

    smaller = [rr for q, rr in others if abs(q.x - c.x) < 1e-6 and abs(q.y - c.y) < 1e-6 and rr < r - 1e-6]
    if not smaller:
        return False
    try:
        h = wizard_hole(view, c, r)
        if h is None:       # extapps109: the rim of a hole an assembly feature made
            from . import asmholecallout as AH
            a = AH.owner(view, c, r, D, DV)
            return a is not None and any(AH.owner(view, c, rr, D, DV) is a for rr in smaller)
        return h is not None and any(wizard_hole(view, c, rr) is h for rr in smaller)
    except Exception as _fw_err:
        _fw_log("drawannot.py:754", _fw_err)
        return False


def hole_callouts(page, views, eliminate_duplicates=True):
    ""

    made, seen = [], set()
    for view in views:
        k = DV.view_scale(view)
        done = []
        every = [(c, r) for _i, c, r in circles(view)]
        for i, c, r in circles(view):
            key = round(r, 4)
            if part_of_hole(view, c, r, every):
                continue
            if any(abs(c.x - q.x) < 1e-6 and abs(c.y - q.y) < 1e-6 and abs(rr - r) < 1e-6 for q, rr in done):
                continue
            done.append((c, r))
            if eliminate_duplicates and key in seen:
                continue
            text = hole_text(view, c, r)
            if text == "\u2300%.2w" and not _is_hole_circle(view, c, r):
                continue
            if text == "\u2300%.2w" and _not_hole(view, c, r):
                continue
            seen.add(key)
            same = sum(1 for q, rr in done if abs(rr - r) < 1e-6)
            text = callout_text(view, c, r, 2, True)    # "4X" in front, as the Hole Callout tool
            dim = dimension(page, view, "Diameter", ["Edge%d" % i],
                            (c.x * k + r * k + 8, c.y * k + r * k + 8), text)
            dim.addProperty("App::PropertyBool", "SWHoleCallout", "FreeCAD", "Hole callout")
            dim.SWHoleCallout = True
            mark_callout(dim, count=True)
            made.append(dim)
    return made


def _is_hole_circle(view, c, r):
    """A circle of the view that is the rim of a hole (an inner cylinder) rather than an outer round."""
    return hole_text(view, c, r) != "\u2300%.2w"


def _not_hole(view, c, r):
    """The circle is the rim of an outer cylinder (a boss or a shaft), not of a hole."""
    d, x, y = D.view_frame(view)
    c3 = DV.model_centre(view) + x * c.x + y * c.y
    for o in DV.source_shapes(view):
        try:
            faces = o.Shape.Faces
        except Exception:
            continue
        for f in faces:
            s = f.Surface
            if type(s).__name__ != "Cylinder" or abs(s.Radius - r) > 1e-4:
                continue
            ax = D._unit(s.Axis)
            off = (s.Center - c3) - ax * (s.Center - c3).dot(ax)
            if abs(abs(ax.dot(d)) - 1) < 1e-4 and off.Length < 1e-3 and not _is_hole(f):
                return True
    return False


def origin_marks(page, views):
    """Model Items' Origins: the model's origin as a point in each view."""
    made = []
    for view in views:
        try:
            g = _project(view, V(0, 0, 0))
            tag = view.makeCosmeticVertex(V(g.x, g.y, 0))
            made.append((view, tag))
        except Exception:
            continue
    return made


def _model_objects(view):
    """Every object of the documents the view shows."""
    docs = []
    for o in DV.source_shapes(view):
        if o.Document not in docs:
            docs.append(o.Document)
    return [o for d in docs for o in d.Objects]


def _standard(page):
    """The drawing's drafting standard (Document Properties > Drafting Standard), ANSI until it is set."""
    std = getattr(page, "SWDraftStandard", "") or ""
    if not std:
        try:
            from . import drawdocprops as DDP
            std = DDP.stored(page.Document).get("standard", "") or ""
        except Exception as _fw_err:
            _fw_log("drawannot.py:_standard", _fw_err)
    return std or "ANSI"


def cosmetic_threads(page, views, only=None):
    """Model Items' Cosmetic threads: each cosmetic thread of the model in the views. Seen end on, a thin circle
    at the thread's other diameter (minor on a shaft, major in a hole); seen from the side, the two thread lines
    along its length and the line where it ends (dashed for a hole, which is hidden)."""
    import json
    made = []
    for view in views:
        d, x, y = D.view_frame(view)
        for o in _model_objects(view):
            info = getattr(o, "ThreadInfo", "")
            if not info or (only is not None and o not in only):
                continue
            try:
                t = json.loads(info)
                c = V(*t["centre"])
                ax = V(*t["direction"])
                ro, R, L = float(t["other"]), float(t["radius"]), float(t["length"])
                inside = bool(t.get("internal"))
            except Exception:
                continue
            tags = []
            style = 2 if inside else 1                   # TechDraw: 1 continuous, 2 dashed (hidden)
            try:
                if abs(abs(ax.dot(d)) - 1) < 1e-6:
                    g = _project(view, c)
                    tag = None
                    if _standard(page) != "ANSI":

                        # its open quarter at the upper right (drawings-land275)
                        tag = view.makeCosmeticCircleArc(V(g.x, g.y, 0), ro, 90.0, 360.0)
                    if not tag:
                        tag = view.makeCosmeticCircle(V(g.x, g.y, 0), ro)
                    tags.append(_styled(view, tag, 1))
                elif abs(ax.dot(d)) < 1e-6:
                    side = d.cross(ax)
                    side.normalize()
                    for sgn in (1, -1):
                        a = _project(view, c + side * (sgn * ro))
                        b = _project(view, c + side * (sgn * ro) + ax * L)
                        tags.append(_styled(view, view.makeCosmeticLine(V(a.x, a.y, 0), V(b.x, b.y, 0)), style))
                    a = _project(view, c + ax * L + side * R)
                    b = _project(view, c + ax * L - side * R)
                    tags.append(_styled(view, view.makeCosmeticLine(V(a.x, a.y, 0), V(b.x, b.y, 0)), style))
            except Exception:
                continue
            if tags:
                _keep(view, "SWThreadLines", tags)
                made.append((view, tags))
    return made


def plane_traces(page, views):
    ""

    made = []
    for view in views:
        d, x, y = D.view_frame(view)
        a, b, c, e = DV.view_box(view)
        k = DV.view_scale(view)
        half = max(c - a, e - b) / k * 0.6 + 2.0
        for o in _model_objects(view):
            if o.TypeId not in ("PartDesign::Plane", "Part::DatumPlane"):
                continue
            pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
            n = pl.Rotation.multVec(V(0, 0, 1))
            if abs(n.dot(d)) > 1e-6:
                continue
            t = d.cross(n)
            g0, g1 = _project(view, pl.Base), _project(view, pl.Base + t)
            u = g1 - g0
            if u.Length < 1e-9:
                continue
            u = u * (1.0 / u.Length)
            try:
                tag = _styled(view, view.makeCosmeticLine(g0 - u * half, g0 + u * half), PHANTOM_STYLE)
            except Exception:
                continue
            _keep(view, "SWPlaneTraces", [tag])
            made.append((view, tag))
    return made


def datum_points(page, views):
    """Model Items' Points: each datum point of the model as a small cross in the views."""
    made = []
    for view in views:
        for o in _model_objects(view):
            if o.TypeId not in ("PartDesign::Point", "Part::DatumPoint"):
                continue
            pl = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
            g = _project(view, pl.Base)
            made += [(view, t) for t in center_mark(view, g, 0.0, 1.5)]
    return made


def instance_counts(page, views):
    """Model Items' Instance/revolution counts: "nX" beside each pattern of the model, in the views."""
    made = []
    for view in views:
        x0, y0 = D.view_position(view)
        k = DV.view_scale(view)
        for o in _model_objects(view):
            if o.TypeId not in ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::MultiTransform"):
                continue
            n = int(getattr(o, "Occurrences", 0) or 0)
            if o.TypeId == "PartDesign::MultiTransform":
                n = 1
                for t in getattr(o, "Transformations", []) or []:
                    n *= max(1, int(getattr(t, "Occurrences", 1) or 1))
            if n < 2:
                continue
            src = (getattr(o, "Originals", None) or [None])[0]
            try:
                bb = (src.AddSubShape if src is not None else o.Shape).BoundBox
                g = _project(view, bb.Center)
            except Exception:
                g = V(0, 0, 0)
            at = (x0 + g.x * k + 6.0, y0 + g.y * k + 6.0)
            text = "%dX" % n
            body, reach = note_svg(text, at)
            s = svg_symbol(page, "Note", body, reach, at, "Note%d" % _count(page.Document, "Note"), "Note")
            s.addProperty("App::PropertyString", "SWText", "FreeCAD", "note text")
            s.SWText = text
            s.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
            s.SWModelItemKey = "count:%s:%s" % (o.Name, view.Name)
            made.append(s)
    return made


# --------------------------------------------------------------------------- Model Items from the part's own annotations
def _sheet(view, p3):
    """3D model point -> sheet point."""
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    g = _project(view, p3)
    return (x0 + g.x * k, y0 + g.y * k)


def _unique_objects(views):
    out = []
    for v in views:
        for o in _model_objects(v):
            if o not in out:
                out.append(o)
    return out


def _pmi_elements(o):
    out = []
    for obj, subs in getattr(o, "References", None) or []:
        for s in (subs if isinstance(subs, (list, tuple)) else [subs]):
            try:
                out.append(obj.Shape.getElement(s.split(".")[-1]) if s else obj.Shape)
            except Exception as _fw_err:
                _fw_log("drawannot.py:960", _fw_err)
    return out


def _pmi_anchor(o):
    pts = [e.CenterOfMass if hasattr(e, "CenterOfMass") else e.Point for e in _pmi_elements(o)]
    return sum(pts, V()) * (1.0 / len(pts)) if pts else V(o.TextPosition)


def _sees(view, o):
    """True when view shows o's face the way a drawing annotates it: a flat face edge-on, a round face end-on."""
    d, x, y = D.view_frame(view)
    for e in _pmi_elements(o):
        s = getattr(e, "Surface", None)
        if s is None:
            continue
        name = type(s).__name__
        if name == "Plane":
            return abs(s.Axis.dot(d)) < 1e-6
        if name == "Cylinder":
            return abs(abs(s.Axis.dot(d)) - 1) < 1e-6
    return False


PMI_DIMENSIONS = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Pattern")


def _target_body(text, at, tip):
    r = 4.0
    body = ['<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (r, STROKE),
            '<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (-r, r, STROKE),
            '<text x="0" y="%g" font-family="osifont, Arial" font-size="2.5" text-anchor="middle">%s</text>'
            % (r * 0.75, _esc(text))]
    if tip is not None:
        tx, ty = _rel(at, tip)
        L = math.hypot(tx, ty)
        if L > r:
            body.append(_arrow(tx, ty, tx * r / L, ty * r / L, "Dot"))
    return "".join(body), r + _reach(at, tip)


def _pmi_tolerance(dim, o, prefix=""):
    """The 3D dimension's tolerance and precision on the drawing dimension, as the Dimension PM writes them (kept
    on the dimension, so the drawing's Document Properties defaults leave them alone): Basic in its box, else
    symmetric or plus/minus."""
    from . import drawdimpm as DP
    plus, minus = float(getattr(o, "Plus", 0.0) or 0.0), float(getattr(o, "Minus", 0.0) or 0.0)
    if o.Kind.startswith("Basic"):
        tol = "Basic"
    elif abs(plus) < 1e-12 and abs(minus) < 1e-12:
        tol = "None"
    elif abs(plus + minus) < 1e-12:
        tol = "Symmetric"
    else:
        tol = "Bilateral"
    m = re.search(r"\d+\.(\d+)", o.Text or "")
    places = ".123456"[:len(m.group(1)) + 1] if m else ".12"
    DP.apply(dim, tol=tol, plus=plus, minus=minus, precision=places, tol_precision=places, text=prefix + DP.DIM)


def _round_on(view, face):
    """(edge index, centre in view geometry) of a hole or boss face seen end on in view, else None."""
    s = getattr(face, "Surface", None)
    if type(s).__name__ != "Cylinder":
        return None
    d = D.view_frame(view)[0]
    if abs(abs(s.Axis.dot(d)) - 1) > 1e-6:
        return None
    c = _project(view, s.Center)
    for i, cc, r in circles(view):
        if abs(cc.x - c.x) < 1e-3 and abs(cc.y - c.y) < 1e-3 and abs(r - s.Radius) < 1e-4:
            return i, cc
    return None


def _plane_on(view, face):
    """(view vertices on a flat face seen edge on, its normal in view geometry) or None."""
    s = getattr(face, "Surface", None)
    if type(s).__name__ != "Plane":
        return None
    d = D.view_frame(view)[0]
    if abs(s.Axis.dot(d)) > 1e-6:
        return None
    n = _project(view, face.CenterOfMass + s.Axis) - _project(view, face.CenterOfMass)
    verts = vertices(view)
    on = []
    for x in face.Vertexes:
        name = _vertex_near(view, _project(view, x.Point), verts)
        if name is not None and name not in on:
            on.append(name)
    return (on, n) if on else None


def pmi_dimension(page, view, o):
    ""


    els = _pmi_elements(o)
    k = DV.view_scale(view)
    if o.Kind in ("Size", "BasicSize", "Pattern"):
        hits = [h for h in (_round_on(view, e) for e in els) if h is not None]
        if not hits:
            return None
        i, c = min(hits, key=lambda h: (h[1].x, h[1].y))
        r = next(e.Surface.Radius for e in els if type(getattr(e, "Surface", None)).__name__ == "Cylinder")
        dim = dimension(page, view, "Diameter", ["Edge%d" % i], (c.x * k + r * k + 8, c.y * k + r * k + 8))
        m = re.match(r"\s*(\d+)X", o.Text or "")
        _pmi_tolerance(dim, o, ("%sX " % m.group(1) if o.Kind == "Pattern" and m else "") + "\u2300")
        return dim
    if o.Kind not in ("Location", "BasicLocation") or len(els) < 2:
        return None
    verts = dict(vertices(view))
    first = _plane_on(view, els[0])
    if first is None:
        return None
    names, n = first
    across = abs(n.x) >= abs(n.y)                 # the face's normal runs across the sheet: a horizontal distance
    kind = "DistanceX" if across else "DistanceY"
    targets = []
    for e in els[1:]:
        hole = _round_on(view, e)
        if hole is not None:
            v = _vertex_near(view, hole[1], list(verts.items()))
            if v is not None:
                targets.append(v)
            continue
        other = _plane_on(view, e)
        if other is not None:
            targets += other[0][:1]
    for t in targets:
        p = verts[int(t[6:])]
        for a in names:
            q = verts[int(a[6:])]
            run = abs((p.x - q.x) if across else (p.y - q.y))
            if abs(run - float(o.Value)) > 1e-3:
                continue
            mid = ((p.x + q.x) / 2 * k, (p.y + q.y) / 2 * k)
            lo = min(v.y for v in verts.values()) * k if across else min(v.x for v in verts.values()) * k
            at = (mid[0], lo - 10.0) if across else (lo - 10.0, mid[1])
            dim = dimension(page, view, kind, [a, t], at)
            _pmi_tolerance(dim, o)
            return dim
    return None


def pmi_items(page, views, kinds, eliminate_duplicates=True):
    """Model Items' Datums, Datum targets, Geometric tolerances and Tolerance dimensions: the part's own 3D
    annotations (its MBD ones), each brought into the view that best shows its face, once per drawing."""
    made, placed = [], []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for o in _unique_objects(views):
        if getattr(o, "SWStyleKind", "") != "PMI" or o.Kind not in kinds:
            continue
        if o.Kind == "Note" and getattr(o, "SWAnnotation3D", "Note") not in ("", "Note"):
            continue                             # a 3D balloon, table or label is not a model note
        key = "pmi:%s" % o.Name
        if key in seen:
            continue
        shows = [v for v in views if o in _model_objects(v)]
        best = next((v for v in shows if _sees(v, o)), shows[0] if shows else None)
        if best is None:
            continue
        if o.Kind in PMI_DIMENSIONS:
            dim = None
            for v in [best] + [v for v in shows if v is not best]:
                try:
                    dim = pmi_dimension(page, v, o)
                except Exception as _fw_err:
                    _fw_log("drawannot.py:pmi_dimension", _fw_err)
                    dim = None
                if dim is not None:
                    break
            if dim is not None:
                dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
                dim.SWModelItemKey = key
                seen.add(key)
                made.append(dim)
                continue
        tip = _sheet(best, _pmi_anchor(o))
        at = _sheet(best, V(o.TextPosition))
        if math.hypot(at[0] - tip[0], at[1] - tip[1]) < 6.0:
            at = (tip[0] + 10.0, tip[1] + 10.0)
        at = _clear_of(_off_view(best, at), [p for p in placed if p[0] is best])
        placed.append((best, at))
        kind, text = o.Kind, o.Text or ""
        if kind == "SurfaceFinish":

            sym, value, f = _finish_of(o)
            body, reach = finish_svg(sym, value, at, tip, minimum=f.get("min", ""), method=f.get("method", ""),
                                     allowance=f.get("allowance", ""), sampling=f.get("sampling", ""),
                                     other=f.get("other", ""), spacing=f.get("spacing", ""))
            s = svg_symbol(page, "SurfaceFinish", body, reach, at, "Surface Finish%d" % (1 + len(
                [x for x in page.Document.Objects if getattr(x, "SWAnnotation", "") == "SurfaceFinish"])),
                "SurfaceFinish")
            s.addProperty("App::PropertyString", "SWFinish", "FreeCAD", "symbol and roughness")
            s.SWFinish = "%s %s" % (sym, value)
        elif kind == "Datum":
            body, reach = datum_svg(text, at, tip)
            s = svg_symbol(page, "DatumFeature", body, reach, at, "Datum Feature%s" % text, "DatumFeature")
            s.addProperty("App::PropertyString", "SWDatum", "FreeCAD", "datum letter")
            s.SWDatum = text
        elif kind == "DatumTarget":
            body, reach = _target_body(text, at, tip)
            s = svg_symbol(page, "DatumTarget", body, reach, at, "Datum Target%d" % _count(page.Document,
                                                                                         "DatumTarget"), "DatumTarget")
        elif kind == "GTol":
            cells = [c for c in text.strip("|").split("|") if c]
            body, reach = gtol_svg(cells, at, tip)
            s = svg_symbol(page, "GeometricTolerance", body, reach, at, "Geometric Tolerance%d" % _count(
                page.Document, "GeometricTolerance"), "GeometricTolerance")
            s.addProperty("App::PropertyStringList", "SWCells", "FreeCAD", "feature control frame cells")
            s.SWCells = cells
        else:
            body, reach = note_svg(text, at, tip, border="Box" if kind.startswith("Basic") else "None")
            s = svg_symbol(page, "Note", body, reach, at, "Note%d" % _count(page.Document, "Note"), "Note")
            s.addProperty("App::PropertyString", "SWText", "FreeCAD", "note text")
            s.SWText = text
        s.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
        s.SWModelItemKey = key
        seen.add(key)
        made.append(s)
    return made


def _off_view(view, at, margin=10.0):
    ""

    try:
        from . import drawviews as DV
        x0, y0, x1, y1 = DV.view_box(view)          # on the sheet
        if x0 < at[0] < x1 and y0 < at[1] < y1:
            top = y1                                 # and above the dimensions over the view
            vx, vy = D.view_position(view)
            for o in view.Document.Objects:
                if o.TypeId == "TechDraw::DrawViewDimension" and (getattr(o, "References2D", None) or [[None]])[0][0] \
                        is view and vy + float(o.Y) > top:
                    top = vy + float(o.Y) + 4.0
            return at[0], top + margin
    except Exception as _fw_err:
        _fw_log("drawannot.py:off_view", _fw_err)
    return at


def _clear_of(at, placed, gap=12.0):
    ""

    x, y = at
    for _ in range(40):
        if all(math.hypot(x - p[1][0], y - p[1][1]) >= gap for p in placed):
            break
        y += gap
    return x, y


def _finish_of(o):
    ""
    names = {"Basic": "Basic", "Machining required": "Machining Required",
             "Machining prohibited": "Machining Prohibited"}
    sym = names.get(str(getattr(o, "SurfaceSymbol", "") or ""), "")
    text = o.Text or ""
    if not sym:
        glyphs = {"\u221a": "Basic", "\u2200": "Machining Required", "\u237b": "Machining Prohibited"}
        sym = next((v for g, v in glyphs.items() if g in text), "Basic")
    fields = dict(getattr(o, "SurfaceLayout", {}) or {})
    value = fields.pop("max", "")
    if not value:
        import re
        m = re.search(r"Ra\s*([0-9.,]+)", text) or re.search(r"([0-9]+(?:[.,][0-9]+)?)", text)
        value = m.group(1) if m else ""
    return sym, value, fields


def _note_source(o):
    """(text, 3D position) of a note in the model: a FreeCAD annotation, a Draft text or label."""
    if o.TypeId == "App::Annotation":
        return "\n".join(o.LabelText or []), V(o.Position)
    t = getattr(getattr(o, "Proxy", None), "Type", "")
    if t in ("Text", "Label") and hasattr(o, "Placement"):
        lines = getattr(o, "Text", None) or getattr(o, "CustomText", None) or []
        if isinstance(lines, str):
            lines = [lines]
        return "\n".join(lines), o.Placement.Base
    return None


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def model_notes(page, views, eliminate_duplicates=True):
    """Model Items' Notes: the notes put on the model, at their place in the first view."""
    made = []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for o in _unique_objects(views):
        src = _note_source(o)
        key = "note:%s" % o.Name
        if src is None or not src[0] or key in seen:
            continue
        view = next(v for v in views if o in _model_objects(v))
        at = _sheet(view, src[1])
        body, reach = note_svg(src[0], at)
        s = svg_symbol(page, "Note", body, reach, at, "Note%d" % _count(page.Document, "Note"), "Note")
        s.addProperty("App::PropertyString", "SWText", "FreeCAD", "note text")
        s.SWText = src[0]
        s.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
        s.SWModelItemKey = key
        seen.add(key)
        made.append(s)
    return made


def model_weld_svg(bead, at, tip):
    ""



    try:
        import json
        from . import weweld
        paths = json.loads(bead.Paths or "[]")
        if not paths:
            return "", 0
        sym = weweld.symbol_of(paths[0])
    except Exception as _fw_err:
        _fw_log("drawannot.py:model weld", _fw_err)
        return "", 0
    L = 18.0
    tx, ty = _rel(at, tip)
    x0 = -L / 2 if tx < 0 else L / 2
    body = ['<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (-L / 2, L / 2, STROKE),
            _arrow(tx, ty, x0, 0)]

    def glyph(kind, below):
        kind = str(kind or "None")
        names = [kind]
        if kind.endswith(" Groove"):
            names += [kind[:-7], kind[:-7] + "-groove"]
        for n in names:
            g = _weld_glyph(n, below)
            if g:
                return g
        return ""
    for key, below in (("arrow", True), ("other", False)):
        side = sym.get(key) or {}
        if side.get("symbol", "None") == "None":
            continue
        body.append(glyph(side["symbol"], below))
        y = 4 if below else -1.5
        if side.get("size"):
            body.append('<text x="-1" y="%g" font-family="osifont, Arial" font-size="2.5" text-anchor="end">%s</text>'
                        % (y, _esc(side["size"])))
        if side.get("lp"):
            body.append('<text x="3.8" y="%g" font-family="osifont, Arial" font-size="2.5">%s</text>'
                        % (y, _esc(side["lp"])))
    if sym.get("around"):
        body.append('<circle cx="%g" cy="0" r="1.2" fill="none" stroke="#000" stroke-width="%g"/>' % (x0, STROKE))
    if sym.get("field"):
        body.append('<path d="M%g 0 L%g -5 L%g -4 L%g -3 Z" fill="#000" stroke="#000" stroke-width="%g"/>'
                    % (x0, x0, x0 + 2.5, x0, STROKE))
    if sym.get("process"):
        far = L / 2 if x0 < 0 else -L / 2
        sg = 1.0 if far > 0 else -1.0
        body.append('<polyline points="%g,%g %g,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                    % (far + sg * 2.5, -2.5, far, far + sg * 2.5, 2.5, STROKE))
        body.append('<text x="%g" y="0.9" font-family="osifont, Arial" font-size="2.5" text-anchor="%s">%s</text>'
                    % (far + sg * 3.2, "start" if sg > 0 else "end", _esc(sym["process"])))
    return "".join(body), L / 2 + _reach(at, tip)


def model_welds(page, views, eliminate_duplicates=True):
    """Model Items' Welds: each weld bead of the model, its weld symbol text on a leader to the bead."""
    made = []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for o in _unique_objects(views):
        if not (hasattr(o, "SymbolText") and hasattr(o, "Paths")):
            continue
        key = "weld:%s" % o.Name
        if key in seen:
            continue
        try:
            centre = o.Shape.BoundBox.Center if not o.Shape.isNull() else None
        except Exception:
            centre = None
        if centre is None:
            continue
        view = next(v for v in views if o in _model_objects(v))
        tip = _sheet(view, centre)
        at = (tip[0] + 14.0, tip[1] + 10.0)
        text = o.SymbolText or "Weld"
        body, reach = model_weld_svg(o, at, tip)
        if not body:
            body, reach = note_svg(text, at, tip)
        s = svg_symbol(page, "WeldSymbol", body, reach, at, "Weld Symbol%d" % _count(page.Document, "WeldSymbol"),
                       "WeldSymbol")
        s.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
        s.SWModelItemKey = key
        seen.add(key)
        made.append(s)
        if _doc_row(page.Document, "Weld Symbols", "Weld bead display", "Simplified", "weld_bead") == "Full":
            for v in views:
                if o in _model_objects(v):
                    b = bead_outline(page, v, o)
                    if b is not None:
                        made.append(b)
    return made


def drop_lost_weld_symbols(doc):
    ""

    gone = []
    syms = [o for o in doc.Objects if str(getattr(o, "SWModelItemKey", "")).startswith("weld:")]
    if not syms:
        return gone
    docs = []
    for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
        for v in page.Views:
            if not v.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            try:
                for o in DV.source_shapes(v):
                    if o.Document not in docs and o.Document is not doc:
                        docs.append(o.Document)
            except Exception as _fw_err:
                _fw_log("drawannot.py:1142", _fw_err)
    if not docs:
        return gone
    for s in syms:
        name = s.SWModelItemKey[len("weld:"):]
        if any(d.getObject(name) is not None for d in docs):
            continue
        gone.append(s.Name)
    for n in gone:
        try:
            doc.removeObject(n)
        except Exception as _fw_err:
            _fw_log("drawannot.py:1154", _fw_err)
    return gone


def bead_outline(page, view, bead):
    """Weld bead display Full: the bead's own edges drawn in the view (Simplified shows only its symbol)."""
    try:
        sh = bead.Shape
    except Exception:
        return None
    if sh is None or sh.isNull():
        return None
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    paths = []
    pts_all = []
    for e in sh.Edges:
        try:
            pts = e.discretize(24)
        except Exception:
            continue
        q = [_project(view, p) for p in pts]
        pts_all += q
        paths.append(q)
    if not pts_all:
        return None
    cx = sum(p.x for p in pts_all) / len(pts_all)
    cy = sum(p.y for p in pts_all) / len(pts_all)
    d = "".join("M" + " L".join("%g %g" % ((p.x - cx) * k, -(p.y - cy) * k) for p in q) for q in paths if len(q) > 1)
    reach = max(math.hypot((p.x - cx) * k, (p.y - cy) * k) for p in pts_all) + 1.0
    body = '<path d="%s" fill="none" stroke="#000" stroke-width="%g"/>' % (d, STROKE)
    s = svg_symbol(page, "WeldBead", body, reach, (x0 + cx * k, y0 + cy * k), "Weld Bead%d" % _count(page.Document,
                   "WeldBead"), "WeldBead")
    s.addProperty("App::PropertyString", "SWWeldBeadOf", "FreeCAD", "the model weld bead it draws")
    s.SWWeldBeadOf = "%s#%s" % (bead.Document.Name, bead.Name)
    return s


def _wizard_radii(view):
    out = []
    for o in _model_objects(view):
        if o.TypeId == "PartDesign::Hole":
            try:
                out.append(float(o.Diameter.Value if hasattr(o.Diameter, "Value") else o.Diameter) / 2.0)
            except Exception as _fw_err:
                _fw_log("drawannot.py:1199", _fw_err)
    try:        # extapps109: the holes of assembly features too
        from . import asmholecallout
        docs = []
        for o in DV.source_shapes(view):
            if o.Document not in docs:
                docs.append(o.Document)
        for doc in docs:
            out += asmholecallout.radii(doc)
    except Exception as _fw_err:
        _fw_log("drawannot.py:asmholes", _fw_err)
    return out


def _wizard_holes(view):
    """(edge index, centre, radius) of the Hole Wizard holes a view sees end on, one per centre."""
    radii = _wizard_radii(view)
    out = []
    for i, c, r in circles(view):
        if not any(abs(r - R) < 1e-4 for R in radii):
            continue
        if any((c - q).Length < 1e-6 for _, q, _ in out):
            continue
        out.append((i, c, r))
    return out


def hole_profiles(page, views, eliminate_duplicates=True):
    """Model Items' Hole Wizard Profile: the diameter of each Hole Wizard hole (once per size with Eliminate
    duplicates)."""
    made, sizes = [], set()
    for view in views:
        k = DV.view_scale(view)
        for i, c, r in _wizard_holes(view):
            if eliminate_duplicates and round(r, 4) in sizes:
                continue
            sizes.add(round(r, 4))
            dim = dimension(page, view, "Diameter", ["Edge%d" % i], (c.x * k + r * k + 6, c.y * k - r * k - 6))
            dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
            dim.SWModelItemKey = "hwprofile:%s:%d" % (view.Name, i)
            made.append(dim)
    return made


def hole_locations(page, views, eliminate_duplicates=True):
    """Model Items' Hole Wizard Locations: each Hole Wizard hole's centre located across and up from the view's
    lower left corner."""
    made = []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for view in views:
        holes = _wizard_holes(view)
        if not holes:
            continue
        verts = vertices(view)
        centres = [c for _, c, _ in holes]
        corners = [(i, p) for i, p in verts if not any(abs(p.x - c.x) < 1e-6 and abs(p.y - c.y) < 1e-6
                                                       for c in centres)]
        # the corner of the holed part itself (not of other bodies the view also shows)
        own = []
        for o in _model_objects(view):
            if o.TypeId == "PartDesign::Hole":
                try:
                    own += [_project(view, x.Point) for x in o.Shape.Vertexes]
                except Exception as _fw_err:
                    _fw_log("drawannot.py:1254", _fw_err)
        if own:
            corners = [(i, p) for i, p in corners if any(abs(p.x - q.x) < 1e-4 and abs(p.y - q.y) < 1e-4 for q in own)]
        if not corners:
            continue
        ci, cp = min(corners, key=lambda t: (round(t[1].x + t[1].y, 6), t[0]))
        corner = "Vertex%d" % ci
        k = DV.view_scale(view)
        lo_x = min(p.x for _, p in verts)
        lo_y = min(p.y for _, p in verts)
        for n, (i, c, r) in enumerate(sorted(holes, key=lambda t: (t[1].x, t[1].y))):
            cv = _vertex_near(view, c, verts)
            key = "hwloc:%s:%d" % (view.Name, i)
            if cv is None or cv == corner or key in seen:
                continue
            step = 7.0 * (n + 1)
            dx = dimension(page, view, "DistanceX", [corner, cv], ((cp.x + c.x) / 2 * k, lo_y * k - step))
            dy = dimension(page, view, "DistanceY", [corner, cv], (lo_x * k - step, (cp.y + c.y) / 2 * k))
            for dim in (dx, dy):
                dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
                dim.SWModelItemKey = key
                made.append(dim)
            seen.add(key)
    return made


SKIP_CURVE_TYPES = ("Sketcher::SketchObject", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
                    "PartDesign::CoordinateSystem", "Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint",
                    "App::Origin", "App::Line", "App::Plane", "App::Point", "PartDesign::Body", "App::Part")


def _trace(view, shape, style=1):
    """Cosmetic lines along shape's edges, as the view sees them."""
    tags = []
    for e in shape.Edges:
        try:
            pts = e.discretize(2) if type(e.Curve).__name__ == "Line" else e.discretize(32)
        except Exception:
            continue
        g = [_project(view, p) for p in pts]
        for a, b in zip(g, g[1:]):
            if (b - a).Length > 1e-6:
                tags.append(_styled(view, view.makeCosmeticLine(V(a.x, a.y, 0), V(b.x, b.y, 0)), style))
    return tags


def model_curves(page, views, kind="Curves"):
    """Model Items' Curves (the model's wires: helices, 3D curves, composite curves) or Surfaces (its surface
    bodies, by their edges), drawn in each view."""
    made = []
    for view in views:
        tags = []
        for o in _model_objects(view):
            if o.TypeId in SKIP_CURVE_TYPES or not getattr(o, "Visibility", True):
                continue
            try:
                shape = o.Shape
            except Exception:
                continue
            if shape is None or shape.isNull():
                continue
            if kind == "Curves" and not shape.Faces and shape.Edges:
                tags += _trace(view, shape)
            elif kind == "Surfaces" and shape.Faces and not shape.Solids:
                tags += _trace(view, shape)
        if tags:
            _keep(view, "SWCurveLines" if kind == "Curves" else "SWSurfaceLines", tags)
            made.append((view, tags))
    return made


class _PlacedSketch:
    """A component's sketch seen from the assembly: its global placement goes through the component's link."""

    def __init__(self, sk, comp, pl):
        self._sk, self._comp, self._pl = sk, comp, pl
        self.Name = "%s~%s" % (comp.Name, sk.Name)
        self.Label = "%s@%s" % (sk.Label, comp.Label)

    def getGlobalPlacement(self):
        return self._pl.multiply(self._sk.getGlobalPlacement())

    def __getattr__(self, name):
        return getattr(self._sk, name)


def view_components(view):
    """[(component, placement into the assembly, its document)] of an assembly view (empty for a part)."""
    out = []
    for o in DV.source_shapes(view):
        if o.TypeId != "Assembly::AssemblyObject":
            continue
        try:
            from . import asmcore
            comps = asmcore.components(o)
        except Exception:
            comps = [c for c in o.Group if c.TypeId == "App::Link"]
        for c in comps:
            linked = getattr(c, "LinkedObject", None)
            if linked is None or linked is c:
                continue
            base = o.getGlobalPlacement() if hasattr(o, "getGlobalPlacement") else o.Placement
            pl = base.multiply(c.Placement)        # an App::Link has no getGlobalPlacement
            if not bool(getattr(c, "LinkTransform", False)) and hasattr(linked, "Placement"):
                pl = pl.multiply(linked.Placement.inverse())      # the link's placement stands in for the part's
            out.append((c, pl, linked.Document))
    return out


def component_at(view, g):
    """The assembly component drawn under view geometry point g (the smallest whose outline holds it)."""
    import Part
    best = None
    for c, _pl, _doc in view_components(view):
        try:
            bb = Part.getShape(c).BoundBox
        except Exception:
            continue
        pts = [_project(view, V(x, y, z)) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
               for z in (bb.ZMin, bb.ZMax)]
        x0, x1 = min(p.x for p in pts), max(p.x for p in pts)
        y0, y1 = min(p.y for p in pts), max(p.y for p in pts)
        if x0 - 1e-6 <= g.x <= x1 + 1e-6 and y0 - 1e-6 <= g.y <= y1 + 1e-6:
            area = (x1 - x0) * (y1 - y0)
            if best is None or area < best[0]:
                best = (area, c)
    return best[1] if best else None


def component_sketches(view, comps, hidden=True):
    out = []
    for c, pl, doc in view_components(view):
        if comps is not None and c not in comps:
            continue
        for s in doc.Objects:
            if s.TypeId == "Sketcher::SketchObject":
                if not hidden and any(getattr(u, "Suppressed", False) for u in s.InList):
                    continue
                out.append(_PlacedSketch(s, c, pl))
    return out


def model_items(page, views=None, eliminate_duplicates=True, marked=True, not_marked=False, hidden=True,
                sketch_placement=False, source="Entire model", components=None):
    ""




    sections = set()
    if not views:
        views = [v for v in D.views_of(page) if v.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem")]

        # (an assembly's inner parts); what a view already has is not repeated there
        secs = [v for v in D.views_of(page) if v.TypeId == "TechDraw::DrawViewSection"]
        sections = {v.Name for v in secs}
        views = views + secs
    made, seen = [], set()
    # (part document, sketch, constraint): a part used twice shows its dimensions once, also over earlier runs
    once = _parts_shown(page) if eliminate_duplicates else set()
    if eliminate_duplicates:      # what the drawing already shows is not brought in again
        seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")}
    for view in views:
        d, x, y = D.view_frame(view)
        verts = vertices(view)
        sketches = [] if source == "Selected component" else model_sketches(view, hidden)
        if source in ("Entire model", "Selected component", "Selected feature"):
            sketches += component_sketches(view, components if source == "Selected component" else None, hidden)
        for sk in sketches:
            n = sk.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
            if abs(abs(n.dot(d)) - 1) > 1e-6:
                continue
            unmarked = set(getattr(sk, "FWNotForDrawing", []) or [])
            for ci, c in enumerate(sk.Constraints):
                if c.Type not in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter"):
                    continue
                # a driving dimension whose Mark For Drawing was unticked comes in as not marked (reviewer 11-19)
                is_marked = c.Driving and (c.Name or "#%d" % ci) not in unmarked
                if (is_marked and not marked) or (not is_marked and not not_marked):
                    continue
                key = "%s/%s:%d" % (view.Name, sk.Name, ci)
                if eliminate_duplicates and key in seen:
                    continue
                real = getattr(sk, "_sk", sk)
                same = (real.Document.Name, real.Name, ci)
                if eliminate_duplicates and same in once:
                    continue            # Eliminate duplicates: the second pin of the same part (drawings-land281)
                if view.Name in sections and any(k.endswith("/%s:%d" % (sk.Name, ci)) for k in seen):
                    continue
                try:
                    dim = _one_item(page, view, sk, c, verts, x, y)
                except Exception:
                    dim = None
                if dim is not None and sketch_placement:
                    _sketch_place(view, sk, c, dim)
                if dim is not None:
                    seen.add(key)
                    once.add(same)
                    _mark_part(dim, same)
                    dim.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
                    dim.SWModelItem = "%s.%s" % (sk.Label, c.Name or "Constraint%d" % (ci + 1))
                    dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "view/sketch:constraint")
                    dim.SWModelItemKey = key
                    try:
                        from . import drawdimlines      # the sketch's Hide Dimension Line comes along
                        if drawdimlines.sketch_hides_dim_line(sk, ci):
                            drawdimlines.set_hidden(dim, drawdimlines.DIM_LINE, True)
                    except Exception as _fw_err:
                        _fw_log("drawannot.py:1451", _fw_err)
                    _sketch_display(sk, ci, c, dim)
                    made.append(dim)
    if marked and source != "Selected component":
        made += _feature_items(page, views, seen, eliminate_duplicates, hidden, source != "Only assembly")
        made += _pattern_items(page, views, seen, eliminate_duplicates)
        made += _fillet_items(page, views, seen, eliminate_duplicates)
        made += _size_items(page, views, seen, eliminate_duplicates)
    page.Document.recompute()
    if made:
        try:
            if _stack_parallel(made):
                page.Document.recompute()
        except Exception as _fw_err:
            _fw_log("drawannot.py:model items stack", _fw_err)
        try:
            if tidy_round_items(made):
                page.Document.recompute()
        except Exception as _fw_err:
            _fw_log("drawannot.py:model items rows", _fw_err)
        try:
            from . import drawdimtools
            if drawdimtools.spread_texts(made):
                page.Document.recompute()
        except Exception as _fw_err:
            _fw_log("drawannot.py:1463", _fw_err)
    return made


def tidy_round_items(made, margin=8.0, gap=6.0):
    ""


    from . import drawdimtools as DT, drawdimlines as DL
    rows = {}
    for d in made:
        at = getattr(d, "SWRoundAt", None)
        if at is None or d.Type not in ("Radius", "Diameter"):
            continue
        v = DT.view_of(d)
        if v is None:
            continue
        rows.setdefault(v.Name, (v, []))[1].append(d)
    moved = 0
    for v, ds in rows.values():
        x0, y0, x1, y1 = DT.view_box(v)
        for side, group in ((1, [d for d in ds if d.SWRoundAt.y >= (y0 + y1) / 2.0]),
                            (-1, [d for d in ds if d.SWRoundAt.y < (y0 + y1) / 2.0])):
            row_y = (y1 + margin) if side > 0 else (y0 - margin)
            right = -1e9
            for d in sorted(group, key=lambda o: o.SWRoundAt.x):
                hw, _hh = DL.text_box(d)
                x = d.SWRoundAt.x + 0.5 * d.SWRoundAt.z
                x = max(x, right + gap + hw)
                DT.put(d, x=x, y=row_y)
                right = x + hw
                moved += 1
    return moved


def _sketch_display(sk, ci, c, dim):
    """The sketch dimension's Display Options > Show Parentheses and Show as Inspection come along to the
    drawing, as Hide Dimension Line does (they show nothing in the sketch; reviewer 11-19)."""
    flags = set(getattr(sk, "FWDimDisplay", []) or [])
    key = c.Name or "#%d" % ci
    try:
        if key + ":ShowParentheses" in flags:
            f = dim.FormatSpec or "%.2f"
            if not (f.startswith("(") and f.endswith(")")):
                dim.FormatSpec = "(%s)" % f
        if key + ":ShowAsInspection" in flags:
            if not hasattr(dim, "FWInspection"):
                dim.addProperty("App::PropertyBool", "FWInspection", "FreeCAD", "Show as Inspection")
            dim.FWInspection = True
            dim.TheoreticalExact = True
    except Exception as _fw_err:
        _fw_log("drawannot.py:sketch_display", _fw_err)


DEPTH_FEATURES = ("PartDesign::Pad", "PartDesign::Pocket")


def _parts_shown(page):
    """The part dimensions the drawing already shows, by part ((document, sketch or feature, constraint or
    property)), whichever instance of the part they were taken from (Eliminate duplicates)."""
    out = set()
    for o in page.Document.Objects:
        k = str(getattr(o, "SWModelItemPart", "") or "")
        if k.count("|") == 2:
            a, b, c = k.split("|")
            out.add((a, b, int(c) if c.isdigit() else c))
    return out


def _mark_part(dim, same):
    try:
        if "SWModelItemPart" not in dim.PropertiesList:
            dim.addProperty("App::PropertyString", "SWModelItemPart", "FreeCAD", "the part dimension it shows")
            dim.setPropertyStatus("SWModelItemPart", ["Hidden"])
        dim.SWModelItemPart = "|".join(str(x) for x in same)
    except Exception as _fw_err:
        _fw_log("drawannot.py:mark_part", _fw_err)


def _feature_items(page, views, seen, eliminate_duplicates, hidden, components=True):
    ""


    made, done = [], set()
    once = _parts_shown(page) if eliminate_duplicates else set()
    for view in views:
        d, x, y = D.view_frame(view)
        verts = vertices(view)
        sketches = list(model_sketches(view, hidden))
        if components:
            sketches += component_sketches(view, None, hidden)
        for sk in sketches:
            real = getattr(sk, "_sk", sk)
            comp = getattr(sk, "_comp", None)
            for f in real.InList:
                if f.TypeId not in DEPTH_FEATURES or getattr(f, "Profile", None) is None:
                    continue
                prof = f.Profile[0] if isinstance(f.Profile, (list, tuple)) else f.Profile
                if prof is not real:
                    continue
                for prop in ("Length", "Length2"):
                    try:
                        kind_ok = f.Type in ("Length", "TwoLengths") and (prop == "Length" or f.Type == "TwoLengths")
                        L = float(getattr(f, prop))
                    except Exception:
                        continue
                    key = "feature:%s%s.%s" % (comp.Name + "~" if comp is not None else "", f.Name, prop)
                    if not kind_ok or L <= 1e-9 or key in done or (eliminate_duplicates and key in seen):
                        continue
                    same = (f.Document.Name, f.Name, prop)
                    if eliminate_duplicates and same in once:
                        continue        # a part used twice: its depth once (drawings-land281)
                    dim = _depth_item(page, view, f, sk, L, prop == "Length2", verts, d, x, y)
                    if dim is None:
                        continue
                    done.add(key)
                    seen.add(key)
                    once.add(same)
                    _mark_part(dim, same)
                    dim.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
                    dim.SWModelItem = "%s%s.%s" % (f.Label, "@" + comp.Label if comp is not None else "", prop)
                    dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "feature dimension")
                    dim.SWModelItemKey = key
                    made.append(dim)
    return made


def _stack_parallel(dims):
    ""



    from . import drawdimtools as DT
    fm, bw = DT.offsets()
    groups = {}
    for d in dims:
        try:
            v, o = DT.view_of(d), DT.orientation(d)
        except Exception:
            continue
        if v is None or o not in ("h", "v"):
            continue
        x0, y0, x1, y1 = DT.view_box(v)
        if o == "h":
            side = "above" if float(d.Y) >= (y0 + y1) / 2 else "below"
        else:
            side = "right" if float(d.X) >= (x0 + x1) / 2 else "left"
        groups.setdefault((v.Name, o, side), (v, []))[1].append(d)
    moved = 0
    for (_vn, o, side), (v, ds) in groups.items():
        x0, y0, x1, y1 = DT.view_box(v)
        pos = [float(d.Y) if o == "h" else float(d.X) for d in ds]
        crowded = any(abs(a - b) < bw * 0.75 for i, a in enumerate(pos) for b in pos[i + 1:])
        lo, hi = (y0, y1) if o == "h" else (x0, x1)
        inside = any(lo < q < hi for q in pos)
        if not crowded and not inside:
            continue
        ds.sort(key=lambda d: abs(DT.value(d)))
        for n, d in enumerate(ds):
            off = fm + n * bw
            if o == "h":
                DT.put(d, y=(y1 + off) if side == "above" else (y0 - off))
            else:
                DT.put(d, x=(x1 + off) if side == "right" else (x0 - off))
            moved += 1
    return moved


def _feature_sizes(doc):
    ""

    out = []
    for f in doc.Objects:
        try:
            if getattr(f, "Suppressed", False):
                continue
            cls = getattr(f, "FreeWorksClass", "") or ""
            if "multishell" in cls and hasattr(f, "Value"):
                out.append((f, "feature:%s.Value" % f.Name, float(f.Value), ""))
            elif f.TypeId == "PartDesign::Thickness":
                out.append((f, "feature:%s.Value" % f.Name, float(f.Value), ""))
            elif getattr(f, "SWStyleKind", "") == "Sweep" and hasattr(f, "Diameter") and \
                    str(getattr(f, "ProfileType", "")).startswith("Circular"):
                out.append((f, "feature:%s.Diameter" % f.Name, float(f.Diameter), "\u2300"))
        except Exception as _fw_err:
            _fw_log("drawannot.py:feature sizes", _fw_err)
    return out


def _gap_points(view, value, tol=1e-3):
    """Two view points value apart across a wall: on concentric arcs whose radii differ by value, or on two
    parallel lines value apart that overlap. None when the view shows no such pair."""
    import Part
    rounds = [(i, e) for i, e in edges(view) if type(e.Curve).__name__ == "Circle"]
    for _i, a in rounds:
        for _j, b in rounds:
            ca, cb = a.Curve, b.Curve
            if (V(ca.Center.x, ca.Center.y, 0) - V(cb.Center.x, cb.Center.y, 0)).Length > tol or \
                    abs((cb.Radius - ca.Radius) - value) > tol:
                continue
            u = 0.5 * (a.FirstParameter + a.LastParameter)
            p = a.valueAt(u)
            c = V(ca.Center.x, ca.Center.y, 0)
            d = V(p.x, p.y, 0) - c
            if d.Length < 1e-9:
                continue
            d.normalize()
            q = c + d * cb.Radius
            try:
                if b.distToShape(Part.Vertex(V(q.x, q.y, b.Vertexes[0].Point.z if b.Vertexes else 0)))[0] > tol:
                    continue
            except Exception:
                continue
            return V(p.x, p.y, 0), q
    flat = [e for _i, e in edges(view) if type(e.Curve).__name__ in ("Line", "LineSegment") and len(e.Vertexes) == 2]
    for a in flat:
        pa, pb = a.Vertexes[0].Point, a.Vertexes[1].Point
        da = V(pb.x - pa.x, pb.y - pa.y, 0)
        if da.Length < 1e-9:
            continue
        da.normalize()
        n = V(-da.y, da.x, 0)
        for b in flat:
            if b is a:
                continue
            qa, qb = b.Vertexes[0].Point, b.Vertexes[1].Point
            db = V(qb.x - qa.x, qb.y - qa.y, 0)
            if db.Length < 1e-9 or abs(abs(db.normalize().dot(da)) - 1) > 1e-6:
                continue
            off = (V(qa.x, qa.y, 0) - V(pa.x, pa.y, 0)).dot(n)
            if abs(abs(off) - value) > tol:
                continue
            ta = sorted((0.0, (V(pb.x, pb.y, 0) - V(pa.x, pa.y, 0)).dot(da)))
            tb = sorted(((V(x.x, x.y, 0) - V(pa.x, pa.y, 0)).dot(da) for x in (qa, qb)))
            lo, hi = max(ta[0], tb[0]), min(ta[1], tb[1])
            if hi - lo < 4 * tol:
                continue
            m = V(pa.x, pa.y, 0) + da * (0.5 * (lo + hi))
            return m, m + n * off
    return None


def _size_items(page, views, seen, eliminate_duplicates):
    """Model Items' feature sizes (a shell's thickness, a sweep's profile diameter): a dimension across the
    wall in the first view that shows both of its sides, once per feature; skipped when no view shows it."""
    made = []
    for view in views:
        srcs = DV.source_shapes(view)
        if not srcs:
            continue
        k = DV.view_scale(view)
        for f, key, value, prefix in _feature_sizes(srcs[0].Document):
            if value <= 0 or (key in seen):
                continue
            pts = _gap_points(view, value)
            if pts is None:
                continue
            a, b = pts
            tags = []
            dim = None
            try:
                for q in (a, b):
                    tags.append(view.makeCosmeticVertex(V(q.x, q.y, 0)))
                view.Document.recompute([view])
                verts = vertices(view)
                ra, rb = _vertex_near(view, a, verts, 1e-4), _vertex_near(view, b, verts, 1e-4)
                if ra and rb and ra != rb:
                    m = (a + b) * 0.5
                    side = (b - a)
                    off = V(-side.y, side.x, 0)
                    if off.Length > 1e-9:
                        off.normalize()
                    dim = dimension(page, view, "Distance", [ra, rb], ((m.x + off.x * 8) * k + 4, (m.y + off.y * 8) * k + 4))
            except Exception as _fw_err:
                _fw_log("drawannot.py:size item", _fw_err)
                dim = None
            if dim is None:
                for t in tags:
                    try:
                        view.removeCosmeticVertex(t)
                    except Exception as _fw_err:
                        _fw_log("drawannot.py:size item drop", _fw_err)
                continue
            if prefix:
                try:
                    dim.FormatSpec = prefix + (dim.FormatSpec or "%.2f")
                except Exception as _fw_err:
                    _fw_log("drawannot.py:size prefix", _fw_err)
            seen.add(key)
            dim.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
            dim.SWModelItem = key.split(":", 1)[1].replace(f.Name, f.Label, 1)
            dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "feature dimension")
            dim.SWModelItemKey = key
            made.append(dim)
    return made


def _fillet_items(page, views, seen, eliminate_duplicates):
    ""

    made, done = [], set()
    for view in views:
        srcs = DV.source_shapes(view)
        if not srcs:
            continue
        rounds = None
        k = DV.view_scale(view)
        for f in srcs[0].Document.Objects:
            if f.TypeId != "PartDesign::Fillet" or f.Name in done:
                continue
            key = "feature:%s.Radius" % f.Name
            if eliminate_duplicates and key in seen:
                continue
            try:
                r = float(f.Radius)
            except Exception:
                continue
            if rounds is None:
                rounds = circles(view)
            hit = next(((i, c) for i, c, rr in rounds if abs(rr - r) < 1e-3), None)
            if hit is None:
                continue
            i, c = hit
            try:
                dim = dimension(page, view, "Radius", ["Edge%d" % i], (c.x * k + r * k + 6, c.y * k + r * k + 6))
            except Exception as _fw_err:
                _fw_log("drawannot.py:fillet item", _fw_err)
                continue
            if dim is None:
                continue
            done.add(f.Name)
            seen.add(key)
            dim.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
            dim.SWModelItem = "%s.Radius" % f.Label
            dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "feature dimension")
            dim.SWModelItemKey = key
            made.append(dim)
    return made


def pattern_spacing(f):
    ""
    try:
        if getattr(f, "SWStyleKind", "") == "LinearPattern":
            return float(f.Spacing1)
        if f.TypeId == "PartDesign::LinearPattern":
            n = int(f.Occurrences)
            if getattr(f, "Mode", "") == "Spacing" and hasattr(f, "Offset"):
                return float(f.Offset)
            return float(f.Length) / (n - 1) if n > 1 else None
    except Exception as _fw_err:
        _fw_log("drawannot.py:1523", _fw_err)
    return None


def _pattern_items(page, views, seen, eliminate_duplicates):
    """Model Items' pattern spacing: between the seed's hole and the next instance, in the first view that shows
    them end on."""
    made, done = [], set()
    for view in views:
        srcs = DV.source_shapes(view)
        if not srcs:
            continue
        verts = vertices(view)
        rounds = circles(view)
        k = DV.view_scale(view)
        for f in srcs[0].Document.Objects:
            sp = pattern_spacing(f)
            key = "feature:%s.Spacing" % f.Name
            if sp is None or sp <= 1e-9 or key in done or (eliminate_duplicates and key in seen):
                continue
            seeds = list(getattr(f, "Originals", []) or getattr(f, "Features", []) or [])
            dim = None
            for seed in seeds:
                prof = getattr(seed, "Profile", None)
                sk = prof[0] if isinstance(prof, (list, tuple)) else prof
                if sk is None or sk.TypeId != "Sketcher::SketchObject":
                    continue
                for g in sk.Geometry:
                    if type(g).__name__ != "Circle":
                        continue
                    c0 = _project(view, sk.getGlobalPlacement().multVec(g.Center))
                    here = [cc for _i, cc, rr in rounds if abs(rr - g.Radius) < 1e-3]
                    if not any((cc - c0).Length < 1e-3 for cc in here):
                        continue                    # this view does not show the hole end on
                    nxt = [cc for cc in here if abs((cc - c0).Length - sp) < 1e-3]
                    if not nxt:
                        continue
                    c1 = nxt[0]
                    r1, r2 = _vertex_near(view, c0, verts), _vertex_near(view, c1, verts)
                    if r1 is None or r2 is None:
                        continue
                    kind = "DistanceX" if abs(c0.y - c1.y) < 1e-6 else "DistanceY" if abs(c0.x - c1.x) < 1e-6 \
                        else "Distance"
                    mx, my = (c0.x + c1.x) / 2 * k, (c0.y + c1.y) / 2 * k
                    at = (mx, my + 8.0) if kind == "DistanceX" else (mx + 8.0, my)
                    dim = dimension(page, view, kind, [r1, r2], at)
                    break
                if dim is not None:
                    break
            if dim is None:
                continue
            done.add(key)
            seen.add(key)
            dim.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
            dim.SWModelItem = "%s.Spacing" % f.Label
            dim.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "feature dimension")
            dim.SWModelItemKey = key
            made.append(dim)
    return made


def _depth_item(page, view, f, sk, L, second, verts, d, x, y):
    """The depth L of extrusion f of sketch sk between two of view's points, or None when the view does not show
    the extrusion from the side."""
    n = sk.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
    if abs(n.dot(d)) > 1e-6:
        return None                     # seen along the extrusion: no depth to show
    try:
        pts = [vx.Point for vx in sk.Shape.Vertexes]
    except Exception:
        pts = []
    pl = getattr(sk, "_pl", None)
    if pl is not None:                  # a component's sketch: its points where the assembly has them
        pts = [pl.multVec(p) for p in pts]
    if not pts:
        return None
    mid = bool(getattr(f, "Midplane", False))
    k = DV.view_scale(view)
    for p1 in pts:
        base = p1 - n * (L / 2) if mid else p1
        for sign in ((1,) if mid else (1, -1)):
            p2 = base + n * (L * sign)
            if second:
                p2 = p1 - n * (L * sign)
            q1, q2 = _project(view, base), _project(view, p2)
            kind = "DistanceY" if abs(q1.x - q2.x) < 1e-6 else "DistanceX" if abs(q1.y - q2.y) < 1e-6 else "Distance"
            r1, r2 = _vertex_near(view, q1, verts), _vertex_near(view, q2, verts)
            if (r1 is None or r2 is None) and kind != "Distance":
                ax = "DistanceX" if kind == "DistanceX" else "DistanceY"
                r1, r2 = r1 or _vertex_in_line(q1, verts, ax), r2 or _vertex_in_line(q2, verts, ax)
            if r1 is None or r2 is None or r1 == r2:
                continue
            x0, y0, x1, y1 = DV.view_box(view)
            px, py = D.view_position(view)
            mx, my = (q1.x + q2.x) / 2 * k, (q1.y + q2.y) / 2 * k

            if kind == "DistanceY":
                at = ((x1 - px) + 8.0, my) if mx >= 0 else ((x0 - px) - 8.0, my)
            elif kind == "DistanceX":
                at = (mx, (y1 - py) + 8.0) if my >= 0 else (mx, (y0 - py) - 8.0)
            else:
                at = (mx + 8.0, my + 8.0)
            return dimension(page, view, kind, [r1, r2], at)
    return None


def _sketch_place(view, sk, c, dim):
    """Use dimension placement in sketch: the dimension sits off its edge by the sketch's label distance."""
    try:
        dist = float(getattr(c, "LabelDistance", 0.0) or 0.0)
        if abs(dist) < 1e-9:
            return
        k = DV.view_scale(view)
        dim.Y = float(dim.Y) + dist * k * (1 if dist > 0 else 1)
    except Exception as _fw_err:
        _fw_log("drawannot.py:1638", _fw_err)


def _one_item(page, view, sk, c, verts, x, y):
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    if c.Type in ("Radius", "Diameter"):
        g = sk.Geometry[c.First]
        if not hasattr(g, "Radius"):
            return None
        cg = _project(view, sk.getGlobalPlacement().multVec(g.Center))
        ref = _circle_near(view, cg, g.Radius)
        if ref is None:
            return None
        at = (cg.x * k + g.Radius * k + 6, cg.y * k + g.Radius * k + 6)
        dim = dimension(page, view, c.Type, [ref], at)
        try:
            if "SWRoundAt" not in dim.PropertiesList:
                dim.addProperty("App::PropertyVector", "SWRoundAt", "FreeCAD", "Model Items: the circle's center, radius")
                dim.setPropertyStatus("SWRoundAt", ["Hidden"])
            dim.SWRoundAt = V(cg.x * k, cg.y * k, g.Radius * k)
        except Exception as _fw_err:
            _fw_log("drawannot.py:round at", _fw_err)
        return dim
    # two points: Second given, else the First line's ends
    if c.Second >= 0 and c.Second != -2000:
        p1, p2 = _geo_point(sk, c.First, c.FirstPos), _geo_point(sk, c.Second, c.SecondPos)
    else:
        g = sk.Geometry[c.First]
        if not hasattr(g, "StartPoint"):
            return None
        if c.Type == "Distance" or c.FirstPos == 0:
            p1, p2 = _geo_point(sk, c.First, 1), _geo_point(sk, c.First, 2)
        else:
            p1 = _geo_point(sk, c.First, c.FirstPos)
            p2 = sk.getGlobalPlacement().Base       # DistanceX/Y of a point: from the sketch origin
    if p1 is None or p2 is None:
        return None
    q1, q2 = _project(view, p1), _project(view, p2)
    kind = "Distance"
    if c.Type in ("DistanceX", "DistanceY"):
        axis = sk.getGlobalPlacement().Rotation.multVec(V(1, 0, 0) if c.Type == "DistanceX" else V(0, 1, 0))
        kind = "DistanceX" if abs(axis.dot(x)) > abs(axis.dot(y)) else "DistanceY"
    elif abs(q1.x - q2.x) < 1e-6:
        kind = "DistanceY"
    elif abs(q1.y - q2.y) < 1e-6:
        kind = "DistanceX"
    r1, r2 = _vertex_near(view, q1, verts), _vertex_near(view, q2, verts)
    if (r1 is None or r2 is None) and kind in ("DistanceX", "DistanceY"):

        # shows the dimension; a horizontal / vertical one measures the same from any point in line with it
        r1 = r1 or _vertex_in_line(q1, verts, kind)
        r2 = r2 or _vertex_in_line(q2, verts, kind)
    tags = []
    if (r1 is None) != (r2 is None) and _on_revolve_axis(sk, p1 if r1 is None else p2):
        # a revolved part's sketch dimension from its axis (the mug's radius 40): the axis has no point in the

        q = q1 if r1 is None else q2
        try:
            tags.append(view.makeCosmeticVertex(V(q.x, q.y, 0)))
            view.Document.recompute([view])
            ref = _vertex_near(view, q, vertices(view), 1e-4)
            r1, r2 = (ref, r2) if r1 is None else (r1, ref)
        except Exception as _fw_err:
            _fw_log("drawannot.py:axis point", _fw_err)
    if r1 is None or r2 is None or r1 == r2:
        for t in tags:
            try:
                view.removeCosmeticVertex(t)
            except Exception as _fw_err:
                _fw_log("drawannot.py:axis point drop", _fw_err)
        return None
    mx, my = (q1.x + q2.x) / 2 * k, (q1.y + q2.y) / 2 * k
    off = 8.0
    at = (mx, my + off) if kind == "DistanceX" else (mx + off, my) if kind == "DistanceY" else (mx + off, my + off)
    return dimension(page, view, kind, [r1, r2], at)


def _on_revolve_axis(sk, p):
    """True when sketch sk makes a revolve (or groove) and global point p lies on one of its own axes."""
    real = getattr(sk, "_sk", sk)
    try:
        if not any(f.TypeId in ("PartDesign::Revolution", "PartDesign::Groove", "Part::Revolution")
                   for f in real.InList):
            return False
        local = sk.getGlobalPlacement().inverse().multVec(p)
        return abs(local.x) < 1e-6 or abs(local.y) < 1e-6
    except Exception:
        return False


def move_dimension(dim, target, at=None, copy=False):
    ""


    from . import drawselect as DS
    refs = list(dim.References2D or [])
    if not refs:
        return None
    src = refs[0][0]
    if src is target:
        return None
    page = D.page_of(target) if hasattr(D, "page_of") else None
    if page is None:
        page = next((p for p in target.InList if p.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return None
    new = None
    sk, ci = DS.model_sketch(dim)
    if sk is not None:
        d, x, y = D.view_frame(target)
        new = _one_item(page, target, sk, sk.Constraints[ci], vertices(target), x, y)
        if new is not None:
            new.addProperty("App::PropertyString", "SWModelItem", "FreeCAD", "the model dimension it shows")
            new.SWModelItem = getattr(dim, "SWModelItem", "")
            new.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "view/sketch:constraint")
            new.SWModelItemKey = "%s/%s:%d" % (target.Name, sk.Name, ci)
    else:
        same = all((App.Vector(a) - App.Vector(b)).Length < 1e-6 for a, b in
                   ((src.Direction, target.Direction), (src.XDirection, target.XDirection)))
        if same:
            new = dimension(page, target, dim.Type, [r for _v, r in refs])
            for prop in ("FormatSpec", "Arbitrary", "OverTolerance", "UnderTolerance", "EqualTolerance"):
                try:
                    setattr(new, prop, getattr(dim, prop))
                except Exception as _fw_err:
                    _fw_log("drawannot.py:1726", _fw_err)
    if new is None:
        D._status("The dimension cannot go into that view: it does not show what the dimension measures.")
        return None
    if at is not None:
        x0, y0 = D.view_position(target)
        new.X, new.Y = (at[0] - x0), (at[1] - y0)
    if not copy:
        try:
            dim.Document.removeObject(dim.Name)
        except Exception as _fw_err:
            _fw_log("drawannot.py:1737", _fw_err)
    page.Document.recompute()
    return new


def _sheet_has_assembly(page):
    """True when a view of the sheet (or, with no views yet, the drawing's model) is of an assembly."""
    views = []
    try:
        views = [v for v in D.views_of(page) if v.isDerivedFrom("TechDraw::DrawViewPart")]
    except Exception as _fw_err:
        _fw_log("drawannot.py:1748", _fw_err)
    for v in views:
        try:
            if any(getattr(o, "TypeId", "") == "Assembly::AssemblyObject" for o in DV.source_shapes(v)):
                return True
        except Exception as _fw_err:
            _fw_log("drawannot.py:1754", _fw_err)
    if views:
        return False
    doc = model_document(page)
    return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


MODEL_ITEMS_PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle/Drawings/ModelItems"


class ModelItemsPanel(D._Panel):
    TITLE = "Model Items"
    LAYER = True
    PIXMAP = "TechDraw_Dimension"
    DIMENSIONS = (("Marked for drawing", "SWModelItemsMarked", True), ("Not marked for drawing", "SWModelItemsNotMarked", False),
                  ("Instance/revolution counts", "SWModelItemsInstanceCounts", False),
                  ("Tolerance dimensions", "SWModelItemsTolerance", False),
                  ("Hole Wizard Profile", "SWModelItemsHoleProfile", False),
                  ("Hole Wizard Locations", "SWModelItemsHoleLocations", False),
                  ("Hole callouts", "SWModelItemsHoleCallouts", False))
    # Surface finish: the part's MBD surface finish symbols (features' mbdtab)
    ANNOTATIONS = (("Notes", "SWModelItemsNotes"), ("Surface finish", "SWModelItemsSurfaceFinish"),
                   ("Geometric tolerances", "SWModelItemsGtol"),
                   ("Datums", "SWModelItemsDatums"), ("Datum targets", "SWModelItemsDatumTargets"),
                   ("Welds", "SWModelItemsWelds"), ("Caterpillar", "SWModelItemsCaterpillar"),
                   ("End treatment", "SWModelItemsEndTreatment"), ("Cosmetic threads", "SWModelItemsThreads"))
    REFERENCE = (("Planes", "SWModelItemsPlanes"), ("Axes", "SWModelItemsAxes"), ("Origins", "SWModelItemsOrigins"),
                 ("Points", "SWModelItemsPoints"), ("Surfaces", "SWModelItemsSurfaces"),
                 ("Curves", "SWModelItemsCurves"))

    def build(self):
        self.say("Please select the type of model item you want to insert from the Dimensions, Annotations, or "
                 "Reference Geometry group boxes. Then graphically select a feature in the drawing view you wish to "
                 "insert model items into.")
        box, lay = D._group("Source/Destination", self.form)
        self.source = QtWidgets.QComboBox(box)
        self.source.setObjectName("SWModelItemsSource")

        self.source.addItems(["Entire model", "Selected feature", "Selected component", "Only assembly"]
                             if _sheet_has_assembly(self.page) else ["Entire model", "Selected feature"])

        last = App.ParamGet(MODEL_ITEMS_PARAM).GetString("Source", "Entire model")
        self.source.setCurrentText(last if self.source.findText(last) >= 0 else "Entire model")
        self.source.currentTextChanged.connect(
            lambda t: App.ParamGet(MODEL_ITEMS_PARAM).SetString("Source", str(t)))
        lay.addWidget(self.source)
        self.dest = QtWidgets.QListWidget(box)                # Destination view(s)
        self.dest.setObjectName("SWModelItemsDestination")
        self.dest.setProperty("swpickbox", True)
        self.dest.setMaximumHeight(56)
        self.dest.setStyleSheet("QListWidget { background: #d6ecff; }")
        self.dest.setToolTip("Destination view(s): click views on the sheet")
        lay.addWidget(self.dest)
        self.dest_views = []
        self.all_views = QtWidgets.QCheckBox("Import items into all views", box)
        self.all_views.setObjectName("SWModelItemsAllViews")
        self.all_views.setChecked(True)
        lay.addWidget(self.all_views)
        self.all_views.toggled.connect(self._dest_shown)
        self.source.currentTextChanged.connect(self._dest_shown)
        self._dest_shown()
        self.lay.addWidget(box)
        box, lay = D._group("Dimensions", self.form)
        self.dim_boxes = {}
        for text, name, on in self.DIMENSIONS:
            b = QtWidgets.QCheckBox(text, box)
            b.setObjectName(name)
            b.setChecked(on)
            lay.addWidget(b)
            self.dim_boxes[name] = b
        self.dups = QtWidgets.QCheckBox("Eliminate duplicates", box)
        self.dups.setObjectName("SWModelItemsNoDuplicates")
        self.dups.setChecked(bool(_drawing_option("Eliminate duplicate model dimensions on insert", True)))
        lay.addWidget(self.dups)
        self.lay.addWidget(box)
        box, lay = D._group("Annotations", self.form)
        self.select_all = QtWidgets.QCheckBox("Select all", box)
        self.select_all.setObjectName("SWModelItemsSelectAll")
        lay.addWidget(self.select_all)
        self.ann_boxes = {}
        for text, name in self.ANNOTATIONS:
            b = QtWidgets.QCheckBox(text, box)
            b.setObjectName(name)
            lay.addWidget(b)
            self.ann_boxes[name] = b
        self.select_all.toggled.connect(lambda on: [b.setChecked(on) for b in self.ann_boxes.values()])
        self.lay.addWidget(box)
        box, lay = D._group("Reference Geometry", self.form)
        self.ref_all = QtWidgets.QCheckBox("Select all", box)
        self.ref_all.setObjectName("SWModelItemsRefSelectAll")
        lay.addWidget(self.ref_all)
        self.ref_boxes = {}
        for text, name in self.REFERENCE:
            b = QtWidgets.QCheckBox(text, box)
            b.setObjectName(name)
            lay.addWidget(b)
            self.ref_boxes[name] = b
        self.ref_all.toggled.connect(lambda on: [b.setChecked(on) for b in self.ref_boxes.values()])
        self.lay.addWidget(box)
        box, lay = D._group("Options", self.form)
        self.hidden = QtWidgets.QCheckBox("Include items from hidden features", box)
        self.hidden.setObjectName("SWModelItemsHidden")
        self.placement = QtWidgets.QCheckBox("Use dimension placement in sketch", box)
        self.placement.setObjectName("SWModelItemsSketchPlacement")
        self.placement.setChecked(True)
        lay.addWidget(self.hidden)
        lay.addWidget(self.placement)
        self.lay.addWidget(box)

    def _dest_shown(self, *_):
        """Destination view(s) shows for Entire model / Only assembly and is always live (NO DEAD CONTROLS): a view
        clicked while Import items into all views is on turns that off and starts the destination list."""
        DL.row(self.dest, self.source.currentText() in ("Entire model", "Only assembly"))

    def sheet_click(self, p):
        ""

        src = self.source.currentText()
        v = DV.view_at(self.page, p)
        if v is None:
            return False
        if src in ("Entire model", "Only assembly"):
            if self.all_views.isChecked():
                self.all_views.setChecked(False)
            if v not in self.dest_views:
                self.dest_views.append(v)
                self.dest.addItem(v.Label)
            self.say("Destination: %s. Click more views, or OK." % ", ".join(x.Label for x in self.dest_views))
            return True
        comps = None
        if src == "Selected component":
            gx, gy = DV.to_geometry(v, p)[:2]
            comp = component_at(v, V(gx, gy, 0))
            if comp is None:
                self.say("Click a component in an assembly view.")
                return True
            comps = [comp]
        self.made += self.bring_in([v], comps)
        self.picked_any = True
        self.say("%d items inserted into %s. Select another view, or OK." % (len(self.made), v.Label))
        return True

    def views(self):
        if self.all_views.isChecked():
            return None
        if self.dest_views:
            return list(self.dest_views)
        v, _ = D.picked_view_and_edge()
        return [v] if v is not None else None

    def accept(self):
        if self.source.currentText() in ("Selected feature", "Selected component") and not self.made:
            # nothing picked yet: the PM stays and says what to pick (OK used to close it with nothing inserted)
            self.say("Select a feature in a drawing view (or a component, for Selected component), or pick Entire "
                     "model under Source.")
            return False
        return D._Panel.accept(self)

    def finish(self):
        if self.source.currentText() in ("Selected feature", "Selected component"):
            return
        self.made = self.bring_in(self.views())

    def bring_in(self, views, components=None):
        made = []
        b = self.dim_boxes
        src = self.source.currentText()
        if b["SWModelItemsMarked"].isChecked() or b["SWModelItemsNotMarked"].isChecked():
            made += model_items(self.page, views, self.dups.isChecked(), b["SWModelItemsMarked"].isChecked(),
                                b["SWModelItemsNotMarked"].isChecked(), self.hidden.isChecked(),
                                self.placement.isChecked(), src, components)
        targets = views or [v for v in D.views_of(self.page)
                            if v.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem")]
        if b["SWModelItemsHoleCallouts"].isChecked():
            made += hole_callouts(self.page, targets, self.dups.isChecked())
        if b["SWModelItemsInstanceCounts"].isChecked():
            made += instance_counts(self.page, targets)
        if self.ref_boxes["SWModelItemsOrigins"].isChecked():
            origin_marks(self.page, targets)
        if self.ref_boxes["SWModelItemsPlanes"].isChecked():
            plane_traces(self.page, targets)
        if self.ref_boxes["SWModelItemsPoints"].isChecked():
            datum_points(self.page, targets)
        if self.ref_boxes["SWModelItemsAxes"].isChecked():
            for v in targets:
                try:
                    for i, c, r in circles(v):
                        if _is_hole_circle(v, c, r):
                            center_mark(v, c, r)
                except Exception:
                    continue
        if self.ann_boxes["SWModelItemsThreads"].isChecked():
            cosmetic_threads(self.page, targets)
        dups = self.dups.isChecked()
        if b["SWModelItemsHoleProfile"].isChecked():
            made += hole_profiles(self.page, targets, dups)
        if b["SWModelItemsHoleLocations"].isChecked():
            made += hole_locations(self.page, targets, dups)
        kinds = [k for name, ks in (("SWModelItemsDatums", ("Datum",)), ("SWModelItemsDatumTargets", ("DatumTarget",)),
                                    ("SWModelItemsGtol", ("GTol",)))
                 if self.ann_boxes[name].isChecked() for k in ks]
        if b["SWModelItemsTolerance"].isChecked():
            kinds += list(PMI_DIMENSIONS)
        if self.ann_boxes["SWModelItemsSurfaceFinish"].isChecked():
            kinds.append("SurfaceFinish")
        if self.ann_boxes["SWModelItemsNotes"].isChecked():
            kinds.append("Note")                 # MBD notes (not 3D balloons or tables)
        if self.ann_boxes["SWModelItemsWelds"].isChecked():
            kinds.append("Weld")
        if kinds:
            made += pmi_items(self.page, targets, kinds, dups)
        if self.ann_boxes["SWModelItemsNotes"].isChecked():
            made += model_notes(self.page, targets,     # extapps83: System Options' notes row too
                                dups and bool(_drawing_option("Eliminate duplicate model notes on insert", True)))
        if self.ann_boxes["SWModelItemsWelds"].isChecked():
            made += model_welds(self.page, targets, dups)
        if self.ann_boxes["SWModelItemsCaterpillar"].isChecked():
            made += model_caterpillars(self.page, targets, dups)
        if self.ann_boxes["SWModelItemsEndTreatment"].isChecked():
            made += model_end_treatments(self.page, targets, dups)
        if self.ref_boxes["SWModelItemsCurves"].isChecked():
            model_curves(self.page, targets, "Curves")
        if self.ref_boxes["SWModelItemsSurfaces"].isChecked():
            model_curves(self.page, targets, "Surfaces")
        part_styled(made)
        self.doc.recompute()
        return made


def _model_doc(dim):
    """The part (or assembly) document behind a dimension's view."""
    refs = getattr(dim, "References2D", None) or []
    view = refs[0][0] if refs else None
    for s in _fw_xs(view) + list(getattr(view, "Source", []) or []):
        if s is not None and s.Document is not dim.Document:
            return s.Document
        if s is not None:
            return s.Document
    return None


def _places(n):
    return "None" if n <= 0 else "." + "123456"[:min(n, 6)]


def part_styled(made):
    ""

    try:
        from . import docstyle, drawdimpm
    except Exception:
        return 0
    n = 0
    for dim in made:
        if getattr(dim, "TypeId", "") != "TechDraw::DrawViewDimension":
            continue
        doc = _model_doc(dim)
        if doc is None or not any(docstyle._is_set(doc, "Dimensions", t) for t in
                                  ("Primary precision", "Dual dimensions display", "Dual precision")):
            continue
        st = docstyle.part_style(doc)
        opts = drawdimpm.options_of(dim)
        if not opts and (float(getattr(dim, "OverTolerance", 0) or 0) or float(getattr(dim, "UnderTolerance", 0) or 0)):
            continue                      # a toleranced model dimension keeps what it came with
        opts.update(precision=_places(st["precision"]), dual=st["dual"], dual_precision=_places(st["dual_precision"]),
                    dual_place="Below" if st["dual_position"] in ("Bottom", "Below") else "To right")
        try:
            drawdimpm.apply(dim, **opts)
            n += 1
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: part dimension style: %s\n" % error)
    return n


# --------------------------------------------------------------------------- Hole Callout
def wizard_hole(view, centre, radius):
    """The PartDesign::Hole behind a view circle: its own cut (AddSubShape) has a cylinder of that radius on
    the circle's axis."""
    d, x, y = D.view_frame(view)
    c3 = DV.model_centre(view) + x * centre.x + y * centre.y
    for o in _model_objects(view):
        # PartDesign Holes, and the Hole Wizard's own features (slots, legacy holes) that keep its choices;

        src = o
        if o.TypeId in PATTERNS:
            src = next((h for h in getattr(o, "Originals", []) or []
                        if h.TypeId == "PartDesign::Hole" or getattr(h, "HoleWizardSpec", "")), None)
            if src is None:
                continue
        elif o.TypeId != "PartDesign::Hole" and not getattr(o, "HoleWizardSpec", ""):
            continue
        try:
            if o is not src:
                tool = _pattern_new_faces(o)
            else:
                tool = o.AddSubShape.copy()
            body = o.getParentGeoFeatureGroup()
            if body is not None and not body.Placement.isIdentity():
                tool.transformShape(body.Placement.toMatrix())     # body coordinates to the part's
        except Exception:
            continue
        for f in tool.Faces:
            s = f.Surface
            kind = type(s).__name__
            if kind == "Cylinder":
                if abs(s.Radius - radius) > 1e-4:
                    continue
                centre = s.Center
            elif kind == "Cone":        # a tapered tap: its circle in the view is one end of the cone
                rs = [e.Curve.Radius for e in f.Edges if type(e.Curve).__name__ == "Circle"]
                if not any(abs(r - radius) < 1e-4 for r in rs):
                    continue
                centre = s.Apex
            else:
                continue
            ax = D._unit(s.Axis)
            off = (centre - c3) - ax * (centre - c3).dot(ax)
            if abs(abs(ax.dot(d)) - 1) < 1e-4 and off.Length < 1e-3:
                return src
    return None


def _pattern_new_faces(o):
    """The faces a pattern feature made (in its shape, not in its base feature's): its hole copies."""
    base = getattr(o, "BaseFeature", None)
    old = [f for f in base.Shape.Faces] if base is not None else []
    new = [f for f in o.Shape.Faces if not any(f.isSame(g) or (abs(f.Area - g.Area) < 1e-6 and
                                                              (f.CenterOfMass - g.CenterOfMass).Length < 1e-6)
                                               for g in old)]
    import Part
    return Part.Compound(new)        # body coordinates, as AddSubShape (wizard_hole moves it to the part's)


PATTERNS = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored",
            "PartDesign::MultiTransform")


def pattern_copies(hole):
    """How many times the patterns and mirrors of hole repeat it (1 when none): LinearPattern / PolarPattern
    Occurrences, Mirrored 2, MultiTransform its transformations multiplied."""
    n = 1
    for o in {x.Name: x for x in (getattr(hole, "InList", []) or [])}.values():
        if o.TypeId not in PATTERNS or hole not in (getattr(o, "Originals", []) or []):
            continue
        if o.TypeId == "PartDesign::MultiTransform":
            m = 1
            for t in getattr(o, "Transformations", []) or []:
                m *= 2 if t.TypeId == "PartDesign::Mirrored" else max(1, int(getattr(t, "Occurrences", 1)))
        elif o.TypeId == "PartDesign::Mirrored":
            m = 2
        else:
            m = max(1, int(getattr(o, "Occurrences", 1)))
        n *= m
    return n


def wizard_callout(view, centre, radius):
    """The Hole Wizard's own callout ("4X ⌀6.60 THRU ALL", "⌴ ⌀11.00 ↧ 6.40", "M6x1 - 6H ↧ 12.00") from
    features' holespec, as dimension text; None for a hole the Hole Wizard did not make."""
    try:
        from . import holespec
        hole = wizard_hole(view, centre, radius)
        if hole is None:        # extapps109: a hole an assembly feature made (Hole Wizard, Simple Hole, Hole Series)
            from . import asmholecallout
            text = asmholecallout.callout(view, centre, radius, D, DV)
            return text
        text = holespec.callout_text(hole) if hole is not None else None
        if text is None and hole is not None:
            text = thread_callout(hole)
        if text is None and hole is not None:
            text = legacy_callout(hole)
    except Exception:
        return None
    return text.replace("%", "%%") if text else None


def thread_callout(hole):
    ""


    if getattr(hole, "TypeId", "") != "PartDesign::Hole":
        return None
    cut = str(getattr(hole, "HoleCutType", "None") or "None")
    if not getattr(hole, "Threaded", False) and cut == "None":
        return None
    val = lambda prop, f=0.0: float(getattr(getattr(hole, prop, f), "Value", getattr(hole, prop, f)))
    through = str(getattr(hole, "DepthType", "")).replace(" ", "").lower() == "throughall"
    first = "⌀%.2f %s" % (val("Diameter"), "THRU ALL" if through else "↧ %.2f" % val("Depth"))
    lines = [first]
    if getattr(hole, "Threaded", False):
        size = str(getattr(hole, "ThreadSize", "")).strip()
        if size and size.lower() != "none":
            cls = str(getattr(hole, "ThreadClass", "") or "").strip()
            tdepth = val("ThreadDepth", val("Depth"))
            full = str(getattr(hole, "ThreadDepthType", "")).lower() in ("hole depth", "")
            second = size + (" - " + cls if cls and cls.lower() != "none" else "")
            second += " THRU ALL" if through and full else " ↧ %.2f" % (val("Depth") if full else tdepth)
            lines.append(second)
    if cut in ("Counterbore", "Counterdrill"):
        lines.append("⌴ ⌀%.2f ↧ %.2f" % (val("HoleCutDiameter"), val("HoleCutDepth")))
    elif cut == "Countersink":
        lines.append("⌵ ⌀%.2f X %g°" % (val("HoleCutDiameter"), val("HoleCutCountersinkAngle", 90.0)))
    if len(lines) == 1 and cut == "None":
        return None
    try:
        from . import holespec
        count = holespec.instances(hole)
    except Exception:
        count = 1
    count *= pattern_copies(hole)
    if count > 1:
        lines[0] = "%dX %s" % (count, lines[0])
    return "\n".join(lines)


def legacy_callout(hole):
    """A Legacy Hole's callout, as the Hole Wizard writes the others: "⌀10.00 ↧ 20.00" or "⌀10.00 THRU ALL",
    and the counterbore / countersink line under it."""
    if not hasattr(hole, "Diameter") or not hasattr(hole, "HoleType"):
        return None
    val = lambda prop: float(getattr(getattr(hole, prop), "Value", getattr(hole, prop)))
    first = "⌀%.2f %s" % (val("Diameter"), "THRU ALL" if getattr(hole, "ThroughAll", False)
                          else "↧ %.2f" % val("Depth"))
    lines = [first]
    kind = str(hole.HoleType)
    if kind in ("Counterbored", "Counterdrilled", "Counterbore"):
        lines.append("⌴ ⌀%.2f ↧ %.2f" % (val("HeadDiameter"), val("HeadDepth")))
    elif kind in ("Countersunk", "Countersink"):
        lines.append("⌵ ⌀%.2f X %g°" % (val("HeadDiameter"), val("HeadAngle")))
    elif kind == "Tapered" and hasattr(hole, "TaperAngle"):
        lines[0] += " TAPER %g°" % val("TaperAngle")
    try:
        from . import holespec
        count = holespec.instances(hole)
    except Exception:
        count = 1
    if count > 1:
        lines[0] = "%dX %s" % (count, lines[0])
    return "\n".join(lines)


def hole_text(view, centre, radius):
    """THRU or the depth of the hole behind a view circle (from the model's cylinder faces); a Hole Wizard
    hole's own callout first (Document Properties > Dimensions > Hole Callout: Use per standard; Show hole depth)."""
    doc = view.Document
    depth = bool(_doc_row(doc, "Hole Callout", "Show hole depth", True))
    wiz = wizard_callout(view, centre, radius) if _doc_row(doc, "Hole Callout", "Use per standard", True) else None
    if wiz:
        return wiz if depth else _no_depth(wiz)
    text = _hole_text(view, centre, radius)
    return text if depth else _no_depth(text)


def _no_depth(text):
    """A callout without its depths (Show hole depth off): every "↧ value" left out."""
    lines = [re.sub(r"\s*↧\s*[^\s]+", "", ln).rstrip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln.strip())


def _hole_text(view, centre, radius):
    d, x, y = D.view_frame(view)
    c3 = DV.model_centre(view) + x * centre.x + y * centre.y
    best = None
    for o in DV.source_shapes(view):
        try:
            shape = o.Shape
        except Exception:
            continue
        for f in shape.Faces:
            s = f.Surface
            if type(s).__name__ != "Cylinder" or abs(s.Radius - radius) > 1e-4:
                continue
            ax = D._unit(s.Axis)
            if abs(abs(ax.dot(d)) - 1) > 1e-4:
                continue
            off = (s.Center - c3) - ax * (s.Center - c3).dot(ax)
            if off.Length > 1e-3:
                continue
            if not _is_hole(f):
                continue                                # a boss's outer face, not a hole
            ts = [ax.dot(v.Point) for v in f.Vertexes] or [0.0]
            length = max(ts) - min(ts)
            span = [ax.dot(v.Point) for v in shape.Vertexes]
            through = length >= (max(span) - min(span)) - 1e-4
            if not through:
                # THRU: both ends of the hole open to air (a hole through a base under a taller boss). A drilled
                # hole's cone point is air too: the axis is looked along past it, 1.5 radii from each end
                base = s.Center - ax * s.Center.dot(ax)
                steps = [0.05] + [s.Radius * k / 4.0 for k in range(1, 7)]
                try:
                    ends = [base + ax * (min(ts) - e) for e in steps] + [base + ax * (max(ts) + e) for e in steps]
                    through = not any(shape.isInside(p, 1e-6, True) for p in ends)
                except Exception:
                    pass
            best = (through, length)
    if best is None:
        return "⌀%.2w"
    through, length = best
    return "⌀%.2w THRU" if through else "⌀%%.2w ↧ %g" % round(length, 4)


class SideHole:
    ""


    def __init__(self, face, shape, radius, edges):
        self.face, self.shape, self.radius, self.edges = face, shape, radius, edges

    def text(self, digits=2, view=None):

        wiz = self.wizard_text(view) if view is not None else None
        if wiz:
            return wiz
        ax = D._unit(self.face.Surface.Axis)
        ts = [ax.dot(v.Point) for v in self.face.Vertexes] or [0.0]
        length = max(ts) - min(ts)
        span = [ax.dot(v.Point) for v in self.shape.Vertexes] or [0.0]
        w = "%%.%dw" % digits
        through = length >= (max(span) - min(span)) - 1e-4
        if not through:
            # THRU when both ends open to air: a drill under a counterbore / countersink is shorter than the part
            c = self.face.Surface.Center
            base = c - ax * c.dot(ax)
            steps = [0.05] + [self.radius * k / 4.0 for k in range(1, 7)]
            try:
                ends = [base + ax * (min(ts) - e) for e in steps] + [base + ax * (max(ts) + e) for e in steps]
                through = not any(self.shape.isInside(p, 1e-6, True) for p in ends)
            except Exception:
                pass
        if through:
            return "⌀%s THRU" % w
        return "⌀%s ↧ %.*f" % (w, digits, length)

    def wizard_text(self, view):
        """The Hole Wizard callout of the hole this side face belongs to (its cut has a cylinder of the same
        radius on the same axis line), else None."""
        s0 = self.face.Surface
        a0 = D._unit(s0.Axis)
        for o in _model_objects(view):
            src = o
            if o.TypeId in PATTERNS:
                continue                       # a pattern's copies: the original hole's line is checked itself
            if o.TypeId != "PartDesign::Hole" and not getattr(o, "HoleWizardSpec", ""):
                continue
            try:
                tool = o.AddSubShape.copy()
                body = o.getParentGeoFeatureGroup()
                if body is not None and not body.Placement.isIdentity():
                    tool.transformShape(body.Placement.toMatrix())
            except Exception:
                continue
            for f in tool.Faces:
                s = f.Surface
                if type(s).__name__ != "Cylinder" or abs(s.Radius - s0.Radius) > 1e-4:
                    continue
                ax = D._unit(s.Axis)
                off = (s.Center - s0.Center) - a0 * (s.Center - s0.Center).dot(a0)
                if abs(abs(ax.dot(a0)) - 1) < 1e-4 and off.Length < 1e-3:
                    try:
                        from . import holespec
                        text = holespec.callout_text(src) or thread_callout(src) or legacy_callout(src)
                    except Exception:
                        text = None
                    return text.replace("%", "%%") if text else None
        return None


def _is_hole(face):
    """A cylinder face that bounds a hole (its normal points to its axis), not a boss or a shaft."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        u, v = (u0 + u1) / 2, (v0 + v1) / 2
        pt, n = face.valueAt(u, v), face.normalAt(u, v)
        s = face.Surface
        ax = D._unit(s.Axis)
        rad = (pt - s.Center) - ax * (pt - s.Center).dot(ax)
        return n.dot(rad) < 0
    except Exception:
        return False


def side_hole_at(view, g, tol):
    """The hole whose side silhouette line is at geometry point g (within tol): a SideHole with the two lines'
    edge indices, else None. The hole's axis lies in the view plane; its two lines are parallel to the axis and
    one diameter apart (a section's centre may differ from the model's, so the pair is found by its spacing)."""
    hit = line_at(view, g, tol)
    if hit is None:
        return None
    i, a, b = hit
    d, x, y = D.view_frame(view)
    ux, uy = b.x - a.x, b.y - a.y
    L = math.hypot(ux, uy) or 1.0
    ux, uy = ux / L, uy / L
    lines = []
    for j, e in edges(view):
        if j == i or type(e.Curve).__name__ not in ("Line", "LineSegment") or len(e.Vertexes) < 2:
            continue
        p, q = e.Vertexes[0].Point, e.Vertexes[-1].Point
        vx, vy = q.x - p.x, q.y - p.y
        lv = math.hypot(vx, vy) or 1.0
        if abs(vx / lv * uy - vy / lv * ux) > 1e-3:
            continue                                   # not parallel
        gap = abs((p.x - a.x) * uy - (p.y - a.y) * ux)
        t = sorted(((p.x - a.x) * ux + (p.y - a.y) * uy, (q.x - a.x) * ux + (q.y - a.y) * uy))
        if t[1] < -1e-6 or t[0] > L + 1e-6:
            continue                                   # side by side lines only
        lines.append((gap, j, lv))
    from . import drawviews as DV_
    try:
        k = float(DV_.view_scale(view)) or 1.0
    except Exception:
        k = 1.0
    best = None
    for o in DV.source_shapes(view):
        try:
            shape = o.Shape
        except Exception:
            continue
        for f in shape.Faces:
            srf = f.Surface
            if type(srf).__name__ != "Cylinder" or not _is_hole(f):
                continue
            ax = D._unit(srf.Axis)
            if abs(ax.dot(d)) > 1e-3:
                continue
            avx, avy = ax.dot(x), ax.dot(y)
            n = math.hypot(avx, avy) or 1.0
            if abs(ux * avy / n - uy * avx / n) > 1e-3:
                continue                               # not along the hole's axis
            ts = [ax.dot(v.Point) for v in f.Vertexes] or [0.0]
            room = (max(ts) - min(ts)) * k + max(tol, 1e-3)    # a hole's side lines are no longer than the hole
            if L > room:
                continue                               # (the outline of the part beside a hole is not one)
            for gap, j, lj in lines:
                err = abs(gap - 2 * srf.Radius * k)          # the view's lines are drawn at its scale
                if lj > room:
                    continue
                if err < max(1e-3, srf.Radius * k * 1e-3) and (best is None or err < best[0]):
                    best = (err, SideHole(f, shape, srf.Radius, (i, j)))
    return best[1] if best else None


TOLERANCE_TYPES = ("None", "Basic", "Bilateral", "Symmetric")
PRECISIONS = (".1", ".12", ".123", ".1234")


def apply_tolerance(dim, kind, upper=0.0, lower=0.0):
    ""
    if "SWTolerance" not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", "SWTolerance", "FreeCAD", "tolerance type")
    dim.SWTolerance = kind
    try:
        dim.TheoreticalExact = kind == "Basic"
        if kind == "Symmetric":
            dim.EqualTolerance = True
            dim.OverTolerance = abs(upper)
        elif kind == "Bilateral":
            dim.EqualTolerance = False
            dim.OverTolerance = upper
            dim.UnderTolerance = lower
        else:
            dim.EqualTolerance = True
            dim.OverTolerance = 0.0
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tolerance: %s\n" % error)


def callout_text(view, centre, radius, digits=2, count=False):
    """A hole callout's text: the hole's own (hole_text) at digits decimals, "nX" in front for count."""
    own = hole_text(view, centre, radius)
    text = own.replace("%.2w", "%%.%dw" % digits)
    if not wizard_callout(view, centre, radius):

        text = re.sub(r"↧ (\d+(?:\.\d+)?)", lambda m: "↧ %.*f" % (digits, float(m.group(1))), text)
    if count and not re.match(r"\d+X ", text):      # the Hole Wizard's callout has its own count
        same = []
        for i, cc, rr in circles(view):
            if abs(rr - radius) < 1e-6 and not any((cc - q).Length < 1e-6 for q in same):
                # the same hole only: a counterbore's or a countersink's drill circle is not one of them
                if (cc - centre).Length < 1e-6 or hole_text(view, cc, rr) == own:
                    same.append(cc)
        if len(same) > 1:
            text = "%dX %s" % (len(same), text)
    return text


def mark_callout(dim, digits=2, count=False):
    """Remembers how a callout's text was made, so it follows the hole (refresh_hole_callouts)."""
    for name, kind, value in (("SWCalloutAuto", "App::PropertyString", dim.FormatSpec),
                              ("SWCalloutDigits", "App::PropertyInteger", int(digits)),
                              ("SWCalloutCount", "App::PropertyBool", bool(count))):
        if name not in dim.PropertiesList:
            dim.addProperty(kind, name, "FreeCAD", "hole callout text as made")
            dim.setPropertyStatus(name, "Hidden")
        setattr(dim, name, value)
    try:
        vo = dim.ViewObject
        if dim.Type == "Diameter" and vo is not None and "RenderingExtent" in vo.PropertiesList and \
                vo.RenderingExtent not in ("Confined", "Minimal"):
            vo.RenderingExtent = "Confined"
    except Exception as _fw_err:                # on to the centre (Reduced) or across to a second arrow (Normal)
        _fw_log("drawannot.py:mark_callout", _fw_err)



CALLOUT_VARIABLES = (("<NUM_INST>", "Number of instances (nX)"), ("<MOD-DIAM>", "Diameter symbol"),
                     ("<HOLE-DIAM>", "Hole diameter"), ("<MOD-DEPTH>", "Depth symbol"),
                     ("<HOLE-DEPTH>", "Hole depth"), ("<THRU>", "THRU (a through hole)"),
                     ("<CBORE-DIAM>", "Counterbore diameter"), ("<CBORE-DEPTH>", "Counterbore depth"),
                     ("<CSK-DIAM>", "Countersink diameter"), ("<CSK-ANGLE>", "Countersink angle"),
                     ("<THREAD>", "Thread (M6x1 - 6H)"), ("<HOLE-TEXT>", "The whole callout as made"))
_VAR = re.compile(r"<(NUM_INST|MOD-DIAM|HOLE-DIAM|MOD-DEPTH|HOLE-DEPTH|THRU|CBORE-DIAM|CBORE-DEPTH|CSK-DIAM|CSK-ANGLE|"
                  r"THREAD|HOLE-TEXT)>")


def callout_values(view, centre, radius, digits=2):
    """{variable: value} of the hole behind a view circle, for the callout variables."""
    text = callout_text(view, centre, radius, digits, True)
    plain = text.replace("%%", "%")
    lines = plain.split("\n")
    m = re.match(r"(\d+)X ", plain)
    vals = {"<NUM_INST>": m.group(1) + "X" if m else "", "<MOD-DIAM>": "⌀", "<MOD-DEPTH>": "",
            "<HOLE-DIAM>": "%%.%dw" % digits, "<THRU>": "THRU" if "THRU" in plain else "", "<HOLE-TEXT>": text}
    first = re.sub(r"^\d+X ", "", lines[0])
    d = re.search(r"↧\s*([\d.]+)", first)
    vals["<HOLE-DEPTH>"] = d.group(1) if d else ""
    vals["<MOD-DEPTH>"] = "↧" if d else ""          # the depth symbol goes with a depth
    t = re.search(r"(M[\d.]+x[\d.]+(?:\s*-\s*\w+)?)", plain)
    vals["<THREAD>"] = t.group(1) if t else ""
    for ln in lines[1:]:
        cb = re.search(r"⌴\s*⌀\s*([\d.]+)(?:\s*↧\s*([\d.]+))?", ln)
        if cb:
            vals["<CBORE-DIAM>"], vals["<CBORE-DEPTH>"] = cb.group(1), cb.group(2) or ""
        cs = re.search(r"⌵\s*⌀\s*([\d.]+)(?:\s*X\s*([\d.]+°?))?", ln)
        if cs:
            vals["<CSK-DIAM>"], vals["<CSK-ANGLE>"] = cs.group(1), cs.group(2) or ""
    for k, _t in CALLOUT_VARIABLES:
        vals.setdefault(k, "")
    return vals


def expand_callout(fmt, vals):
    """A callout text with variables -> the dimension's text (a variable with no value leaves no gap)."""
    out = _VAR.sub(lambda m: vals.get(m.group(0), ""), fmt)
    out = "\n".join(re.sub(r"  +", " ", ln).strip() for ln in out.split("\n"))
    return "\n".join(ln for ln in out.split("\n") if ln)


def has_variables(text):
    return bool(_VAR.search(text or ""))


def set_callout_format(dim, fmt):
    """The callout's text with variables: it follows the hole with the text the user wrote round them."""
    if "SWCalloutFormat" not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", "SWCalloutFormat", "FreeCAD", "hole callout text with variables")
        dim.setPropertyStatus("SWCalloutFormat", "Hidden")
    dim.SWCalloutFormat = fmt or ""
    _CALLOUT_SIG.pop((dim.Document.Name, dim.Name), None)


class CalloutVariablesDialog(QtWidgets.QDialog):
    """Callout Variables: the variables and the hole's values; a double-click (or Insert) puts one in the text."""
    ASK = []           # checks: the variable picked at once

    def __init__(self, vals=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWCalloutVariables")
        self.setWindowTitle("Callout Variables")
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QTreeWidget(self)
        self.list.setObjectName("SWCalloutVariablesList")
        self.list.setHeaderLabels(["Variable", "Description", "Value"])
        for k, t in CALLOUT_VARIABLES:
            v = (vals or {}).get(k, "")
            QtWidgets.QTreeWidgetItem(self.list, [k, t, v.replace("%.2w", "(value)") if "%" in v else v])
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.list)
        bb = QtWidgets.QDialogButtonBox(self)
        bb.addButton("Insert", QtWidgets.QDialogButtonBox.AcceptRole)
        bb.addButton(QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def picked(self):
        it = self.list.currentItem()
        return it.text(0) if it is not None else None

    @classmethod
    def pick(cls, vals=None):
        if cls.ASK:
            return cls.ASK.pop(0)
        dlg = cls(vals)
        return dlg.picked() if dlg.exec_() == QtWidgets.QDialog.Accepted else None


_CALLOUT_SIG = {}


def refresh_hole_callouts(doc):
    ""

    changed = []
    for dim in doc.Objects:
        if not getattr(dim, "SWHoleCallout", False) or dim.TypeId != "TechDraw::DrawViewDimension":
            continue
        try:
            if "SWCalloutAuto" not in dim.PropertiesList:          # made before callouts followed their holes
                m = re.search(r"%\.(\d)w", dim.FormatSpec or "")
                mark_callout(dim, int(m.group(1)) if m else 2, bool(re.match(r"\d+X ", dim.FormatSpec or "")))
            fmt = getattr(dim, "SWCalloutFormat", "") or ""
            if dim.FormatSpec != dim.SWCalloutAuto:
                continue                   # typed over: left alone
            view, sub = dim.References2D[0][0], dim.References2D[0][1][0] if isinstance(
                dim.References2D[0][1], (list, tuple)) else dim.References2D[0][1]
            e = view.getEdgeByIndex(int(sub[4:]))
            cv = e.Curve
            if type(cv).__name__ != "Circle":
                continue
            shapes = []
            for o in DV.source_shapes(view):
                try:
                    shapes.append(o.Shape.hashCode())
                except Exception as _fw_err:
                    _fw_log("drawannot.py:2485", _fw_err)
            sig = (round(cv.Radius, 6), round(cv.Center.x, 6), round(cv.Center.y, 6), tuple(shapes))
            key = (doc.Name, dim.Name)
            if _CALLOUT_SIG.get(key) == sig:
                continue
            _CALLOUT_SIG[key] = sig
            c0 = V(cv.Center.x, cv.Center.y, 0)
            text = expand_callout(fmt, callout_values(view, c0, cv.Radius, dim.SWCalloutDigits)) if fmt else \
                callout_text(view, c0, cv.Radius, dim.SWCalloutDigits, dim.SWCalloutCount)
            if text != dim.FormatSpec:
                set_text(dim, text)
                dim.SWCalloutAuto = text
                changed.append(dim)
        except Exception:
            continue
    if changed:
        doc.recompute()
    return changed


class HoleCalloutPanel(D._Panel):
    TITLE = "Hole Callout"
    LAYER = True
    PIXMAP = "TechDraw_Balloon"

    def build(self):
        from . import drawpmparts as PP
        self.say("Click the edge of a hole in a view, then click where the callout goes.")
        PP.style_group(self)
        box, lay = D._group("Tolerance/Precision", self.form)
        grid = QtWidgets.QGridLayout()
        self.tol_type = QtWidgets.QComboBox(box)
        self.tol_type.setObjectName("SWHoleTolType")
        self.tol_type.addItems(TOLERANCE_TYPES)
        self.tol_max = QtWidgets.QDoubleSpinBox(box)
        self.tol_max.setObjectName("SWHoleTolMax")
        self.tol_min = QtWidgets.QDoubleSpinBox(box)
        self.tol_min.setObjectName("SWHoleTolMin")
        for w in (self.tol_max, self.tol_min):
            w.setDecimals(4)
            w.setRange(-1000, 1000)
            w.setSuffix("mm")
        self.tol_max.setValue(0.1)
        self.tol_min.setValue(-0.1)
        self.precision = QtWidgets.QComboBox(box)
        self.precision.setObjectName("SWHolePrecision")
        self.precision.addItems(PRECISIONS)
        self.precision.setCurrentText(_doc_row(self.doc, "Hole Callout", "Primary precision", ".12",
                                               "pm:Hole Callout:SWHolePrecision"))
        for n, (lab, w) in enumerate((("Tolerance:", self.tol_type), ("Maximum variation:", self.tol_max),
                                      ("Minimum variation:", self.tol_min), ("Precision:", self.precision))):
            grid.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Dimension Text", self.form)
        self.count = QtWidgets.QCheckBox("Instance count (2X)", box)
        self.count.setObjectName("SWHoleCount")
        self.count.setChecked(True)
        lay.addWidget(self.count)

        self.text = QtWidgets.QPlainTextEdit(box)
        self.text.setObjectName("SWHoleText")
        self.text.setMaximumHeight(56)
        self.text.setPlaceholderText("The callout text (after the first callout is placed)")
        self.text.hide()                    # shown once a callout is placed (a greyed box is a dead control)
        lay.addWidget(self.text)
        row = QtWidgets.QHBoxLayout()
        self.variables = QtWidgets.QPushButton("Callout variables...", box)
        self.variables.setObjectName("SWHoleVariables")
        self.variables.setToolTip("Insert a variable (the hole's diameter, depth, count...) into the callout text: "
                                  "text with variables follows the hole")
        self.variables.hide()
        self.variables.clicked.connect(self.insert_variable)
        row.addWidget(self.variables)
        self.text_apply = QtWidgets.QPushButton("Apply text", box)
        self.text_apply.setObjectName("SWHoleTextApply")
        self.text_apply.hide()
        self.text_apply.clicked.connect(self.retext)
        row.addWidget(self.text_apply)
        lay.addLayout(row)
        self.lay.addWidget(box)
        for w in (self.tol_type, self.precision):
            w.currentTextChanged.connect(self.restyle)
        for w in (self.tol_max, self.tol_min):
            w.valueChanged.connect(self.restyle)
        self.count.toggled.connect(self.restyle)
        self._tol_rows = {}
        for n, w in ((1, self.tol_max), (2, self.tol_min)):
            item = grid.itemAtPosition(n, 0)
            self._tol_rows[w] = item.widget() if item is not None else None
        self.tol_type.currentTextChanged.connect(self.tol_shown)
        self.tol_shown(self.tol_type.currentText())
        self.hole = None
        self.dims = []
        self.refs = {}

    def tol_shown(self, kind):
        ""

        for w, on in ((self.tol_max, kind in ("Bilateral", "Symmetric")), (self.tol_min, kind == "Bilateral")):
            w.setVisible(on)
            if self._tol_rows.get(w) is not None:
                self._tol_rows[w].setVisible(on)

    def callout_text(self, view, c, r):
        if isinstance(c, SideHole):
            return c.text(len(self.precision.currentText()) - 1, view)
        return callout_text(view, c, r, len(self.precision.currentText()) - 1, self.count.isChecked())

    def restyle(self, *_):
        if not self.dims:
            return
        dim = self.dims[-1]
        view, c, r = self.refs[dim.Name]
        apply_tolerance(dim, self.tol_type.currentText(), self.tol_max.value(), self.tol_min.value())
        set_text(dim, self.callout_text(view, c, r))
        mark_callout(dim, len(self.precision.currentText()) - 1, self.count.isChecked())
        self.doc.recompute()
        self.show_text(dim)

    def show_text(self, dim):
        self.text.blockSignals(True)
        self.text.setPlainText(dim.FormatSpec)
        self.text.blockSignals(False)
        for w in (self.text, self.text_apply, self.variables):
            w.show()

    def values(self):
        dim = self.dims[-1]
        view, c, r = self.refs[dim.Name]
        if isinstance(c, SideHole):
            t = c.text(len(self.precision.currentText()) - 1, view)
            return {"<NUM_INST>": "", "<MOD-DIAM>": "⌀", "<HOLE-DIAM>": "%%.%dw" % (len(self.precision.currentText()) - 1),
                    "<THRU>": "THRU" if "THRU" in t else "", "<HOLE-TEXT>": t, "<MOD-DEPTH>": "↧" if "↧" in t else "",
                    "<HOLE-DEPTH>": t.split("↧")[1].strip() if "↧" in t else "", "<THREAD>": "",
                    "<CBORE-DIAM>": "", "<CBORE-DEPTH>": "", "<CSK-DIAM>": "", "<CSK-ANGLE>": ""}
        return callout_values(view, c, r, len(self.precision.currentText()) - 1)

    def insert_variable(self):
        if not self.dims:
            return None
        v = CalloutVariablesDialog.pick(self.values())
        if v:
            self.text.insertPlainText(v)
        return v

    def retext(self):
        """Apply text: text with variables follows the hole (the variables worked out now and at every change);
        plain text typed over the callout no longer does."""
        if not self.dims:
            return
        dim = self.dims[-1]
        t = self.text.toPlainText()
        if not t:
            return
        if has_variables(t):
            set_callout_format(dim, t)
            out = expand_callout(t, self.values())
            set_text(dim, out)
            dim.SWCalloutAuto = out
        elif t != dim.FormatSpec:
            set_callout_format(dim, "")
            set_text(dim, t)
        self.doc.recompute()

    def sheet_click(self, p):
        if self.hole is None:
            view, hit = circle_under(self.page, p, 2.0)
            if view is None:
                self.say("Click the edge of a hole inside a drawing view.")
                return True
            k = DV.view_scale(view)
            if hit is None:
                side = side_hole_at(view, DV.to_geometry(view, p), 2.0 / k)
                if side is not None:              # a hole seen from its side: a section or side view
                    self.hole = (view, side)
                    self.say("Click where the callout goes.")
                    return True
                self.say("Click on a hole's edge.")
                return True
            self.hole = (view, hit)
            self.say("Click where the callout goes.")
            return True
        view, hole = self.hole
        self.hole = None
        x0, y0 = D.view_position(view)
        if isinstance(hole, SideHole):
            i, j = hole.edges
            a = view.getEdgeByIndex(i)
            p0, p1 = a.Vertexes[0].Point, a.Vertexes[-1].Point
            kind = "DistanceY" if abs(p1.x - p0.x) >= abs(p1.y - p0.y) else "DistanceX"
            c, r = hole, hole.radius
            dim = dimension(self.page, view, kind, ["Edge%d" % i, "Edge%d" % j], (p[0] - x0, p[1] - y0),
                            self.callout_text(view, c, r))
            dim.addProperty("App::PropertyBool", "SWSideCallout", "FreeCAD", "hole callout on a hole seen from its side")
            dim.SWSideCallout = True
        else:
            i, c, r = hole
            dim = dimension(self.page, view, "Diameter", ["Edge%d" % i], (p[0] - x0, p[1] - y0),
                            self.callout_text(view, c, r))
        dim.addProperty("App::PropertyBool", "SWHoleCallout", "FreeCAD", "Hole callout")
        dim.SWHoleCallout = True
        mark_callout(dim, len(self.precision.currentText()) - 1, self.count.isChecked())
        self.refs[dim.Name] = (view, c, r)
        apply_tolerance(dim, self.tol_type.currentText(), self.tol_max.value(), self.tol_min.value())
        self.dims.append(dim)
        self.made.append(dim)
        self.doc.recompute()
        self.show_text(dim)
        self.say("Hole callout added. Click another hole, or OK.")
        return True


# --------------------------------------------------------------------------- symbols drawn as SVG
TEXT_SIZE = 3.5
STROKE = 0.25


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _arrow(x0, y0, x1, y1, end="Filled arrow"):
    """SVG of a leader from (x1, y1) to the arrow tip (x0, y0) (svg coordinates, y down)."""
    out = ['<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>' % (x1, y1, x0, y0, STROKE)]
    L = math.hypot(x1 - x0, y1 - y0)
    if L < 1e-9 or end == "None":
        return "".join(out)
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    a, w = 3.0, 1.0
    if end == "Dot":
        out.append('<circle cx="%g" cy="%g" r="0.75" fill="#000"/>' % (x0, y0))
    elif end in ("Filled triangle", "Empty triangle"):
        bx, by = x0 + ux * a * 0.9, y0 + uy * a * 0.9
        out.append('<polygon points="%g,%g %g,%g %g,%g" fill="%s" stroke="#000" stroke-width="%g"/>' % (
            x0 - uy * a * 0.6, y0 + ux * a * 0.6, x0 + uy * a * 0.6, y0 - ux * a * 0.6, bx, by,
            "#000" if end == "Filled triangle" else "none", STROKE))
    else:
        bx, by = x0 + ux * a, y0 + uy * a
        pts = "%g,%g %g,%g %g,%g" % (x0, y0, bx - uy * w, by + ux * w, bx + uy * w, by - ux * w)
        fill = "#000" if end == "Filled arrow" else "none"
        out.append('<polygon points="%s" fill="%s" stroke="#000" stroke-width="%g"/>' % (pts, fill, STROKE))
    return "".join(out)


_DOC_FONT = re.compile(r'font-family="(?:[^"]*?, )?osifont, Arial"')


def with_font(svg, font):
    """svg's text on the document font (Document Properties > Annotations > Font), osifont behind it for the
    characters it lacks; text with a font of its own is left as it is."""
    want = 'font-family="osifont, Arial"' if not font or font == "osifont" else \
        'font-family="%s, osifont, Arial"' % _esc(str(font)).replace('"', "")
    return _DOC_FONT.sub(want, svg or "")


def doc_font(doc):
    """The drawing's annotation font, once its Document Properties were set; else "" (osifont)."""
    try:
        from . import drawdocprops as DP
        return DP.prop(doc, "ann_font") if DP.stored(doc) else ""
    except Exception as _fw_err:
        _fw_log("drawannot.py:2772", _fw_err)
        return ""


def doc_datum_style(doc):
    try:
        from . import drawdocprops as DP
        return DP.prop(doc, "datum_frame") or "Square", DP.prop(doc, "datum_leader") or "Filled triangle"
    except Exception:
        return "Square", "Filled triangle"


def restyle_datum(sym, frame, leader):
    """A datum feature drawn again with another frame / leader style (its letter, text and leader point kept)."""
    tip = getattr(sym, "SWTip", None)
    if tip is None:
        return False
    if getattr(sym, "SWDatumStyle", "") == "%s|%s" % (frame, leader):
        return False
    at = (float(sym.X), float(sym.Y))
    body, reach = datum_svg(getattr(sym, "SWDatum", "A"), at, (tip.x, tip.y) if tip.z >= 0 else None, frame, leader,
                            getattr(sym, "SWDatumText", ""))
    R = max(5.0, reach + 5.0)
    sym.Symbol = with_font('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" '
                           'viewBox="%g %g %g %g">%s</svg>' % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body),
                           doc_font(sym.Document))
    sym.SWDatumStyle = "%s|%s" % (frame, leader)
    return True


def svg_symbol(page, name, body, reach, at, label, kind):
    """A TechDraw symbol of SVG body, centred on sheet point at (TechDraw centres a symbol on its X, Y)."""
    font = doc_font(page.Document)
    if font:
        body = with_font(body, font)
    svg = symbol_svg(body, reach)
    doc = page.Document
    s = doc.addObject("TechDraw::DrawViewSymbol", name)
    s.Symbol = svg
    page.addView(s)
    s.X, s.Y = at
    s.Label = label
    s.addProperty("App::PropertyString", "SWAnnotation", "FreeCAD", "Annotation kind")
    s.SWAnnotation = kind
    if kind in ("Balloon", "StackedBalloon"):
        try:                    # the drawing's FeatureManager tree lists no balloons
            s.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("drawannot.py:2784", _fw_err)
    return s


class _Reach(float):
    """A symbol's reach (its old square half size) that may also know its half width and half height (rx, ry)."""
    rx = ry = None


def symbol_half(reach):
    """(half width, half height) of a symbol's svg box: the note's own extent when known, else the square."""
    Rs = max(5.0, reach + 5.0)
    rx, ry = getattr(reach, "rx", None), getattr(reach, "ry", None)
    if rx is None or ry is None:
        return Rs, Rs
    return max(3.0, min(Rs, rx)), max(3.0, min(Rs, ry))


def symbol_svg(body, reach):
    hx, hy = symbol_half(reach)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
            % (2 * hx, 2 * hy, -hx, -hy, 2 * hx, 2 * hy, body))


def _reach(at, tip):
    return math.hypot(tip[0] - at[0], tip[1] - at[1]) if tip else 0.0


def _rel(at, tip):
    """sheet point tip relative to at, in svg coordinates (y down)."""
    return tip[0] - at[0], -(tip[1] - at[1])


def _text_width(text, size=TEXT_SIZE):
    return 0.6 * size * max([len(line) for line in text.split("\n")] or [1])


FRAME_RUN = re.compile(r"\|(?:[^|\n]+\|)+")      # |⌖|0.1|A| typed or inserted in a note: frame cells
CELL_PAD = 1.2                                     # mm each side of a cell's text


def _pieces(line):
    """A note line cut into ("text", s) and ("frame", [cells]) pieces."""
    out, at = [], 0
    for m in FRAME_RUN.finditer(line):
        if m.start() > at:
            out.append(("text", line[at:m.start()]))
        out.append(("frame", m.group(0)[1:-1].split("|")))
        at = m.end()
    if at < len(line):
        out.append(("text", line[at:]))
    return out


def _cell_width(c, size):
    return max(size * 1.4, _text_width(c, size) + 2 * CELL_PAD)


def _line_width(line, size=TEXT_SIZE):
    """A note line's width with its frame cells (a Geometric Tolerance or Datum Feature inserted in the note)."""
    if "|" not in line:
        return _text_width(line, size)
    w = 0.0
    for kind, v in _pieces(line):
        w += sum(_cell_width(c, size) for c in v) if kind == "frame" else _text_width(v, size)
    return w


def _framed_line(line, x, y, size, font, look):
    ""

    out = []
    for kind, v in _pieces(line):
        if kind == "text":
            out.append('<text x="%g" y="%g" font-family="%s" font-size="%g"%s xml:space="preserve">%s</text>'
                       % (x, y, _esc(font), size, look, _esc(v)))
            x += _text_width(v, size)
            continue
        top, h = y - size * 1.05, size * 1.4
        for c in v:
            cw = _cell_width(c, size)
            out.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                       % (x, top, cw, h, STROKE))
            out.append('<text x="%g" y="%g" font-family="%s" font-size="%g" text-anchor="middle"%s>%s</text>'
                       % (x + cw / 2, y, _esc(font), size, look, _esc(c)))
            x += cw
    return "".join(out)


NOTE_BORDERS = ("None", "Circular", "Box", "Triangle", "Hexagon", "Diamond")


def _frame(shape, w, h, pad=1.5):
    """An SVG outline round a w x h box centred on 0, 0 (note borders, balloon styles), pad mm clear of it."""
    r = max(w, h) / 2 + pad
    if shape == "Circular":
        return '<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (r, STROKE)
    if shape in ("Box", "Square"):
        return ('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                % (-w / 2 - pad, -h / 2 - pad, w + 2 * pad, h + 2 * pad, STROKE))
    if shape == "Triangle":
        return ('<polygon points="0,%g %g,%g %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                % (-1.6 * r, 1.4 * r, 0.9 * r, -1.4 * r, 0.9 * r, STROKE))
    if shape == "Hexagon":
        pts = " ".join("%g,%g" % (r * 1.1 * math.cos(math.radians(a)), r * 1.1 * math.sin(math.radians(a)))
                       for a in range(0, 360, 60))
        return '<polygon points="%s" fill="none" stroke="#000" stroke-width="%g"/>' % (pts, STROKE)
    if shape == "Diamond":
        return ('<polygon points="0,%g %g,0 0,%g %g,0" fill="none" stroke="#000" stroke-width="%g"/>'
                % (-1.4 * r, 1.4 * r, 1.4 * r, -1.4 * r, STROKE))
    return ""


NOTE_SYMBOLS = (("Diameter", "\u2300"), ("Degree", "\u00b0"), ("Plus/Minus", "\u00b1"),
                ("Square", "\u25a1"), ("Counterbore", "\u2334"), ("Countersink", "\u2335"), ("Depth", "\u21a7"),
                ("Centerline", "\u2104"), ("Approximately", "\u2248"), ("Less or equal", "\u2264"),
                ("Greater or equal", "\u2265"), ("Spherical diameter", "S\u2300"), ("Radius", "R"),
                ("Arc length", "\u2322"), ("Slope", "\u2333"), ("Conical taper", "\u2332"),
                ("Copyright", "\u00a9"), ("Registered", "\u00ae"), ("Trademark", "\u2122"))

SYMBOL_LIBRARY = (
    ("Modifying Symbols", NOTE_SYMBOLS),
    ("Geometric Tolerance", (("Straightness", "\u23e4"), ("Flatness", "\u23e5"), ("Circularity", "\u25cb"),
                             ("Cylindricity", "\u232d"), ("Line profile", "\u2312"), ("Surface profile", "\u2313"),
                             ("Angularity", "\u2220"), ("Perpendicularity", "\u27c2"), ("Parallelism", "\u2225"),
                             ("Position", "\u2316"), ("Concentricity", "\u25ce"), ("Symmetry", "\u232f"),
                             ("Circular runout", "\u2197"), ("Total runout", "\u2330"),
                             ("Maximum material condition", "\u24c2"), ("Least material condition", "\u24c1"),
                             ("Regardless of feature size", "\u24c8"), ("Projected tolerance zone", "\u24c5"),
                             ("Free state", "\u24bb"), ("Tangent plane", "\u24c9"), ("Unequally disposed", "\u24ca"))),
    ("Hole Symbols", (("Diameter", "\u2300"), ("Counterbore", "\u2334"), ("Countersink", "\u2335"),
                      ("Depth", "\u21a7"), ("Spherical diameter", "S\u2300"), ("Square", "\u25a1"))),
    ("Flag Symbols", tuple(("Flag %d" % n, chr(0x2460 + n - 1)) for n in range(1, 21))),
    ("Text Symbols", (("Alpha", "\u03b1"), ("Beta", "\u03b2"), ("Gamma", "\u03b3"), ("Delta", "\u0394"),
                      ("Theta", "\u03b8"), ("Mu", "\u00b5"), ("Pi", "\u03c0"), ("Sigma", "\u03a3"),
                      ("Omega", "\u03a9"), ("Squared", "\u00b2"), ("Cubed", "\u00b3"), ("One half", "\u00bd"),
                      ("One quarter", "\u00bc"), ("Three quarters", "\u00be"), ("Multiply", "\u00d7"),
                      ("Not equal", "\u2260"), ("Infinity", "\u221e"))),
)


class SymbolLibraryDialog(QtWidgets.QDialog):
    """Note > Add Symbol: the Symbol Library: Categories, the category's symbols (a big preview of the one
    picked), OK puts it in the note at the cursor."""

    def __init__(self, parent=None, category=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWSymbolLibrary")
        self.setWindowTitle("Symbol Library")
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.category = QtWidgets.QComboBox(self)
        self.category.setObjectName("SWSymbolCategory")
        self.category.addItems([c for c, _ in SYMBOL_LIBRARY])
        form.addRow("Categories:", self.category)
        lay.addLayout(form)
        row_ = QtWidgets.QHBoxLayout()
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWSymbolList")
        row_.addWidget(self.list, 1)
        self.preview = QtWidgets.QLabel(self)
        self.preview.setObjectName("SWSymbolPreview")
        self.preview.setMinimumSize(90, 90)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        f = self.preview.font()
        f.setPointSize(36)
        self.preview.setFont(f)
        self.preview.setFrameShape(QtWidgets.QFrame.Box)
        row_.addWidget(self.preview)
        lay.addLayout(row_)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.category.currentIndexChanged.connect(self.fill)
        self.list.currentRowChanged.connect(self.show_symbol)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        if category:
            self.category.setCurrentText(category)
        self.fill()

    def symbols(self):
        return dict(SYMBOL_LIBRARY).get(self.category.currentText(), ())

    def fill(self, *_):
        self.list.clear()
        for name, ch in self.symbols():
            it = QtWidgets.QListWidgetItem("%s   %s" % (ch, name))
            it.setData(QtCore.Qt.UserRole, ch)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def show_symbol(self, row):
        it = self.list.item(row) if row >= 0 else None
        self.preview.setText(it.data(QtCore.Qt.UserRole) if it is not None else "")

    def symbol(self):
        it = self.list.currentItem()
        return it.data(QtCore.Qt.UserRole) if it is not None else ""


def library_symbol(name):
    """A symbol's text by its name (any category), else name itself."""
    for _cat, items in SYMBOL_LIBRARY:
        for n, ch in items:
            if n == name:
                return ch
    return name


BORDER_SIZES = ("Tight Fit", "1 Character", "2 Characters", "3 Characters", "4 Characters", "5 Characters",
                "User Defined")


def _wrap(text, width, size):
    import textwrap
    if not width:
        return text.split("\n") or [""]
    chars = max(1, int(width / (0.6 * size)))
    out = []
    for line in text.split("\n"):
        out.extend(textwrap.wrap(line, chars) or [""])
    return out


def _spline_leader(tx, ty, sx, sy, arrow="Filled arrow"):
    """Spline Leader: a smooth curve from the note (sx, sy) to the tip (tx, ty), its arrow along the curve's end."""
    c1 = (sx + (tx - sx) * 0.5, sy)
    c2 = (tx, sy + (ty - sy) * 0.5)

    def at(t):
        u = 1 - t
        return (u ** 3 * sx + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * tx,
                u ** 3 * sy + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * ty)
    out = ['<path d="M %g %g C %g %g %g %g %g %g" fill="none" stroke="#000" stroke-width="%g"/>'
           % (sx, sy, c1[0], c1[1], c2[0], c2[1], tx, ty, STROKE)]
    ex, ey = at(0.92)
    out.append(_arrow(tx, ty, ex, ey, arrow))
    return "".join(out)


NOTE_LEADERS = ("Auto Leader", "Leader", "Multi-jog Leader", "No Leader", "Spline Leader")


def note_svg(text, at, tip=None, arrow="Filled arrow", size=TEXT_SIZE, align="Left", angle=0.0, border="None",
             font="osifont, Arial", upper=False, wrap=0.0, leader_style="Bent", attach="Nearest", pad=1.5,
             border_size="Tight Fit", border_user=10.0, link=False, leader_dash="", leader_width=0.0, look="",
             jogs=()):
    ""


    if upper:
        try:
            from . import drawdocprops
            doc = App.ActiveDocument
            text = drawdocprops.upper_text(text, doc if doc is not None and drawdocprops.stored(doc) else None)
        except Exception:
            text = text.upper()
    lines = _wrap(text, wrap, size)
    w = max([_line_width(line, size) for line in lines] or [size])
    if wrap and align == "Fit text":
        w = wrap
    h = size * 1.4 * len(lines)
    x, anchor = {"Left": (-w / 2, "start"), "Center": (0, "middle"), "Right": (w / 2, "end")}.get(align, (-w / 2, "start"))
    look = (' fill="#0000ee" text-decoration="underline"' if link else "") + \
        ("" if link else (look or ""))        # Choose Font: style, space, Strikeout / Underline
    body = []
    for n, line in enumerate(lines):
        y = -h / 2 + size * (1.1 + 1.4 * n)
        if align == "Fit text":
            lw = max(_text_width(line, size), 1e-6)
            body.append('<g transform="translate(%g 0) scale(%g 1)"><text x="0" y="%g" font-family="%s" '
                        'font-size="%g"%s>%s</text></g>' % (-w / 2, w / lw, y, _esc(font), size, look, _esc(line)))
        elif FRAME_RUN.search(line):
            lw = _line_width(line, size)
            x0 = {"middle": x - lw / 2, "end": x - lw}.get(anchor, x)
            body.append(_framed_line(line, x0, y, size, font, look))
        else:
            body.append('<text x="%g" y="%g" font-family="%s" font-size="%g" text-anchor="%s"%s>%s</text>'
                        % (x, y, _esc(font), size, anchor, look, _esc(line)))
    fw, fh = w, h
    if border != "None" and border_size != "Tight Fit":
        side = border_user if border_size == "User Defined" else _text_width("0" * int(border_size[0]), size)
        fw, fh = max(w, side), max(h, side if border in ("Circular", "Hexagon", "Diamond", "Triangle") else h)
    body.append(_frame(border, fw, fh, pad))
    inner = "".join(body)
    if angle:
        inner = '<g transform="rotate(%g)">%s</g>' % (-angle, inner)
    body = [inner]
    if tip is not None:
        tx, ty = _rel(at, tip)
        left = attach == "Left" or attach == "Nearest" and tx < 0
        sx = -w / 2 - 1 if left else w / 2 + 1
        ly = -h / 2 + size * 0.7
        lead = []
        if jogs:
            # Multi-jog Leader: the arrow at the tip, then straight segments through each jog point to the note
            pts = [_rel(at, j) for j in jogs]
            lead.append(_arrow(tx, ty, pts[0][0], pts[0][1], arrow))
            end = (sx + (-3 if left else 3), ly) if leader_style == "Bent" else (sx, ly)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:] + [end]):
                lead.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                            % (x1, y1, x2, y2, STROKE))
            if leader_style == "Bent":
                lead.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                            % (sx, ly, end[0], ly, STROKE))
        elif leader_style == "Straight":
            lead.append(_arrow(tx, ty, sx, ly, arrow))
        elif leader_style == "Spline":
            lead.append(_spline_leader(tx, ty, sx, ly, arrow))
        elif leader_style == "Underlined":
            uy = h / 2 + 0.6
            lead.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                        % (-w / 2 - 1, uy, w / 2 + 1, uy, STROKE))
            lead.append(_arrow(tx, ty, sx, uy, arrow))
        else:
            lead.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                        % (sx, ly, sx + (-3 if left else 3), ly, STROKE))
            lead.append(_arrow(tx, ty, sx + (-3 if left else 3), ly, arrow))
        lead = "".join(lead)
        if leader_width:
            lead = lead.replace('stroke-width="%g"' % STROKE, 'stroke-width="%g"' % leader_width)
        if leader_dash:
            lead = lead.replace("<line ", '<line stroke-dasharray="%s" ' % leader_dash)
            lead = lead.replace("<path ", '<path stroke-dasharray="%s" ' % leader_dash)
        body.append(lead)
    reach = _Reach(max(fw, fh) / 2 * (1.6 if border != "None" else 1.0) + pad + _reach(at, tip))
    # the note's own extent on each axis (look audit DW-3: the square of the leader's length made the hover and

    k = 1.6 if border != "None" else 1.0
    hx, hy = fw / 2 * k + pad, fh / 2 * k + pad
    if angle:
        hx = hy = math.hypot(hx, hy)
    pts = [(hx, hy)]
    if tip is not None:
        tx, ty = _rel(at, tip)
        pts.append((abs(tx) + 2.0, abs(ty) + 2.0))
        pts.append((w / 2 + 5.0, hy))
        for j in jogs or ():
            jx, jy = _rel(at, j)
            pts.append((abs(jx) + 1.0, abs(jy) + 1.0))
    reach.rx = max(x for x, _y in pts) + 1.0
    reach.ry = max(y for _x, y in pts) + 1.0
    return "".join(body), reach


def attached_documents(page, tip):
    ""


    if tip is None:
        return None, None
    view = DV.view_at(page, tip)
    if view is None:
        return None, None
    vdoc = None
    try:
        for o in DV.source_shapes(view):
            if o.Document is not page.Document:
                vdoc = o.Document
                break
    except Exception as _fw_err:
        _fw_log("drawannot.py:3054", _fw_err)
    cdoc = None
    try:
        comp = item_number(view, tip)[1]
        if comp is not None:
            base = getattr(comp, "LinkedObject", None) or comp
            cdoc = base.Document
    except Exception as _fw_err:
        _fw_log("drawannot.py:3062", _fw_err)
    return vdoc, cdoc or vdoc


LINK_SOURCES = {"Current document": "PRP", "Model in view": "PRPSHEET",
                "Model in view to which the annotation is attached": "PRPVIEW",
                "Component to which the annotation is attached": "PRPMODEL"}
LINK_KEYS = ["Label", "CreatedBy", "Company", "Comment", "LastModifiedBy", "CreationDate", "LastModifiedDate", "License"]




SYSTEM_PROPS = ("FW-Author", "FW-Comments", "FW-Created Date", "FW-File Name", "FW-Folder Name", "FW-Keywords",
                "FW-Last Saved By", "FW-Last Saved Date", "FW-Long Date", "FW-Short Date", "FW-Subject", "FW-Title")
SHEET_PROPS = ("FW-Current Sheet", "FW-Sheet Name", "FW-Sheet Scale", "FW-Template Size", "FW-Total Sheets")


def _aliases(out):
    ""
    out.update({"FW-" + k[3:]: v for k, v in list(out.items()) if k.startswith("SW-")})
    return out


def _date(text, long=False):
    ""
    import datetime as _dt
    t = None
    if text:
        try:
            t = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            t = None
    t = t or _dt.datetime.now()
    if long:
        return "%s, %s %d, %d" % (t.strftime("%A"), t.strftime("%B"), t.day, t.year)
    return "%d/%d/%d" % (t.month, t.day, t.year)


def system_properties(doc):
    ""

    import os as _os
    if doc is None:
        return {}
    try:
        from . import fileprops
        sm = fileprops.summary(doc)
    except Exception:
        sm = {"Author": getattr(doc, "CreatedBy", ""), "Comments": getattr(doc, "Comment", ""),
              "Created": getattr(doc, "CreationDate", ""), "Last saved": getattr(doc, "LastModifiedDate", ""),
              "Last saved by": getattr(doc, "LastModifiedBy", "")}
    fn = getattr(doc, "FileName", "") or ""
    out = {"SW-Author": str(sm.get("Author", "") or ""), "SW-Comments": str(sm.get("Comments", "") or ""),
           "SW-Keywords": str(sm.get("Keywords", "") or ""), "SW-Subject": str(sm.get("Subject", "") or ""),
           "SW-Title": str(sm.get("Title", "") or "") or doc.Label,
           "SW-File Name": _os.path.splitext(_os.path.basename(fn))[0] if fn else doc.Label,
           "SW-Folder Name": (_os.path.dirname(fn).replace("/", _os.sep) + _os.sep) if fn else "",
           "SW-Created Date": _date(sm.get("Created")) if sm.get("Created") else "",
           "SW-Last Saved Date": _date(sm.get("Last saved")) if sm.get("Last saved") else "",
           "SW-Last Saved By": str(sm.get("Last saved by", "") or ""),
           "SW-Short Date": _date(None), "SW-Long Date": _date(None, True)}
    return _aliases(out)


def property_names(doc, sheet=False):
    ""

    names = list(LINK_KEYS)
    if doc is None:
        return names
    try:
        names += [str(k) for k in dict(doc.Meta) if ":" not in str(k)]
    except Exception as _fw_err:
        _fw_log("drawannot.py:3135", _fw_err)
    try:
        from . import customprops
        names += [n for n, _k, _v in customprops.read(doc)]
        from . import fileprops             # and the configurations' own properties
        for c in fileprops.configurations(doc):
            names += [n for n, _k, _v in fileprops.read_config(doc, c)]
    except Exception as _fw_err:
        _fw_log("drawannot.py:3140", _fw_err)
    names += list(SYSTEM_PROPS) + (list(SHEET_PROPS) if sheet else [])
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


class LinkPropertyDialog(QtWidgets.QDialog):
    ""



    def __init__(self, page, tip=None, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.page, self.tip = page, tip
        self.setObjectName("SWLinkProperty")
        self.setWindowTitle("Link to Property")
        lay = QtWidgets.QVBoxLayout(self)
        box = QtWidgets.QGroupBox("Use custom properties from", self)
        bl = QtWidgets.QVBoxLayout(box)
        self.current = QtWidgets.QRadioButton("Current document", box)
        self.current.setObjectName("SWLinkCurrent")
        self.model = QtWidgets.QRadioButton("Model found here", box)
        self.model.setObjectName("SWLinkModel")
        self.where = QtWidgets.QComboBox(box)
        self.where.setObjectName("SWLinkModelWhere")
        self.where.addItems(["Drawing view specified in sheet properties",
                             "Model in view to which the annotation is attached"])
        self.comp = QtWidgets.QRadioButton("Component to which the annotation is attached", box)
        self.comp.setObjectName("SWLinkComponent")
        for w in (self.current, self.model, self.where, self.comp):
            bl.addWidget(w)
        self.current.setChecked(True)
        lay.addWidget(box)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Property name:", self))
        self.name = QtWidgets.QComboBox(self)
        self.name.setObjectName("SWLinkName")
        self.name.setEditable(True)
        row.addWidget(self.name, 1)
        lay.addLayout(row)

        self.on_pick = None
        self.keep = QtWidgets.QToolButton(self)
        self.keep.setObjectName("SWLinkKeepVisible")
        self.keep.setText("Keep Visible")
        self.keep.setToolTip("Keep Visible: the box stays open after OK, to link more properties")
        self.keep.setCheckable(True)
        self.keep.setChecked(_link_keep_open())
        self.keep.toggled.connect(_set_link_keep_open)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        brow = QtWidgets.QHBoxLayout()
        brow.addWidget(self.keep)
        brow.addStretch(1)
        brow.addWidget(bb)
        lay.addLayout(brow)
        for w in (self.current, self.model, self.comp):
            w.toggled.connect(self.refill)
        self.where.currentIndexChanged.connect(self.refill)
        self.refill()

    def source(self):
        if self.comp.isChecked():
            return "Component to which the annotation is attached"
        if self.model.isChecked():
            return "Model in view" if self.where.currentIndex() == 0 else \
                "Model in view to which the annotation is attached"
        return "Current document"

    def refill(self, *_):
        if not getattr(self.where, "_fw_live", False):    # a pick in the list chooses Model found here
            self.where._fw_live = True
            DL.sets(self.model, True, self.where)
        src = self.source()
        if src == "Current document":
            doc = self.page.Document
        elif src == "Model in view":
            doc = model_document(self.page)
        else:
            vdoc, cdoc = attached_documents(self.page, self.tip)
            doc = (cdoc if src.startswith("Component") else vdoc) or model_document(self.page)
        keep = self.name.currentText()
        self.name.clear()
        self.name.addItems(property_names(doc, sheet=src == "Current document"))
        if keep:
            self.name.setCurrentText(keep)

    def choice(self):
        return "%s  %s" % (self.source(), self.name.currentText().strip())

    def accept(self):
        """OK: with Keep Visible on (and a note to put it in), the link goes in and the box stays open."""
        if self.keep.isChecked() and self.on_pick is not None:
            if self.name.currentText().strip():
                self.on_pick(self.choice())
                self.picked_count = getattr(self, "picked_count", 0) + 1
            return
        super().accept()


def _link_keep_open():
    try:
        from . import paths
        return paths.params().GetBool("LinkPropertyKeepVisible", False)    # off: OK closes, as before
    except Exception:
        return False


def _set_link_keep_open(on):
    try:
        from . import paths
        paths.params().SetBool("LinkPropertyKeepVisible", bool(on))
    except Exception as _fw_err:
        _fw_log("drawannot.py:3255", _fw_err)


def resolve_properties(page, text, tip=None):
    """$PRP:"name" (the drawing's property), $PRPSHEET:"name" (the model in the sheet's first view), and for a
    note attached at tip, $PRPVIEW:"name" (the model of the view it is attached to) and $PRPMODEL:"name" (the
    component it is attached to)."""
    import re as _re
    if "$PRP" not in text:
        return text

    def props(doc, config=None):
        out = {}
        if doc is None:
            return out
        for k in ("Label", "CreatedBy", "Company", "Comment", "LastModifiedBy", "CreationDate", "LastModifiedDate",
                  "License", "Id"):
            try:
                out[k] = str(getattr(doc, k, "") or "")
            except Exception as _fw_err:
                _fw_log("drawannot.py:3275", _fw_err)
        try:
            out.update({str(k): str(v) for k, v in dict(doc.Meta).items()})
        except Exception as _fw_err:
            _fw_log("drawannot.py:3279", _fw_err)
        try:
            from . import customprops          # File > Properties' custom properties, by their names
            for n, kind, v in customprops.read(doc):
                out[n] = str(customprops.evaluate(doc, kind, v, config))   # the view's configuration's mass, dimensions

            # its own shows its material (or Material <not specified>); a Material the user typed stays
            if not any(str(k).lower() == "material" for k in out) and any(
                    o.TypeId == "PartDesign::Body" or getattr(getattr(o, "Proxy", None), "Type", None) ==
                    "SWStyle::Material" for o in doc.Objects):
                out["Material"] = str(customprops.evaluate(doc, "Text", '$PRP:"Material"', config) or
                                      "Material <not specified>")
        except Exception as _fw_err:
            _fw_log("drawannot.py:3285", _fw_err)
        try:
            out.update(system_properties(doc))
        except Exception as _fw_err:
            _fw_log("drawannot.py:3289", _fw_err)
        return out
    mine = props(page.Document)
    mine.update(sheet_properties(page))
    mdoc, mconfig = model_configuration(page)
    model = props(mdoc, mconfig)
    try:
        from . import fileprops
        model.update(fileprops.config_values(mdoc, mconfig))
    except Exception as _fw_err:
        _fw_log("drawannot.py:prpsheet-config", _fw_err)
    tz = str(_doc_row(page.Document, "Dimensions", "Trailing zeroes, properties", "Smart"))

    def zeros(v):
        """Document Properties > Dimensions > Trailing zeroes, properties: Smart / Remove trim a number's zeroes."""
        if tz in ("Smart", "Remove") and _re.fullmatch(r"[-+]?\d+\.\d*0", v.strip()):
            return v.strip().rstrip("0").rstrip(".")
        return v
    def get(d, name):
        ""
        if name in d:
            return d[name]
        low = name.lower()
        return next((v for k, v in d.items() if str(k).lower() == low), "")
    text = _re.sub(r'\$PRPSHEET:"([^"]*)"', lambda m: zeros(get(model, m.group(1))), text)
    if "$PRPVIEW" in text or "$PRPMODEL" in text:
        vdoc, cdoc = attached_documents(page, tip)
        vp, cp = props(vdoc or model_document(page)), props(cdoc or vdoc or model_document(page))
        text = _re.sub(r'\$PRPVIEW:"([^"]*)"', lambda m: zeros(get(vp, m.group(1))), text)
        text = _re.sub(r'\$PRPMODEL:"([^"]*)"', lambda m: zeros(get(cp, m.group(1))), text)
    return _re.sub(r'\$PRP:"([^"]*)"', lambda m: zeros(get(mine, m.group(1))), text)


def sheet_properties(page):
    ""

    out = {}
    try:
        from . import drawsheet
        pages = drawsheet.pages(page.Document)
        out["SW-Current Sheet"] = str(pages.index(page) + 1 if page in pages else 1)
        out["SW-Total Sheets"] = str(len(pages) or 1)
    except Exception:
        out["SW-Current Sheet"], out["SW-Total Sheets"] = "1", "1"
    out["SW-Sheet Name"] = page.Label
    try:
        out["SW-Sheet Scale"] = D.scale_text(float(page.Scale))
    except Exception:
        out["SW-Sheet Scale"] = "%g" % float(page.Scale)
    import os as _os
    fn = page.Document.FileName or ""
    out["SW-File Name"] = _os.path.splitext(_os.path.basename(fn))[0] if fn else page.Document.Label
    out["SW-Title"] = page.Document.Label
    try:
        out["SW-Title"] = system_properties(page.Document)["SW-Title"]
    except Exception as _fw_err:
        _fw_log("drawannot.py:3333", _fw_err)
    try:
        from . import drawsheet
        name = drawsheet.describe(drawsheet.page_template_path(page))
        if not name or name.lower().endswith(".svg"):
            w, h = drawsheet._sheet_size(page)
            name = "%g x %g mm" % (round(w, 1), round(h, 1))
        out["SW-Template Size"] = name
    except Exception:
        out["SW-Template Size"] = ""
    return _aliases(out)


def model_configuration(page):
    """(the model document the sheet's $PRPSHEET fields read, the configuration its view shows or None)."""
    try:
        from . import drawsheet
        pv = drawsheet.property_view(page)
    except Exception:
        pv = None
    try:
        from . import drawpartcfg
        for v in ([pv] if pv is not None else []) + list(page.Views):
            try:
                d, c = drawpartcfg.view_configuration(v)
            except Exception:
                continue
            if d is not None and d is not page.Document:
                return d, (c or None)
    except Exception as _fw_err:
        _fw_log("drawannot.py:model_configuration", _fw_err)
    return model_document(page), None


def model_document(page):
    try:
        from . import drawsheet
        pv = drawsheet.property_view(page)
    except Exception:
        pv = None
    try:
        from . import drawpartcfg            # a view showing a configuration draws a copy in the drawing
        for v in ([pv] if pv is not None else []) + list(page.Views):
            try:
                d = drawpartcfg.view_configuration(v)[0]
            except Exception:
                continue
            if d is not None and d is not page.Document:
                return d
    except Exception as _fw_err:
        _fw_log("drawannot.py:model_document", _fw_err)
    if pv is not None:
        try:
            for s in _fw_xs(pv) + list(getattr(pv, "Source", []) or []):
                if s.Document is not page.Document:
                    return s.Document
        except Exception as _fw_err:
            _fw_log("drawannot.py:3358", _fw_err)
    for v in page.Views:
        try:
            for s in _fw_xs(v) + list(getattr(v, "Source", []) or []):
                if s.Document is not page.Document:
                    return s.Document
        except Exception as _fw_err:
            _fw_log("drawannot.py:3365", _fw_err)
    try:
        from . import asmdrawing        # an assembly view drawn from its view model (exploded, configuration...)
        for v in ([pv] if pv is not None else []) + list(page.Views):
            asm = asmdrawing.assembly_of_view(v)
            if asm is not None and asm.Document is not page.Document:
                return asm.Document
    except Exception as _fw_err:
        _fw_log("drawannot.py:3373", _fw_err)
    return None



BALLOON_SHAPES = ("None", "Circular", "Triangle", "Hexagon", "Box", "Diamond", "Pentagon", "Circular Split Line",
                  "Flag - Five Sided", "Flag - Triangle", "Underline", "Square", "Square Circle", "Inspection")
BALLOON_SIZES = ("Tight Fit", "1 Character", "2 Characters", "3 Characters", "4 Characters", "5 Characters",
                 "User Defined")
QTY_DENOTATIONS = ("X", "x", " X", "PLCS", "PLACES")


def _qty_text(n, denote):
    return "%s%s" % (n, denote) if denote in ("X", "x", " X") else "%s %s" % (n, denote)


def balloon_svg(text, at, tip, shape="Circular", size=TEXT_SIZE, fit="2 Characters", lower="", pad=1.5,
                user=10.0, qty="", qty_place="Right"):
    ""

    chars = int(fit[0]) if fit[:1].isdigit() else len(text) or 1
    r = max(2.5, _text_width("0" * max(chars, 1), size) / 2 + pad)
    if fit == "Tight Fit":
        r = _text_width(text or "0", size) / 2 + max(pad - 0.3, 0.2)
    elif fit == "User Defined":
        r = max(1.0, user / 2.0)
    body = []
    if shape == "Circular Split Line":
        body.append('<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (r, STROKE))
        body.append('<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (-r, r, STROKE))
        body.append('<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                    % (-size * 0.25, size * 0.8, _esc(text)))
        body.append('<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                    % (size * 0.95, size * 0.8, _esc(lower)))
    else:
        if shape in ("Flag", "Flag - Five Sided"):
            body.append('<polygon points="%g,%g %g,%g %g,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (-r, -r * 0.8, r * 0.6, -r * 0.8, r * 1.3, r * 0.6, r * 0.8, STROKE))
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                        % (-r, -r * 0.8, -r, r * 0.8, STROKE))
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                        % (-r, r * 0.8, r * 0.6, r * 0.8, STROKE))
        elif shape == "Flag - Triangle":
            # a triangular flag: the upright side at the left, its point to the right
            body.append('<polygon points="%g,%g %g,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (-r * 0.9, -r * 1.2, r * 1.5, -r * 0.9, r * 1.2, STROKE))
        elif shape == "Pentagon":
            pts = " ".join("%g,%g" % (r * 1.15 * math.sin(math.radians(a)), -r * 1.15 * math.cos(math.radians(a)))
                           for a in range(0, 360, 72))
            body.append('<polygon points="%s" fill="none" stroke="#000" stroke-width="%g"/>' % (pts, STROKE))
        elif shape == "Square Circle":
            # the circle inside a square
            body.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (-r, -r, 2 * r, 2 * r, STROKE))
            body.append('<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (r * 0.85, STROKE))
        elif shape == "Inspection":
            # the inspection balloon: an oval with round ends round the text
            w = max(2 * r, _text_width(text or "0", size) + 2 * r * 0.8)
            body.append('<rect x="%g" y="%g" width="%g" height="%g" rx="%g" ry="%g" fill="none" stroke="#000" '
                        'stroke-width="%g"/>' % (-w / 2, -r * 0.8, w, r * 1.6, r * 0.8, r * 0.8, STROKE))
        elif shape == "Box":
            # a box as wide as the text needs, as high as the text (Square stays square)
            w = max(2 * r - 3, _text_width(text or "0", size) + 1.0)
            body.append(_frame("Box", w, size * 1.1))
        elif shape == "Underline":
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                        % (-r, size * 0.6, r, size * 0.6, STROKE))
        elif shape:
            body.append(_frame(shape, 2 * r - 3, 2 * r - 3))
        body.append('<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                    % (size * 0.35, size, _esc(text)))
    if tip is not None:
        tx, ty = _rel(at, tip)
        L = math.hypot(tx, ty)
        if L > r:
            body.append(_arrow(tx, ty, tx * r / L, ty * r / L, "Dot" if shape else "Filled arrow"))
    if qty:
        qw = _text_width(qty, size)
        qx, qy, anchor = {"Left": (-r - 1.0, size * 0.35, "end"), "Top": (0, -r - 1.0, "middle"),
                          "Bottom": (0, r + 1.0 + size, "middle")}.get(qty_place, (r + 1.0, size * 0.35, "start"))
        body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="%s">%s</text>'
                    % (qx, qy, size, anchor, _esc(qty)))
        r = r + qw + 1.0
    return "".join(body), r * 1.5 + _reach(at, tip)


ROUGH_SYMBOLS = ("Basic", "Machining Required", "Machining Prohibited")


LAYS = [("None", ""), ("Circular", "C"), ("Crossed", "X"), ("Multi-Directional", "M"), ("Parallel", "="),
        ("Perpendicular", "\u27c2"), ("Radial", "R"), ("Particulate", "P")]


FINISH_STANDARDS = ("ISO 1302", "ISO 21920-1")
ISO21920_PARAMS = ("Ra", "Rq", "Rz", "Rp", "Rv", "Rt", "Rsk", "Rku", "Rdq", "Rmr", "Rdc", "Pa", "Pt", "Pz", "Wa", "Wt", "Wz")
ISO21920_TOLERANCE = (("Upper limit (U)", "U"), ("Lower limit (L)", "L"), ("Upper and lower", "UL"), ("None", ""))
ISO21920_RULES = ("16% rule", "max rule")


def iso21920_lines(req, upper, lower):
    """ISO 21920-1 requirement text (position a, and b for the lower limit): tolerance type, transmission band
    (Ls-Lc nesting indices), parameter with its evaluation length, the comparison rule (max written, 16% the
    default and left out) and the limit value, e.g. "U 0,0025-0,8/Ra max 1,6"."""
    tol = dict(ISO21920_TOLERANCE).get(req.get("tolerance", ""), req.get("tolerance", ""))
    band = "-".join(x for x in (req.get("ls", ""), req.get("lc", "")) if x)
    par = req.get("parameter", "Ra") + (req.get("ln", "") or "")
    rule = "max " if req.get("rule", "").startswith("max") else ""

    def one(t, v):
        if not v:
            return ""
        head = (t + " ") if t else ""
        return "%s%s%s %s%s" % (head, (band + "/") if band else "", par, rule, v)
    if tol == "UL":
        return [x for x in (one("U", upper), one("L", lower)) if x]
    if tol == "L":
        return [x for x in (one("L", lower or upper),) if x]
    return [x for x in (one(tol, upper),) if x]


def finish_svg(kind, value, at, tip=None, minimum="", method="", allowance="", sampling="", lay="None",
               around=False, angle=0.0, other="", spacing="", arrow="Filled arrow", leader="Leader", iso21920=None,
               jogs=()):
    ""

    h = 6.0
    s = TEXT_SIZE * 0.8
    long_bar = bool(method or sampling)
    if iso21920 is not None:       # ISO 21920-1: the requirement lines under the long bar, b the lower limit
        lines = iso21920_lines(iso21920, value, minimum)
        value, minimum = (lines + ["", ""])[:2]
        sampling, other, spacing = "", "", ""
        long_bar = True
    per2002, anchor = True, "Closest"
    try:     # Document Properties > Annotations > Surface Finishes
        per2002 = bool(_doc_row(App.ActiveDocument, "Surface Finishes", "Display symbols per 2002", True))
        anchor = _doc_row(App.ActiveDocument, "Surface Finishes", "Leader anchor", "Closest")
    except Exception as _fw_err:
        _fw_log("drawannot.py:3485", _fw_err)
    if per2002 or long_bar:
        body = ['<polyline points="%g,%g %g,%g %g,%g %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                % (-h * 0.6, -h * 0.35, 0, h * 0.5, h * 0.9, -h, h * (3.6 if long_bar else 2.4), -h, STROKE)]
    else:
        # the symbol before ISO 1302:2002: no bar on the long leg, the value over the V
        body = ['<polyline points="%g,%g %g,%g %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                % (-h * 0.6, -h * 0.35, 0, h * 0.5, h * 0.9, -h, STROKE)]
    if kind == "Machining Required":
        body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                    % (-h * 0.6, -h * 0.35, h * 0.55, -h * 0.35, STROKE))
    elif kind == "Machining Prohibited":
        body.append('<circle cx="0" cy="%g" r="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                    % (-h * 0.05, h * 0.3, STROKE))
    if around:
        body.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                    % (h * 0.9, -h, h * 0.18, STROKE))

    def text(x, y, v, anchor="start"):
        if v:
            body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="%s">%s</text>'
                        % (x, y, s, anchor, _esc(v)))
    vx, vy = (h * 1.0, -h * 1.15) if (per2002 or long_bar) else (h * 0.2, -h * 0.7)
    text(vx, vy, value)
    text(h * 1.0, -h * 1.15 + s * 1.2, minimum)
    text(h * 1.0, -h * 1.15 - s * 1.3, method)
    text(-h * 0.7, h * 0.1, allowance, "end")
    text(h * 2.6, -h * 1.15, sampling)
    text(h * 0.9, h * 0.55, dict(LAYS).get(lay, ""))
    text(h * 1.0, -h * 1.15 + s * 2.4, other)
    text(h * (3.8 if long_bar else 2.6), -h * 1.15 + s * 1.2, spacing)
    inner = "".join(body)
    if angle:
        inner = '<g transform="rotate(%g)">%s</g>' % (-angle, inner)
    body = [inner]
    if tip is not None:
        tx, ty = _rel(at, tip)
        pts = [_rel(at, j) for j in (jogs or ())]
        if leader == "Bent Leader":
            # the shoulder runs from the symbol's point toward the side the leader goes
            side = (pts[-1][0] if pts else tx) < 0
            body.append(symbol_leader(tx, ty, -1e-9 if side else 0.0, h * 0.5, arrow, True, pts))
        else:
            ax = {"Left": -h * 0.6, "Right": h * 0.9}.get(anchor, 0)
            ay = {"Left": -h * 0.35, "Right": -h}.get(anchor, h * 0.5)
            body.append(symbol_leader(tx, ty, ax, ay, arrow, False, pts))
    return "".join(body), h * 3.7 + max([_reach(at, tip)] + [_reach(at, j) for j in (jogs or ())])


def _restroke(svg, dash="", width=0.0, tags=("line", "path")):
    """SVG lines (tags) drawn with a line style (dash pattern) and thickness (mm) other than the default."""
    if width:
        svg = svg.replace('stroke-width="%g"' % STROKE, 'stroke-width="%g"' % width)
    if dash:
        for t in tags:
            svg = svg.replace("<%s " % t, '<%s stroke-dasharray="%s" ' % (t, dash))
    return svg


def symbol_leader(tx, ty, sx, sy, arrow="Filled arrow", bent=False, jogs=()):
    """A symbol's leader (Surface Finish, Geometric Tolerance), from where it leaves the symbol (sx, sy) to the tip
    (tx, ty): bent, with a short horizontal shoulder first; jogs, the Multi-jog Leader's bend points in order from
    the tip (all svg coordinates relative to the symbol)."""
    out = []
    if bent:
        bx = sx + (-3.0 if sx < 0 else 3.0)
        out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>' % (sx, sy, bx, sy, STROKE))
        sx = bx
    pts = [tuple(j) for j in (jogs or ())]
    if pts:
        out.append(_arrow(tx, ty, pts[0][0], pts[0][1], arrow))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:] + [(sx, sy)]):
            out.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                       % (x1, y1, x2, y2, STROKE))
    else:
        out.append(_arrow(tx, ty, sx, sy, arrow))
    return "".join(out)



GTOL = [("Straightness", "⏤"), ("Flatness", "⏥"), ("Circularity", "○"), ("Cylindricity", "⌭"),
        ("Profile of a line", "⌒"), ("Profile of a surface", "⌓"), ("Parallelism", "∥"),
        ("Perpendicularity", "⟂"), ("Angularity", "∠"), ("Circular runout", "↗"),
        ("Total runout", "⌰"), ("Position", "⌖"), ("Concentricity", "◎"), ("Symmetry", "⌯")]
MATERIAL = [("None", ""), ("Maximum material", "Ⓜ"), ("Least material", "Ⓛ"),
            ("Regardless of feature size", "Ⓢ"), ("Statistical", "⟨ST⟩")]


def gtol_cells(symbol, diameter, tol, material, datums, tol2="", diameter2=False, material2="None",
               projected=None, free=False, tangent=False):
    sym = dict(GTOL).get(symbol, symbol)
    first = ("\u2300" if diameter else "") + (tol or "") + (dict(MATERIAL).get(material, "") or "")
    if projected is not None:
        first += "\u24c5" + projected
    if free:
        first += "\u24bb"
    if tangent:
        first += "\u24c9"
    cells = [sym, first]
    if tol2:
        cells.append(("\u2300" if diameter2 else "") + tol2 + (dict(MATERIAL).get(material2, "") or ""))
    cells += [d for d in datums if d]
    return cells


def gtol_svg(cells, at, tip=None, second=None, angle=0.0, leader="Leader", arrow="Filled arrow", jogs=(),
             leader_dash="", leader_width=0.0, frame_dash="", frame_width=0.0):
    ""



    size = TEXT_SIZE
    h = size * 2.0
    frame, anchor = STROKE, "Closest"
    try:      # Document Properties > Annotations > Geometric Tolerances: Frame thickness, Leader anchor
        doc = App.ActiveDocument
        t = _doc_row(doc, "Geometric Tolerances", "Frame thickness", "Thin")
        if t != "Thin":
            from . import drawdocprops
            frame = drawdocprops.thickness_mm(t, STROKE)
        anchor = _doc_row(doc, "Geometric Tolerances", "Leader anchor", "Closest")
    except Exception as _fw_err:
        _fw_log("drawannot.py:3574", _fw_err)
    if frame_width:
        frame = frame_width
    rows = [cells] + ([second] if second else [])
    widths = [max(h, _text_width(c, size) + 2.5) for c in cells]
    total = max(sum(max(h, _text_width(c, size) + 2.5) for c in r) for r in rows)
    H = h * len(rows)
    body = []
    for ri, row in enumerate(rows):
        x = -total / 2
        y = -H / 2 + ri * h
        for ci, c in enumerate(row):
            w = max(h, _text_width(c, size) + 2.5) if ri == 0 else (widths[0] if ci == 0 else
                                                                    max(h, _text_width(c, size) + 2.5))
            if ri > 0 and ci == 0:
                x += w                       # the symbol cell spans both rows
                continue
            body.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (x, y, w, h, frame))
            body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                        % (x + w / 2, y + h / 2 + size * 0.35, size, _esc(c)))
            x += w
    if second:
        body.append('<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                    % (-total / 2, -H / 2 + h, widths[0], h, frame))
    if frame_dash:
        body = [_restroke(b, frame_dash, 0.0, ("rect",)) for b in body]
    if angle:
        body = ['<g transform="rotate(%g)">%s</g>' % (-angle, "".join(body))]
    if tip is not None:
        tx, ty = _rel(at, tip)
        sx = -total / 2 if (anchor == "Left" or anchor not in ("Left", "Right") and tx < 0) else total / 2
        if angle:
            ca, sa = math.cos(math.radians(-angle)), math.sin(math.radians(-angle))
            sx, sy = sx * ca, sx * sa
        else:
            sy = 0.0
        pts = [_rel(at, j) for j in (jogs or ())]
        body.append(_restroke(symbol_leader(tx, ty, sx, sy, arrow, leader == "Bent Leader", pts),
                              leader_dash, leader_width))
        reach = max([_reach(at, tip)] + [_reach(at, j) for j in (jogs or ())])
        return "".join(body), max(total, H) / 2 + reach + (3.0 if leader == "Bent Leader" else 0.0)
    return "".join(body), max(total, H) / 2


DATUM_FRAMES = ("Square", "Round")
DATUM_LEADERS = ("Filled triangle", "Filled triangle with shoulder", "Empty triangle", "Empty triangle with shoulder")


def datum_svg(letter, at, tip, frame="Square", leader="Filled triangle", text=""):
    """A datum feature: the letter in a square (or round, GB) frame, its leader ending in a filled or empty
    triangle on the edge, with or without a shoulder (a short straight stem off the triangle)."""
    size = TEXT_SIZE
    s = size * 2.0
    if frame == "Round":
        box = '<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (s / 2, STROKE)
    else:
        box = '<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (
            -s / 2, -s / 2, s, s, STROKE)
    body = [box, '<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
            % (size * 0.35, size, _esc(letter))]
    for n, line in enumerate((text or "").splitlines()):     # the PM's Text: under the frame
        body.append('<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                    % (s / 2 + size * (1.2 + 1.4 * n), size * 0.8, _esc(line)))
    if tip is not None:
        tx, ty = _rel(at, tip)
        L = math.hypot(tx, ty)
        end = "Empty triangle" if leader.startswith("Empty") else "Filled triangle"
        if L > s / 2:
            sx, sy = tx * (s / 2) / L, ty * (s / 2) / L
            if leader.endswith("shoulder") and L > s / 2 + 3.5:
                # the shoulder: a 2.5 mm straight stem off the triangle, then the leader on to the frame
                stem = 2.5 + 2.7
                kx, ky = tx - tx / L * stem, ty - ty / L * stem
                body.append(_arrow(tx, ty, kx, ky, end))
                body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                            % (kx, ky, sx, sy, STROKE))
            else:
                body.append(_arrow(tx, ty, sx, sy, end))
    return "".join(body), s + _reach(at, tip)


def next_datum(page):
    from . import drawviews as DVv
    cur = getattr(page, "FreeWorksNextDatumLabel", "") if hasattr(page, "FreeWorksNextDatumLabel") else ""
    cur = cur or "A"
    used = {getattr(o, "SWDatum", "") for o in page.Document.Objects}
    while cur in used:
        cur = DVv._next_letter(cur)
    if not hasattr(page, "FreeWorksNextDatumLabel"):
        page.addProperty("App::PropertyString", "FreeWorksNextDatumLabel", "FreeCAD", "Next datum label")
    page.FreeWorksNextDatumLabel = DVv._next_letter(cur)
    return cur


def peek_datum(page):
    cur = getattr(page, "FreeWorksNextDatumLabel", "") if hasattr(page, "FreeWorksNextDatumLabel") else ""
    if not cur:
        try:     # Document Properties > Annotations > Datums > Next label
            cur = str(_doc_row(page.Document, "Datums", "Next label", "A") or "")
        except Exception:
            cur = ""
    return cur or "A"


_COMPS = {}     # assembly -> [(component, item key, shape, box)]: cleared whenever a model object changes


class _CompsObserver:
    def _clear(self, *_):
        _COMPS.clear()

    def slotChangedObject(self, obj, prop):
        try:
            if not obj.isDerivedFrom("TechDraw::DrawView") and not obj.isDerivedFrom("TechDraw::DrawPage") \
                    and not obj.isDerivedFrom("TechDraw::DrawTemplate"):
                _COMPS.clear()
        except Exception:
            _COMPS.clear()

    slotCreatedObject = slotDeletedObject = slotRecomputedDocument = slotDeletedDocument = slotUndoDocument = \
        slotRedoDocument = slotCreatedDocument = _clear


_COMPS_OBS = []


def _components(o):
    """The assembly's solid components in order, with their shapes and boxes (kept until the model changes)."""
    if not _COMPS_OBS:
        _COMPS_OBS.append(_CompsObserver())
        App.addDocumentObserver(_COMPS_OBS[0])
    key = (o.Document.Name, o.Name)
    got = _COMPS.get(key)
    if got is not None:
        return got
    got, seen = [], set()
    for c in o.OutList:
        if c.Name in seen:
            continue
        try:
            sh = c.Shape
            if sh.Volume > 1e-9:
                seen.add(c.Name)
                k = getattr(c, "LinkedObject", None) or c
                got.append((c, getattr(k, "Name", c.Name), sh, sh.BoundBox))
        except Exception as _fw_err:
            _fw_log("drawannot.py:3718", _fw_err)
    _COMPS[key] = got
    return got


def _ray_box(q, d, box):
    """A lower bound of the distance from the line q + t*d (d unit) to the box."""
    c = box.Center
    w = c - q
    off = w - d * w.dot(d)
    r = 0.5 * math.sqrt(box.XLength ** 2 + box.YLength ** 2 + box.ZLength ** 2)
    return max(0.0, off.Length - r)


def front_most(d, q, shapes, tol=1e-6):
    """Index of the shape the line of sight through model point q meets first (d: the view direction, toward
    the viewer), else None: a part inside another (a rod in its tube) is under the click only where it shows."""
    import Part
    dn = App.Vector(d)
    if dn.Length > 1e-12:
        dn.normalize()
    ray = Part.makeLine(q - dn * 1e5, q + dn * 1e5)
    hits = []
    for i, sh in enumerate(shapes):
        try:
            hits.append((sh.distToShape(ray)[0], i, sh))
        except Exception:
            continue
    return _front_of(dn, q, ray, hits, tol)


def _front_of(dn, q, ray, hits, tol=1e-6):
    """hits: (distance to the line of sight, index, shape). The nearest; of those the line passes through, the
    one it enters nearest the viewer."""
    if not hits:
        return None
    low = min(h[0] for h in hits)
    tied = [h for h in hits if h[0] - low <= tol]
    if len(tied) == 1 or low > tol:
        return min(tied, key=lambda h: (h[0], h[1]))[1]
    best = None
    for _dist, i, sh in tied:
        depth = -1e30
        try:
            pts = [v.Point for v in sh.section(ray).Vertexes]
            if pts:
                depth = max(p.dot(dn) for p in pts)
        except Exception as _fw_err:
            _fw_log("drawannot.py:3766", _fw_err)
        if best is None or depth > best[0] + 1e-9:
            best = (depth, i)
    return best[1]


def item_number(view, p):
    """The balloon's item number: 1 for a part; for an assembly the component under the click, in order."""
    shapes = DV.source_shapes(view)
    comps = []
    seen = set()
    for o in shapes:
        if o.TypeId == "Assembly::AssemblyObject":
            for row in _components(o):
                if row[0].Name not in seen:
                    seen.add(row[0].Name)
                    comps.append(row)
    if not comps:
        return "1", None
    import Part
    d, x, y = D.view_frame(view)
    q = DV.to_model(view, p)
    ray = Part.makeLine(q - d * 1e5, q + d * 1e5)
    names = []
    order = {}
    for c, key, sh, box in comps:
        if key not in order:
            names.append(key)
            order[key] = len(names)
    # nearest first by box, and stop once no box can be nearer than the best shape found
    dn = App.Vector(d)
    if dn.Length > 1e-12:
        dn.normalize()
    ranked = sorted(((_ray_box(q, dn, box), i) for i, (c, key, sh, box) in enumerate(comps)), key=lambda t: t[0])
    hits = []
    for low, i in ranked:
        if hits and low > min(h[0] for h in hits) + 1e-6:
            break
        try:
            hits.append((comps[i][2].distToShape(ray)[0], i))
        except Exception as _fw_err:
            _fw_log("drawannot.py:3845", _fw_err)
            continue
    j = _front_of(dn, q, ray, [(dist, i, comps[i][2]) for dist, i in hits])
    best = None
    if j is not None:
        c, key, sh, box = comps[j]
        best = (0.0, order[key], c, j)
    return (str(best[1]), best[2]) if best else ("1", None)


class _AnnotPanel(D._Panel):
    """Clicks: an optional leader point on a view first (when Leader is on), then where the annotation goes."""
    LEADER = True

    def leader_group(self, default=True, arrows=True):
        box, lay = D._group("Leader", self.form)
        self.leader = QtWidgets.QCheckBox("Leader", box)
        self.leader.setObjectName("SWAnnotLeader")
        self.leader.setChecked(default)
        lay.addWidget(self.leader)
        if arrows:
            self.arrow = QtWidgets.QComboBox(box)
            self.arrow.setObjectName("SWAnnotArrow")
            self.arrow.addItems(["Filled arrow", "Open arrow", "Dot", "Filled triangle", "None"])
            lay.addWidget(self.arrow)
        self.lay.addWidget(box)
        self.tip = None

    SYMBOL_LEADERS = ("Leader", "Multi-jog Leader", "No Leader", "Auto Leader")

    def symbol_leaders(self, prefix, shapes=("Straight", "Bent")):
        ""



        self.leader_group(default=False, arrows=True)
        lbox = self.lay.itemAt(self.lay.count() - 1).widget()
        ll = lbox.layout()
        row = QtWidgets.QGridLayout()           # two a row: one row of four made the pane wider than 300 px
        self.leader_kind = QtWidgets.QButtonGroup(lbox)
        for n, name in enumerate(self.SYMBOL_LEADERS):
            b = QtWidgets.QToolButton(lbox)
            b.setText(name)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setObjectName(prefix + name.replace(" ", "").replace("-", ""))
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.leader_kind.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
            b.setChecked(name == "No Leader")
        ll.insertLayout(0, row)
        row = QtWidgets.QHBoxLayout()
        self.leader_shape = QtWidgets.QButtonGroup(lbox)
        for n, name in enumerate(shapes):
            b = QtWidgets.QToolButton(lbox)
            b.setText(name)
            b.setToolTip(name + " Leader")
            b.setCheckable(True)
            b.setObjectName(prefix + name + "Leader")
            self.leader_shape.addButton(b, n)
            row.addWidget(b)
            b.setChecked(name == "Straight")
        row.addStretch(1)
        ll.insertLayout(1, row)
        self.leader_kind.buttonClicked.connect(lambda b: self._kind_picked())
        self.leader_kind.buttonClicked.connect(lambda b: self._shapes_shown())
        self.leader_shape.buttonClicked.connect(lambda b: self._shape_picked())
        self.leader.toggled.connect(self._leader_box)
        self.leader.hide()
        self._shapes_shown()

    def leader_type(self):
        b = self.leader_kind.checkedButton()
        return b.text() if b else ("Leader" if self.leader.isChecked() else "No Leader")

    def leader_kind_text(self):
        """The leader as the symbol drawers take it: "Bent Leader" or "Leader"."""
        b = self.leader_shape.checkedButton()
        return "Bent Leader" if b is not None and b.text() == "Bent" else "Leader"

    def _shapes_shown(self):
        ""
        on = self.leader_type() != "No Leader"
        for b in self.leader_shape.buttons():
            b.setVisible(on)
        if getattr(self, "arrow", None) is not None:
            self.arrow.setVisible(on)

    def perpendicular_jog(self, tip, p):
        """Perpendicular Leader: the bend point that makes the leader's last run meet the model edge at the tip
        square (sheet coordinates), or None off an edge."""
        b = self.leader_shape.checkedButton()
        if b is None or b.text() != "Perpendicular" or tip is None:
            return None
        view = DV.view_at(self.page, tip)
        if view is None:
            return None
        hit = edge_at(view, DV.to_geometry(view, tip), 2.0 / DV.view_scale(view))
        if hit is None:
            return None
        e = hit[1]
        try:
            g = DV.to_geometry(view, tip)
            t = e.tangentAt(e.Curve.parameter(V(g[0], g[1], 0)))
        except Exception:
            t = e.Vertexes[-1].Point - e.Vertexes[0].Point
        n = math.hypot(t.x, t.y)
        if n < 1e-9:
            return None
        nx, ny = -t.y / n, t.x / n
        d = (p[0] - tip[0]) * nx + (p[1] - tip[1]) * ny
        j = (tip[0] + nx * d, tip[1] + ny * d)
        if abs(d) < 0.5 or math.hypot(p[0] - j[0], p[1] - j[1]) < 0.5:
            return None
        return j

    def _kind_picked(self):
        self.leader.blockSignals(True)
        self.leader.setChecked(self.leader_type() != "No Leader")
        self.leader.blockSignals(False)
        self._jog_clicks = []
        self.tip = None

    def _shape_picked(self):
        if self.leader_type() == "No Leader":
            self.leader_kind.button(0).setChecked(True)
            self._kind_picked()

    def _leader_box(self, on):
        if (self.leader_type() != "No Leader") != on:
            self.leader_kind.button(0 if on else 2).setChecked(True)
            self._kind_picked()
            self._shapes_shown()

    def jog_click(self, p):
        ""

        if getattr(self, "leader_kind", None) is None or self.leader_type() != "Multi-jog Leader":
            self._jogs = []
            return False
        pts = self.__dict__.setdefault("_jog_clicks", [])
        if pts and len(pts) >= 2 and math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) < 1.5:
            tip, jogs = pts[0], pts[1:-1]
            self._jog_clicks = []
            self._jogs = [tuple(j) for j in jogs]
            obj = self.place(pts[-1], tip)
            self._jogs = []
            if obj is not None:
                self.made.append(obj)
                self.doc.recompute()
            self.say(self.AGAIN)
            return True
        pts.append(tuple(p))
        self.say("Click the next jog point, or click the same point again to place it there."
                 if len(pts) > 1 else "Click the first jog point.")
        return True

    def sheet_click(self, p):
        if self.jog_click(p):
            return True
        if self.leader.isChecked() and self.tip is None:
            self.tip = p
            self.say("Click where it goes.")
            return True
        tip, self.tip = (self.tip if self.leader.isChecked() else None), None
        obj = self.place(p, tip)
        if obj is not None:
            self.made.append(obj)
            if getattr(self, "layer", None) is not None and not getattr(obj, "SWLayer", ""):
                from . import drawpmparts as PP
                if PP.layer_of(self) != PP.NONE_LAYER:
                    PP.apply_layer(obj, PP.layer_of(self))
            self.doc.recompute()
        self.say(self.AGAIN)
        return True


# --------------------------------------------------------------------------- DW-2: the note on the pointer
def _svg_image(svg, w, h):
    """svg drawn into a w x h image with a clear background (no renderer kept: nothing shared to outlive)."""
    for mod in ("PySide6.QtSvg", "PySide2.QtSvg", "PySide.QtSvg"):
        try:
            m = __import__(mod, fromlist=["QSvgRenderer"])
            break
        except Exception:
            m = None
    if m is None:
        return None
    r = m.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    if not r.isValid():
        return None
    img = QtGui.QImage(max(1, int(w)), max(1, int(h)), QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(QtCore.Qt.transparent)
    pa = QtGui.QPainter(img)
    try:
        pa.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r.render(pa)
    finally:
        pa.end()
    return img


def note_ghost(panel, p):
    ""

    clicks = getattr(panel, "clicks", None)
    view = getattr(clicks, "view", None)
    scene = view.scene() if view is not None else None
    item = getattr(panel, "_note_ghost", None)
    if scene is None:
        return None
    if p is None:
        if item is not None:
            item.setVisible(False)
        return None
    tip = panel.tip if getattr(panel, "leader", None) is not None and panel.leader.isChecked() else None
    jogs = getattr(panel, "_jog_clicks", None) or []
    if tip is None and jogs:
        tip = jogs[0]
    f = panel.fmt()
    f["jogs"] = [list(j) for j in jogs[1:]]
    panel._attach_tip = tip
    body, reach = note_svg(panel.note_text(), p, tip, panel.arrow.currentText(), **f)
    font = doc_font(panel.page.Document)
    if font:
        body = with_font(body, font)
    svg = symbol_svg(body, reach)
    hx, hy = symbol_half(reach)
    if item is None:
        item = QtWidgets.QGraphicsPixmapItem()
        item.setOpacity(0.55)
        item.setZValue(1e6)
        item.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        scene.addItem(item)
        panel._note_ghost = item
        panel._note_ghost_svg = None
        olds = getattr(clicks, "_ghost", None)
        if not olds:                       # the PM's own clean-up (SheetClicks.stop) takes it away too
            clicks._ghost = [item]
    zoom = max(0.05, abs(view.transform().m11()))
    k = min(zoom, 4000.0 / max(1.0, 2 * hx * D.REZ), 4000.0 / max(1.0, 2 * hy * D.REZ))   # screen pixels, capped
    key = (svg, round(k, 4))
    if key != getattr(panel, "_note_ghost_svg", None):
        img = _svg_image(svg, 2 * hx * D.REZ * k, 2 * hy * D.REZ * k)
        if img is None:
            item.setVisible(False)
            return None
        item.setPixmap(QtGui.QPixmap.fromImage(img))
        panel._note_ghost_svg = key
    pm = item.pixmap()
    if pm.width() <= 0 or pm.height() <= 0:
        return None
    item.setTransform(QtGui.QTransform.fromScale(2 * hx * D.REZ / pm.width(), 2 * hy * D.REZ / pm.height()))
    item.setPos(D.to_scene(p[0] - hx, p[1] + hy))
    item.setVisible(True)
    return item


# --------------------------------------------------------------------------- the note text box's right-click menu
NUMBER = re.compile(r"^(\s*)(\d+)\.\s")


def _block_range(edit):
    """(first, last) block numbers the cursor's selection covers."""
    c = edit.textCursor()
    doc = edit.document()
    a = doc.findBlock(c.selectionStart()).blockNumber()
    b = doc.findBlock(c.selectionEnd()).blockNumber()
    return a, b


def _lines(edit):
    return edit.toPlainText().split("\n")


def _set_lines(edit, lines, keep):
    edit.setPlainText("\n".join(lines))
    c = edit.textCursor()
    blk = edit.document().findBlockByNumber(min(keep, len(lines) - 1))
    c.setPosition(blk.position() + blk.length() - 1)
    edit.setTextCursor(c)


def _number_from(lines, i):
    """The number line i continues with: one more than the numbered line above it, else 1."""
    j = i - 1
    while j >= 0:
        m = NUMBER.match(lines[j])
        if m:
            return int(m.group(2)) + 1
        if lines[j].strip():
            return 1
        j -= 1
    return 1


def note_numbering(edit, how="toggle"):
    ""

    lines = _lines(edit)
    a, b = _block_range(edit)
    if how == "toggle":
        if all(NUMBER.match(lines[i]) for i in range(a, b + 1)):
            for i in range(a, b + 1):
                lines[i] = NUMBER.sub(r"\1", lines[i], count=1)
        else:
            n = _number_from(lines, a)
            for i in range(a, b + 1):
                lines[i] = "%d. %s" % (n, NUMBER.sub(r"\1", lines[i], count=1))
                n += 1
    else:
        n = 1 if how == "restart" else _number_from(lines, a)
        i = a
        while i < len(lines) and (i <= b or NUMBER.match(lines[i])):
            lines[i] = "%d. %s" % (n, NUMBER.sub(r"\1", lines[i], count=1))
            n += 1
            i += 1
    _set_lines(edit, lines, b)
    return lines


class ParagraphDialog(QtWidgets.QDialog):
    """Paragraph Properties: the note's alignment and its first-line indent (spaces)."""

    def __init__(self, panel):
        super().__init__(Gui.getMainWindow())
        self.setObjectName("SWNoteParagraph")
        self.setWindowTitle("Paragraph Properties")
        lay = QtWidgets.QFormLayout(self)
        self.align = QtWidgets.QComboBox(self)
        self.align.setObjectName("SWNoteParagraphAlign")
        self.align.addItems(["Left", "Center", "Right"])
        b = panel.align.checkedButton() if getattr(panel, "align", None) is not None else None
        if b is not None and b.text() in ("Left", "Center", "Right"):
            self.align.setCurrentText(b.text())
        lay.addRow("Alignment:", self.align)
        self.indent = QtWidgets.QSpinBox(self)
        self.indent.setObjectName("SWNoteParagraphIndent")
        self.indent.setRange(0, 20)
        indent_label = QtWidgets.QLabel("Indent:")
        indent_label.setToolTip("Indent, in characters")
        self.indent.setToolTip("Indent, in characters")
        lay.addRow(indent_label, self.indent)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addRow(box)


def paragraph_apply(panel, edit, align, indent):
    for btn in panel.align.buttons():
        if btn.text() == align:
            btn.setChecked(True)
    if indent:
        lines = _lines(edit)
        a, b = _block_range(edit)
        for i in range(a, b + 1):
            lines[i] = " " * indent + lines[i].lstrip(" ")
        _set_lines(edit, lines, b)
    try:
        panel.retext()
    except Exception as _fw_err:
        _fw_log("drawannot.py:3953", _fw_err)


def note_menu(panel, edit):
    ""


    m = QtWidgets.QMenu(edit)
    m.setObjectName("SWNoteTextMenu")
    has_sel = edit.textCursor().hasSelection()

    def add(text, fn, on=True, name=None):
        a = m.addAction(text)
        a.setEnabled(bool(on))
        a.triggered.connect(fn)
        if name:
            a.setObjectName(name)
        return a
    add("Undo", edit.undo, edit.document().isUndoAvailable())
    m.addSeparator()
    add("Cut", edit.cut, has_sel)
    add("Copy", edit.copy, has_sel)
    add("Paste", edit.paste, edit.canPaste())
    add("Delete", lambda: edit.textCursor().removeSelectedText(), has_sel)
    m.addSeparator()
    add("Restart Numbering", lambda: note_numbering(edit, "restart"))
    add("Continue Numbering", lambda: note_numbering(edit, "continue"))
    add("Numbering", lambda: note_numbering(edit, "toggle"))
    m.addSeparator()

    def font():
        if getattr(panel, "doc_font", None) is not None:
            panel.doc_font.setChecked(False)
            from . import drawpmparts as PP
            PP._pick_font(panel)
    add("Font...", font, getattr(panel, "doc_font", None) is not None)

    def paragraph():
        dlg = ParagraphDialog(panel)
        if dlg.exec_():
            paragraph_apply(panel, edit, dlg.align.currentText(), dlg.indent.value())
    add("Paragraph Properties", paragraph, getattr(panel, "align", None) is not None)
    m.addSeparator()
    add("Select All", edit.selectAll, bool(edit.toPlainText()))
    m.addSeparator()
    rtl = add("Right to left reading order", lambda on: right_to_left(panel, edit, on))
    rtl.setCheckable(True)
    rtl.setChecked(edit.layoutDirection() == QtCore.Qt.RightToLeft)
    return m


def right_to_left(panel, edit, on):
    """Right to left reading order: the text box reads right to left and the note is right aligned."""
    edit.setLayoutDirection(QtCore.Qt.RightToLeft if on else QtCore.Qt.LeftToRight)
    o = edit.document().defaultTextOption()
    o.setTextDirection(QtCore.Qt.RightToLeft if on else QtCore.Qt.LeftToRight)
    edit.document().setDefaultTextOption(o)
    if getattr(panel, "align", None) is not None:
        for btn in panel.align.buttons():
            if btn.text() == ("Right" if on else "Left"):
                btn.setChecked(True)
        try:
            panel.retext()
        except Exception as _fw_err:
            _fw_log("drawannot.py:4017", _fw_err)


def hook_note_menu(panel, edit):
    edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
    def show(pos):
        m = note_menu(panel, edit)
        m.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        edit._sw_menu = m
        m.popup(edit.viewport().mapToGlobal(pos))
    edit.customContextMenuRequested.connect(show)


class NotePanel(_AnnotPanel):
    TITLE = "Note"
    PIXMAP = "TechDraw_Annotation"
    AGAIN = "Note placed. Click to place another, or OK."

    def _tool(self, box, name, text, tip, checkable=False, icon=None):
        b = QtWidgets.QToolButton(box)
        b.setObjectName(name)
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        if icon:
            try:
                ic = QtGui.QIcon(D.pixmap(icon))
                if not ic.isNull():
                    b.setIcon(ic)
            except Exception as _fw_err:
                _fw_log("drawannot.py:4047", _fw_err)
        return b

    def build(self):
        from . import drawpmparts as PP
        self.say("Type the note, then click where the leader points and where the note goes.")
        self._style_skip = {"SWNoteX", "SWNoteY", "SWNoteLock"}
        PP.style_group(self)
        box, lay = D._group("Text", self.form)
        self.text = QtWidgets.QPlainTextEdit(box)
        self.text.setObjectName("SWNoteText")
        self.text.setMaximumHeight(80)
        self.text.textChanged.connect(self.retext)
        hook_note_menu(self, self.text)
        lay.addWidget(self.text)
        self.lay.addWidget(box)
        box, lay = D._group("Text Format", self.form)
        row = QtWidgets.QGridLayout()           # two a row: the four in one row made the pane 315 px wide
        self.align = QtWidgets.QButtonGroup(box)
        for n, name in enumerate(("Left", "Center", "Right", "Fit text")):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            b.setCheckable(True)
            b.setObjectName("SWNoteAlign" + name.replace(" ", ""))
            b.setToolTip({"Left": "Left Align", "Center": "Center Align", "Right": "Right Align"}.get(name, "Fit Text"))
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.align.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
            if name == "Left":
                b.setChecked(True)
        self.align.buttonClicked.connect(lambda *_: self.retext())
        lay.addLayout(row)
        grid = QtWidgets.QGridLayout()
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWNoteAngle")
        self.angle.setRange(-360, 360)
        self.angle.setSuffix("°")
        self.font_size = QtWidgets.QDoubleSpinBox(box)
        self.font_size.setObjectName("SWNoteFontSize")
        self.font_size.setRange(0.5, 100)
        self.font_size.setValue(TEXT_SIZE)
        self.font_size.setSuffix("mm")
        grid.addWidget(QtWidgets.QLabel("Angle:", box), 0, 0)
        grid.addWidget(self.angle, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Font height:", box), 1, 0)
        grid.addWidget(self.font_size, 1, 1)
        self.angle.valueChanged.connect(lambda *_: self.retext())
        self.font_size.valueChanged.connect(lambda *_: self.retext())
        lay.addLayout(grid)
        row = QtWidgets.QHBoxLayout()
        self.link_button = self._tool(box, "SWNoteHyperlink", "Link", "Insert Hyperlink", icon="Std_Hyperlink")
        self.prop_button = self._tool(box, "SWNoteLinkProperty", "Prop", "Link to Property",
                                      icon="Std_DlgParameter")
        self.symbol_button = self._tool(box, "SWNoteAddSymbol", "Sym", "Add Symbol")      # not a second "⌀" next to Hole Callout
        self.lock = self._tool(box, "SWNoteLock", "Lock", "Lock/Unlock Note", checkable=True, icon="Std_ToggleFreeze")
        self.link_button.clicked.connect(self.insert_hyperlink)
        self.prop_button.clicked.connect(self.link_property)
        self.symbol_button.clicked.connect(self.add_symbol)
        self.lock.toggled.connect(self.relock)
        self.gtol_button = self._tool(box, "SWNoteInsertGtol", "\u2316", "Insert Geometric Tolerance",
                                      icon="TechDraw_GeometricHatch")
        self.finish_button = self._tool(box, "SWNoteInsertFinish", "\u221a", "Insert Surface Finish Symbol",
                                        icon="TechDraw_SurfaceFinishSymbols")
        self.datum_button = self._tool(box, "SWNoteInsertDatum", "A", "Insert Datum Feature",
                                       icon="TechDraw_Annotation")
        self.datum_button.clicked.connect(self.insert_datum)
        self.hole_button = self._tool(box, "SWNoteInsertHole", "\u2300", "Insert Hole Callout", checkable=True,
                                      icon="TechDraw_HoleCircle")
        self.painter = self._tool(box, "SWNoteFormatPainter", "Paint", "Format Painter", checkable=True)
        self.gtol_button.clicked.connect(self.insert_gtol)
        self.finish_button.clicked.connect(self.insert_finish)
        self.hole_button.toggled.connect(lambda on: on and (self.painter.setChecked(False), self.say(
            "Click the edge of a hole in a view: its callout goes into the note.")))
        self.painter.toggled.connect(lambda on: on and (self.hole_button.setChecked(False), self.say(
            "Click a note on the sheet: its format is copied to this note.")))

        # Tolerance, Insert Surface Finish Symbol, Insert Datum Feature (FreeCAD keeps Hole Callout, Format Painter)
        for b in (self.link_button, self.prop_button, self.symbol_button, self.lock):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        for b in (self.gtol_button, self.finish_button, self.datum_button, self.hole_button, self.painter):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        PP.format_group(self, box=box, lay=lay)
        self.upper = QtWidgets.QCheckBox("All uppercase", box)
        self.upper.setObjectName("SWNoteUpper")
        self.upper.toggled.connect(lambda *_: self.retext())
        lay.addWidget(self.upper)
        self.lay.addWidget(box)
        self.leader_group(default=False)
        lbox = self.lay.itemAt(self.lay.count() - 1).widget()
        ll = lbox.layout()
        row = QtWidgets.QGridLayout()           # two a row: one row of five made the pane 557 px wide
        self.leader_kind = QtWidgets.QButtonGroup(lbox)
        for n, name in enumerate(NOTE_LEADERS):
            b = QtWidgets.QToolButton(lbox)
            b.setText(name)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setObjectName("SWNote" + name.replace(" ", ""))
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self.leader_kind.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
            b.setChecked(name == "Auto Leader")
        self.leader.setChecked(True)                # (Auto Leader); one started on the empty sheet has none
        self.leader_kind.buttonClicked.connect(self.pick_leader)
        self.leader.toggled.connect(self._leader_toggled)
        self.leader.hide()
        ll.insertLayout(0, row)
        row = QtWidgets.QHBoxLayout()
        self.leader_style = QtWidgets.QButtonGroup(lbox)
        for n, name in enumerate(("Straight", "Bent", "Underlined")):
            b = QtWidgets.QToolButton(lbox)
            b.setText(name)
            b.setToolTip(name + " Leader")
            b.setCheckable(True)
            b.setObjectName("SWNoteLeader" + name)
            self.leader_style.addButton(b, n)
            row.addWidget(b)
            b.setChecked(name == "Bent")
        self.leader_style.buttonClicked.connect(lambda *_: self.retext())
        ll.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        self.attach = QtWidgets.QButtonGroup(lbox)
        for n, name in enumerate(("Left", "Nearest", "Right")):
            b = QtWidgets.QToolButton(lbox)
            b.setText(name)
            b.setToolTip("Leader " + name)
            b.setCheckable(True)
            b.setObjectName("SWNoteAttach" + name)
            self.attach.addButton(b, n)
            row.addWidget(b)
            b.setChecked(name == "Nearest")
        self.attach.buttonClicked.connect(lambda *_: self.retext())
        ll.addLayout(row)
        self.arrow.currentTextChanged.connect(lambda *_: self.retext())
        box, lay = D._group("Leader Style", self.form)
        self.leader_doc = QtWidgets.QCheckBox("Use document display", box)
        self.leader_doc.setObjectName("SWNoteLeaderDoc")
        self.leader_doc.setChecked(True)
        from . import drawpmparts as PP2
        self.leader_line = QtWidgets.QComboBox(box)
        self.leader_line.setObjectName("SWNoteLeaderLine")
        self.leader_line.addItems(PP2.LINE_STYLES)
        self.leader_thick = QtWidgets.QComboBox(box)
        self.leader_thick.setObjectName("SWNoteLeaderThickness")
        self.leader_thick.addItems(PP2.THICKNESSES)
        for w in (self.leader_line, self.leader_thick):
            w.currentTextChanged.connect(lambda *_: self.retext())
        DL.sets(self.leader_doc, False, self.leader_line, self.leader_thick)   # a pick turns Use document display off
        self.leader_doc.toggled.connect(lambda *_: self.retext())
        for w in (self.leader_doc, self.leader_line, self.leader_thick):
            lay.addWidget(w)
        self.lay.addWidget(box)
        box, lay = D._group("Border", self.form)
        self.border = QtWidgets.QComboBox(box)
        self.border.setObjectName("SWNoteBorder")
        self.border.addItems(NOTE_BORDERS)
        self.border.currentTextChanged.connect(lambda *_: self.retext())
        lay.addWidget(self.border)
        self.border_size = QtWidgets.QComboBox(box)
        self.border_size.setObjectName("SWNoteBorderSize")
        self.border_size.addItems(BORDER_SIZES)
        self.pad = QtWidgets.QDoubleSpinBox(box)
        self.pad.setObjectName("SWNoteBorderPadding")
        self.pad.setRange(0, 50)
        self.pad.setValue(1.5)
        self.pad.setPrefix("Padding: ")
        self.pad.setSuffix("mm")
        self.border_user = QtWidgets.QDoubleSpinBox(box)
        self.border_user.setObjectName("SWNoteBorderUser")
        self.border_user.setRange(1, 500)
        self.border_user.setValue(10.0)
        self.border_user.setPrefix("User defined: ")
        self.border_user.setSuffix("mm")
        for w in (self.border_size, self.pad, self.border_user):
            lay.addWidget(w)
            sig = w.currentTextChanged if isinstance(w, QtWidgets.QComboBox) else w.valueChanged
            sig.connect(lambda *_: (self.reborder(), self.retext()))
        self.border.currentTextChanged.connect(lambda *_: self.reborder())
        self.lay.addWidget(box)
        self.reborder()
        self.wrap = QtWidgets.QGroupBox("Wordwrap", self.form)
        self.wrap.setObjectName("SWNoteWordwrap")
        self.wrap.setCheckable(True)
        self.wrap.setChecked(False)
        wl = QtWidgets.QVBoxLayout(self.wrap)
        self.wrap_width = QtWidgets.QDoubleSpinBox(self.wrap)
        self.wrap_width.setObjectName("SWNoteWrapWidth")
        self.wrap_width.setRange(2, 1000)
        self.wrap_width.setValue(50.0)
        self.wrap_width.setSuffix("mm")
        wl.addWidget(self.wrap_width)
        self.wrap.toggled.connect(lambda *_: self.retext())
        self.wrap_width.valueChanged.connect(lambda *_: self.retext())
        self.lay.addWidget(self.wrap)
        DL.fold(self.wrap)
        box, lay = D._group("Parameters", self.form)
        grid = QtWidgets.QGridLayout()
        self.px = QtWidgets.QDoubleSpinBox(box)
        self.px.setObjectName("SWNoteX")
        self.py = QtWidgets.QDoubleSpinBox(box)
        self.py.setObjectName("SWNoteY")
        for n, (lab, w) in enumerate((("X:", self.px), ("Y:", self.py))):
            w.setRange(-10000, 10000)
            w.setDecimals(2)
            w.setSuffix("mm")
            w.valueChanged.connect(self.reposition)
            grid.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        self.xy_box = box
        box.hide()                     # X / Y show once there is a note to move
        PP.layer_group(self)
        self.last = None
        self.hyperlink = ""

    def reborder(self):
        on = self.border.currentText() != "None"
        DL.row(self.border_size, on)
        DL.row(self.pad, on)
        DL.row(self.border_user, on and self.border_size.currentText() == "User Defined")

    def fmt(self):
        from . import drawpmparts as PP
        b = self.align.checkedButton()
        ls = self.leader_style.checkedButton()
        at = self.attach.checkedButton()
        custom = not self.leader_doc.isChecked()
        th = self.leader_thick.currentText()
        return dict(size=self.font_size.value(), align=b.text() if b else "Left", angle=self.angle.value(),
                    border=self.border.currentText(), font=PP.font_of(self), upper=self.upper.isChecked(),
                    wrap=self.wrap_width.value() if self.wrap.isChecked() else 0.0,
                    leader_style="Spline" if self.leader_type() == "Spline Leader" else (ls.text() if ls else "Bent"),
                    attach=at.text() if at else "Nearest",
                    pad=self.pad.value(), border_size=self.border_size.currentText(),
                    border_user=self.border_user.value(), link=bool(self.hyperlink),
                    leader_dash=PP.DASHES.get(self.leader_line.currentText(), "") if custom else "",
                    leader_width=float(th[:-2]) if custom and th != "Default" else 0.0, look=PP.font_look(self),
                    jogs=[list(j) for j in (getattr(self, "_jogs", None) or [])])

    def note_text(self):
        return resolve_properties(self.page, self.text.toPlainText() or "Note", getattr(self, "_attach_tip", None))

    # Leader: Auto Leader, Leader, No Leader, Spline Leader
    def leader_type(self):
        b = self.leader_kind.checkedButton()
        return b.text() if b else ("Leader" if self.leader.isChecked() else "No Leader")

    def pick_leader(self, *_):
        kind = self.leader_type()
        self.leader.blockSignals(True)
        self.leader.setChecked(kind != "No Leader")
        self.leader.blockSignals(False)
        for b in self.leader_style.buttons():
            DL.row(b, kind in ("Leader", "Auto Leader", "Multi-jog Leader"))
        self.retext()

    def _leader_toggled(self, on):
        want = "Leader" if on else "No Leader"
        if on and self.leader_type() != "No Leader":
            return
        for b in self.leader_kind.buttons():
            if b.text() == want:
                b.setChecked(True)
        self.pick_leader()

    def sheet_click(self, p):
        if getattr(self, "editing", None) is not None:
            return False                     # editing a picked note: clicks go on to the sheet
        if self.hole_button.isChecked():
            return self._pick_hole(p)
        if self.painter.isChecked():
            return self._pick_format(p)
        if self.leader_type() == "Multi-jog Leader":

            # again) where the note goes
            pts = self.__dict__.setdefault("_jog_clicks", [])
            if pts and math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) < 1.5 and len(pts) >= 2:
                tip, jogs = pts[0], pts[1:-1]
                self.__dict__["_jog_clicks"] = []
                self._jogs = [tuple(j) for j in jogs]
                obj = self.place(pts[-1], tip)
                if obj is not None:
                    self.made.append(obj)
                    self.doc.recompute()
                self._jogs = [tuple(j) for j in jogs]
                self.say(self.AGAIN)
                return True
            pts.append(tuple(p))
            self.say("Click the next jog point, or click the same point again to place the note there."
                     if len(pts) > 1 else "Click the first jog point.")
            return True
        self._jogs = []
        if self.leader_type() == "Auto Leader" and self.tip is None:
            # Auto Leader: a leader when the note is started on the model (a view), none on the empty sheet
            if DV.view_at(self.page, p) is None:
                obj = self.place(p, None)
                if obj is not None:
                    self.made.append(obj)
                    self.doc.recompute()
                self.say(self.AGAIN)
                return True
        return _AnnotPanel.sheet_click(self, p)

    # Text Format: Insert Geometric Tolerance, Insert Surface Finish, Insert Hole Callout, Format Painter
    def insert_gtol(self):
        """The geometric tolerance frame typed into the note, cell by cell: |symbol|tolerance|datums|."""
        from . import drawpmparts as PP
        spec = PP.ASK.pop("gtol", None)
        if spec is None:
            spec = self._gtol_dialog()
            if spec is None:
                return
        symbol, diameter, tol, material, datums = spec
        cells = gtol_cells(symbol, diameter, tol, material, list(datums))
        self.text.insertPlainText("|" + "|".join(cells) + "|")

    def _gtol_dialog(self):
        dlg = QtWidgets.QDialog(Gui.getMainWindow())
        dlg.setObjectName("SWNoteGtolDialog")
        dlg.setWindowTitle("Geometric Tolerance")
        g = QtWidgets.QGridLayout(dlg)
        sym = QtWidgets.QComboBox(dlg)
        sym.setObjectName("SWNoteGtolSymbol")
        for name, ch in GTOL:
            sym.addItem("%s  %s" % (ch, name), name)
        dia = QtWidgets.QCheckBox("\u2300", dlg)
        dia.setObjectName("SWNoteGtolDiameter")
        tol = QtWidgets.QLineEdit("0.05", dlg)
        tol.setObjectName("SWNoteGtolTolerance")
        mat = QtWidgets.QComboBox(dlg)
        mat.setObjectName("SWNoteGtolMaterial")
        mat.addItems([m for m, _ in MATERIAL])
        datums = []
        for n, lab in enumerate(("Primary:", "Secondary:", "Tertiary:")):
            e = QtWidgets.QLineEdit(dlg)
            e.setObjectName("SWNoteGtolDatum%d" % (n + 1))
            e.setMaxLength(3)
            datums.append(e)
            g.addWidget(QtWidgets.QLabel(lab, dlg), 3 + n, 0)
            g.addWidget(e, 3 + n, 1)
        g.addWidget(QtWidgets.QLabel("Symbol:", dlg), 0, 0)
        g.addWidget(sym, 0, 1)
        g.addWidget(dia, 1, 0)
        g.addWidget(tol, 1, 1)
        g.addWidget(QtWidgets.QLabel("Material condition:", dlg), 2, 0)
        g.addWidget(mat, 2, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        g.addWidget(bb, 6, 0, 1, 2)
        if not dlg.exec_():
            return None
        return (sym.currentData(), dia.isChecked(), tol.text().strip(), mat.currentText(),
                [e.text().strip().upper() for e in datums])

    def insert_datum(self):
        """Insert Datum Feature: the datum letter in its frame, in the note (the sheet's next datum label unless
        another is typed; the label is not used up)."""
        from . import drawpmparts as PP
        letter = PP.ASK.pop("datum", None)
        if letter is None:
            letter, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Datum Feature", "Label:",
                                                        QtWidgets.QLineEdit.Normal, peek_datum(self.page))
            if not ok:
                return
        letter = str(letter).strip().upper()
        if letter:
            self.text.insertPlainText("|%s|" % letter)

    def insert_finish(self):
        """The surface finish symbol and its roughness typed into the note."""
        from . import drawpmparts as PP
        spec = PP.ASK.pop("finish", None)
        if spec is None:
            dlg = QtWidgets.QDialog(Gui.getMainWindow())
            dlg.setObjectName("SWNoteFinishDialog")
            dlg.setWindowTitle("Surface Finish")
            g = QtWidgets.QGridLayout(dlg)
            kind = QtWidgets.QComboBox(dlg)
            kind.setObjectName("SWNoteFinishSymbol")
            kind.addItems(ROUGH_SYMBOLS)
            val = QtWidgets.QLineEdit("3.2", dlg)
            val.setObjectName("SWNoteFinishRoughness")
            lay = QtWidgets.QComboBox(dlg)
            lay.setObjectName("SWNoteFinishLay")
            lay.addItems([n for n, _ in LAYS])
            for n, (lab, w) in enumerate((("Symbol:", kind), ("Maximum roughness:", val), ("Lay direction:", lay))):
                g.addWidget(QtWidgets.QLabel(lab, dlg), n, 0)
                g.addWidget(w, n, 1)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            g.addWidget(bb, 3, 0, 1, 2)
            if not dlg.exec_():
                return
            spec = (kind.currentText(), val.text().strip(), lay.currentText())
        kind, value, lay = (tuple(spec) + ("None",))[:3]
        mark = {"Basic": "\u221a", "Machining Required": "\u2207", "Machining Prohibited": "\u221a\u25cb"}.get(kind, "\u221a")
        text = mark + (value or "") + (dict(LAYS).get(lay, "") or "")
        self.text.insertPlainText(text)

    def _pick_hole(self, p):
        """Insert Hole Callout: the clicked hole's callout text into the note."""
        view, hit = circle_under(self.page, p, 2.0)
        if view is None:
            self.say("Click the edge of a hole inside a drawing view.")
            return True
        k = DV.view_scale(view)
        if hit is None:
            self.say("Click on a hole's edge.")
            return True
        _i, c, r = hit
        text = hole_text(view, c, r)
        text = re.sub(r"%\.(\d)w", lambda m: ("%%.%df" % int(m.group(1))) % (2 * r), text)
        text = text.replace("%w", "%g" % (2 * r))
        self.text.insertPlainText(text)
        self.hole_button.setChecked(False)
        self.say("Hole callout added to the note. Type more, or click where the note goes.")
        return True

    def _pick_format(self, p):
        """Format Painter: the clicked note's format (text, border, leader) copied to this note."""
        import json
        best, near = None, 1e9
        for o in self.page.Views:
            if getattr(o, "SWAnnotation", "") != "Note" or "SWNoteOptions" not in o.PropertiesList:
                continue
            if o is self.last:
                continue
            dd = math.hypot(float(o.X) - p[0], float(o.Y) - p[1])
            if dd < near:
                best, near = o, dd
        if best is None or near > 30:
            self.say("Click a note on the sheet.")
            return True
        try:
            f = json.loads(best.SWNoteOptions)
        except Exception:
            f = {}
        self.load_format(f)
        self.painter.setChecked(False)
        self.say("Format copied from %s." % best.Label)
        return True

    def load_format(self, f):
        def pick(group, text):
            for b in group.buttons():
                if b.text() == text:
                    b.setChecked(True)
        if "size" in f:
            self.font_size.setValue(float(f["size"]))
        if "angle" in f:
            self.angle.setValue(float(f["angle"]))
        if "align" in f:
            pick(self.align, f["align"])
        if "border" in f:
            self.border.setCurrentText(f["border"])
        if "border_size" in f:
            self.border_size.setCurrentText(f["border_size"])
        if "pad" in f:
            self.pad.setValue(float(f["pad"]))
        if "upper" in f:
            self.upper.setChecked(bool(f["upper"]))
        if f.get("wrap"):
            self.wrap.setChecked(True)
            self.wrap_width.setValue(float(f["wrap"]))
        if f.get("leader_style") in ("Straight", "Bent", "Underlined"):
            pick(self.leader_style, f["leader_style"])
        if f.get("leader_style") == "Spline":
            pick(self.leader_kind, "Spline Leader")
            self.pick_leader()
        if "attach" in f:
            pick(self.attach, f["attach"])
        if f.get("font") and f["font"] != "osifont, Arial" and getattr(self, "doc_font", None) is not None:
            self.doc_font.setChecked(False)         # the picked font (Choose Font) comes along
            self.font_family.setText(f["font"])
            look = f.get("look", "") or ""
            m = re.search(r'letter-spacing="([\d.]+)"', look)
            self.font_more = dict(style=("Bold " if "bold" in look else "") + ("Italic" if "italic" in look else "")
                                  or "Regular", space=float(m.group(1)) if m else 0.0,
                                  strike="line-through" in look, underline='underline' in look)
            self.font_more["style"] = self.font_more["style"].strip()
        self.retext()

    def sheet_move(self, p):
        try:
            busy = getattr(self, "editing", None) is not None or self.hole_button.isChecked() \
                or self.painter.isChecked()
            note_ghost(self, None if busy else p)
        except Exception as _fw_err:
            _fw_log("drawannot.py:note ghost", _fw_err)

    def place(self, p, tip):
        try:
            note_ghost(self, None)             # the placed note takes the ghost's place
        except Exception as _fw_err:
            _fw_log("drawannot.py:note ghost off", _fw_err)
        self._attach_tip = tip
        text = self.note_text()
        body, reach = note_svg(text, p, tip, self.arrow.currentText(), **self.fmt())
        s = svg_symbol(self.page, "Note", body, reach, p, "Note%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "Note"])), "Note")
        s.addProperty("App::PropertyString", "SWText", "FreeCAD", "note text")
        s.SWText = self.text.toPlainText() or "Note"
        s.addProperty("App::PropertyVector", "SWTip", "FreeCAD", "leader point")
        s.SWTip = V(tip[0], tip[1], 0) if tip else V(0, 0, -1)
        s.addProperty("App::PropertyString", "SWNoteFormat", "FreeCAD", "alignment, angle, height, border")
        self._store(s)
        if self.hyperlink:
            s.addProperty("App::PropertyString", "SWHyperlink", "FreeCAD", "hyperlink")
            s.SWHyperlink = self.hyperlink
        try:
            s.LockPosition = self.lock.isChecked()
        except Exception as _fw_err:
            _fw_log("drawannot.py:4525", _fw_err)
        from . import drawpmparts as PP
        if PP.layer_of(self) != PP.NONE_LAYER:
            PP.apply_layer(s, PP.layer_of(self))
        self.last = s
        self._show_xy()
        self._empty[s.Name] = not self.text.toPlainText().strip()

        QtCore.QTimer.singleShot(0, self._type_here)
        return s

    def _type_here(self):
        try:
            self.text.setFocus(QtCore.Qt.OtherFocusReason)
            self.text.selectAll()
        except RuntimeError as _fw_err:
            _fw_log("drawannot.py:note focus", _fw_err)

    @property
    def _empty(self):
        return self.__dict__.setdefault("_empty_notes", {})

    def _store(self, s):
        import json
        f = self.fmt()
        s.SWNoteFormat = "%s|%g|%g|%s" % (f["align"], f["angle"], f["size"], f["border"])
        if "SWNoteOptions" not in s.PropertiesList:
            s.addProperty("App::PropertyString", "SWNoteOptions", "FreeCAD", "the Note PM's other options")
        s.SWNoteOptions = json.dumps(f)

    def _show_xy(self):
        s = self.last
        for w, v in ((self.px, float(s.X)), (self.py, float(s.Y))):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        if getattr(self, "xy_box", None) is not None:
            self.xy_box.show()

    def reposition(self, *_):
        s = self.last
        if s is None:
            return
        dx, dy = self.px.value() - float(s.X), self.py.value() - float(s.Y)
        s.X, s.Y = self.px.value(), self.py.value()
        if s.SWTip.z >= 0:
            s.SWTip = V(s.SWTip.x + dx, s.SWTip.y + dy, 0)
        self.doc.recompute()

    def relock(self, on):
        for s in self.made:
            try:
                s.LockPosition = bool(on)
            except Exception as _fw_err:
                _fw_log("drawannot.py:4564", _fw_err)

    def insert_hyperlink(self):
        from . import drawpmparts as PP
        url = PP.ASK.pop("hyperlink", None)
        if url is None:
            url, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Insert Hyperlink", "Address:",
                                                     text=self.hyperlink)
            if not ok:
                return
        self.hyperlink = url.strip()
        if self.last is not None:
            if "SWHyperlink" not in self.last.PropertiesList:
                self.last.addProperty("App::PropertyString", "SWHyperlink", "FreeCAD", "hyperlink")
            self.last.SWHyperlink = self.hyperlink
        if not self.text.toPlainText().strip():
            self.text.setPlainText(self.hyperlink)
        self.retext()

    def link_property(self):
        ""

        from . import drawpmparts as PP
        pick = PP.ASK.pop("property", None)
        if pick is None:
            dlg = LinkPropertyDialog(self.page, getattr(self, "tip", None))
            dlg.on_pick = self._insert_link              # Keep Visible: each OK links one more
            self.link_dialog = dlg
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            pick = dlg.choice()
        self._insert_link(pick)

    def _insert_link(self, pick):
        where, _, key = pick.partition("  ")
        token = '$%s:"%s"' % (LINK_SOURCES.get(where, "PRP"), key.strip())
        self.text.insertPlainText(token)

    def add_symbol(self):
        from . import drawpmparts as PP
        pick = PP.ASK.pop("symbol", None)
        if pick is None:
            dlg = SymbolLibraryDialog()
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            ch = dlg.symbol()
        else:
            ch = pick.split("  ")[0] if "  " in pick else library_symbol(pick)
        if ch:
            self.text.insertPlainText(ch)

    def retext(self):
        s = self.last
        if s is None:
            return
        tip = (s.SWTip.x, s.SWTip.y) if s.SWTip.z >= 0 else None
        self._attach_tip = tip
        text = self.note_text()
        body, reach = note_svg(text, (float(s.X), float(s.Y)), tip, self.arrow.currentText(), **self.fmt())
        self._store(s)
        s.Symbol = symbol_svg(body, reach)
        s.SWText = self.text.toPlainText() or "Note"
        if self.text.toPlainText().strip():
            self._empty[s.Name] = False
        if getattr(s, "SWLayer", ""):
            from . import drawpmparts as PP
            PP.apply_layer(s)
        self.doc.recompute()

    def finish(self):
        from . import drawpmparts as PP

        for name, empty in list(self._empty.items()):
            o = self.doc.getObject(name)
            if empty and o is not None:
                try:
                    if o in self.made:
                        self.made.remove(o)
                    self.doc.removeObject(name)
                except Exception as _fw_err:
                    _fw_log("drawannot.py:empty note", _fw_err)
        PP.finish_layers(self)


NOTE_EDIT = []      # the Note PM opened on a picked note


def edit_note(s, page=None):
    ""
    import json
    if page is None:
        page = next((o for o in s.InList if o.TypeId == "TechDraw::DrawPage"), None) or D.active_page()
    if page is None:
        return None
    pn = NotePanel(page)
    pn.editing = s
    pn.last = s
    pn.text.blockSignals(True)
    pn.text.setPlainText(str(getattr(s, "SWText", "") or ""))
    pn.text.blockSignals(False)
    try:
        f = json.loads(s.SWNoteOptions) if "SWNoteOptions" in s.PropertiesList else {}
    except Exception:
        f = {}
    if f:
        pn.load_format(f)
    pn._show_xy()
    pn.say("Edit the note's text and options, then OK.")
    D._show(pn)
    NOTE_EDIT[:] = [pn]
    return pn


class BalloonPanel(_AnnotPanel):
    TITLE = "Balloon"
    PIXMAP = "TechDraw_Balloon"
    AGAIN = "Balloon placed. Click an edge for the next one, or OK."
    SHAPES = BALLOON_SHAPES

    def build(self):
        from . import drawpmparts as PP
        self.say("If you need to order balloons sequentially, a Bill of Materials is required.\n"
                 "To insert flag notes in balloons, select Flag Note Bank.\n"
                 "Click on the part in a view, then where the balloon goes.")

        self.flag_box = QtWidgets.QGroupBox("Flag Note Bank", self.form)
        self.flag_box.setObjectName("SWBalloonFlagBank")
        self.flag_box.setCheckable(True)
        self.flag_box.setChecked(False)
        fl = QtWidgets.QVBoxLayout(self.flag_box)
        self.flag_note = QtWidgets.QComboBox(self.flag_box)
        self.flag_note.setObjectName("SWBalloonFlagNote")
        fl.addWidget(self.flag_note)
        self.flag_none = QtWidgets.QLabel("The sheet has no flag note bank: add one with Annotations > Flag Note.",
                                          self.flag_box)
        self.flag_none.setWordWrap(True)
        fl.addWidget(self.flag_none)
        self.lay.addWidget(self.flag_box)
        self.fill_flags()
        DL.fold(self.flag_box)
        self.flag_box.toggled.connect(lambda on: on and self.fill_flags())
        PP.style_group(self)
        box, lay = D._group("Settings", self.form)
        self.shape = QtWidgets.QComboBox(box)
        self.shape.setObjectName("SWBalloonStyle")
        self.shape.addItems(self.SHAPES)
        self.shape.setCurrentText("Circular")
        lay.addWidget(self.shape)
        self.kind = QtWidgets.QComboBox(box)
        self.kind.setObjectName("SWBalloonText")

        self.kind.addItems(["Text", "Item Number", "Quantity", "Custom Properties", "Part Number (BOM)", "File Name"])
        self.kind.setCurrentText("Item Number")
        self.fit = QtWidgets.QComboBox(box)
        self.fit.setObjectName("SWBalloonSize")
        self.fit.addItems(BALLOON_SIZES)
        self.fit.setCurrentText("2 Characters")
        lay.addWidget(self.fit)
        self.pad = QtWidgets.QDoubleSpinBox(box)
        self.pad.setObjectName("SWBalloonPadding")
        self.pad.setRange(0, 50)
        self.pad.setValue(1.5)
        self.pad.setPrefix("Padding: ")
        self.pad.setSuffix("mm")
        self.user = QtWidgets.QDoubleSpinBox(box)
        self.user.setObjectName("SWBalloonUser")
        self.user.setRange(1, 200)
        self.user.setValue(10.0)
        self.user.setPrefix("User defined: ")
        self.user.setSuffix("mm")
        self.fit.currentTextChanged.connect(lambda t: DL.row(self.user, t == "User Defined"))
        lay.addWidget(self.pad)
        lay.addWidget(self.user)
        lay.addWidget(QtWidgets.QLabel("Balloon text:", box))
        lay.addWidget(self.kind)
        self.custom = QtWidgets.QLineEdit(box)
        self.custom.setObjectName("SWBalloonCustom")
        lay.addWidget(self.custom)
        lay.addWidget(QtWidgets.QLabel("Lower text:", box))
        self.lower_kind = QtWidgets.QComboBox(box)
        self.lower_kind.setObjectName("SWBalloonLowerText")
        self.lower_kind.addItems(["Text", "Item Number", "Quantity", "Custom Properties", "Part Number (BOM)",
                                  "File Name"])
        self.lower_kind.setCurrentText("Quantity")
        self.lower_custom = QtWidgets.QLineEdit(box)
        self.lower_custom.setObjectName("SWBalloonLowerCustom")
        lay.addWidget(self.lower_kind)
        lay.addWidget(self.lower_custom)
        self.lay.addWidget(box)
        self.lower_label = lay.itemAt(lay.indexOf(self.lower_kind) - 1).widget()

        def reshow(*_):

            # the lower text for a split balloon
            split = self.shape.currentText() == "Circular Split Line"
            self.custom.setVisible(self.kind.currentText() in ("Text", "Custom Property", "Custom Properties"))
            for w in (self.lower_label, self.lower_kind):
                w.setVisible(split)
            self.lower_custom.setVisible(split and self.lower_kind.currentText() in ("Text", "Custom Property",
                                                                                       "Custom Properties"))
        for w in (self.shape, self.kind, self.lower_kind):
            w.currentTextChanged.connect(reshow)
        reshow()
        DL.row(self.user, self.fit.currentText() == "User Defined")
        self.qty = QtWidgets.QGroupBox("Quantity", self.form)
        self.qty.setObjectName("SWBalloonQuantity")
        self.qty.setCheckable(True)
        self.qty.setChecked(False)
        ql = QtWidgets.QVBoxLayout(self.qty)
        row = QtWidgets.QHBoxLayout()
        self.qty_place = QtWidgets.QButtonGroup(self.qty)
        for n, name in enumerate(("Left", "Right", "Top", "Bottom")):
            b = QtWidgets.QToolButton(self.qty)
            b.setText(name)
            b.setToolTip("Quantity " + name)
            b.setCheckable(True)
            b.setObjectName("SWBalloonQty" + name)
            b.setChecked(name == "Right")
            self.qty_place.addButton(b, n)
            row.addWidget(b)
        ql.addLayout(row)
        ql.addWidget(QtWidgets.QLabel("Quantity denotation:", self.qty))
        self.qty_denote = QtWidgets.QComboBox(self.qty)
        self.qty_denote.setObjectName("SWBalloonQtyDenote")
        self.qty_denote.addItems(QTY_DENOTATIONS)
        ql.addWidget(self.qty_denote)
        self.qty_override = QtWidgets.QCheckBox("Override value:", self.qty)
        self.qty_override.setObjectName("SWBalloonQtyOverride")
        self.qty_value = QtWidgets.QLineEdit(self.qty)
        self.qty_value.setObjectName("SWBalloonQtyValue")
        DL.sets(self.qty_override, True, self.qty_value)     # typing a value turns Override value on
        ql.addWidget(self.qty_override)
        ql.addWidget(self.qty_value)
        self.lay.addWidget(self.qty)
        DL.fold(self.qty)
        PP.layer_group(self)
        self.leader = QtWidgets.QCheckBox("Leader", self.form)
        self.leader.setChecked(True)
        self.leader.hide()
        self.tip = None

    def fill_flags(self):
        cur = self.flag_note.currentText()
        self.flag_note.clear()
        self._flags = _balloon_flags(self.doc)
        for lab, _b, _n in self._flags:
            self.flag_note.addItem(lab)
        if cur:
            self.flag_note.setCurrentText(cur)
        self.flag_note.setVisible(bool(self._flags))
        self.flag_none.setVisible(not self._flags)

    def flag_pick(self):
        """(bank, index) of the flag note picked in Flag Note Bank, else None."""
        if not self.flag_box.isChecked():
            return None
        i = self.flag_note.currentIndex()
        flags = getattr(self, "_flags", [])
        return (flags[i][1], flags[i][2]) if 0 <= i < len(flags) else None

    def sheet_click(self, p):
        if self.tip is None:
            view = DV.view_at(self.page, p)
            if view is None:
                self.say("Click on the part inside a drawing view.")
                return True
            self.tip = (p, view)
            self.say("Click where the balloon goes.")
            return True
        (tip, view), self.tip = self.tip, None
        flag = self.flag_pick()
        if flag is not None:
            from . import drawflagnotes as FN
            b = FN.place_flag(self.page, flag[0], flag[1], p, tip)
            if b is not None:
                self.made.append(b)
                self.doc.recompute()
            self.say(self.AGAIN)
            return True
        qty = None
        if self.qty.isChecked():
            qty = (self.qty_place.checkedButton().text(), self.qty_denote.currentText(),
                   self.qty_value.text().strip() if self.qty_override.isChecked() else "")
        b = make_balloon(self.page, view, tip, p, self.shape.currentText(), None, self.fit.currentText(),
                         self.kind.currentText(), self.custom.text(), self.lower_kind.currentText(),
                         self.lower_custom.text(), self.pad.value(), self.user.value(), qty)
        self.made.append(b)
        from . import drawpmparts as PP
        if PP.layer_of(self) != PP.NONE_LAYER:
            PP.apply_layer(b, PP.layer_of(self))
        self.doc.recompute()
        self.say(self.AGAIN)
        return True


def _balloon_flags(doc):
    """[(label, bank, index)] of every flag note of doc's flag note banks."""
    out = []
    try:
        from . import drawflagnotes as FN
        banks = FN.banks(doc)
        for bank in banks:
            for n, e in enumerate(FN.entries(bank)):
                lab = "%d  %s" % (n + 1, e.get("text", ""))
                out.append(((bank.Label + ": " + lab) if len(banks) > 1 else lab, bank, n))
    except Exception as _fw_err:
        _fw_log("drawannot.py:balloon flags", _fw_err)
    return out


def quantity(view, item):
    """How many of balloon item number item the view's assembly has (the BOM's QTY.)."""
    try:
        from . import drawtables
        for row in drawtables.bom_rows(view)[1:]:
            if str(row[0]) == str(item):
                return str(row[3])
    except Exception as _fw_err:
        _fw_log("drawannot.py:4764", _fw_err)
    return "1"


def _component_object(view, comp):
    """The assembly component comp (an object, or its name in the view's assembly), else None."""
    if comp is None or not isinstance(comp, str):
        return comp
    try:
        from . import asmdrawing as AD
        asm = AD.assembly_of_view(view)
        return asm.Document.getObject(comp) if asm is not None else None
    except Exception as _fw_err:
        _fw_log("drawannot.py:_component_object", _fw_err)
        return None


def bom_part_number(view, item):
    """Part Number (BOM): the PART NUMBER cell of the sheet's Bill of Materials row with this ITEM NO."""
    try:
        from . import drawtables as DT
        page = next((o for o in view.InList if o.TypeId == "TechDraw::DrawPage"), None)
        boms = [o for o in (page.Views if page is not None else []) if getattr(o, "SWTable", "") == "BOM"]
        for t in boms:
            rows = DT.rows_of(t)
            head = [str(c).strip().upper() for c in (rows[0] if rows else [])]
            if "ITEM NO." not in head or "PART NUMBER" not in head:
                continue
            i, j = head.index("ITEM NO."), head.index("PART NUMBER")
            for r in rows[1:]:
                if len(r) > max(i, j) and str(r[i]).strip() == str(item).strip():
                    return str(r[j])
    except Exception as e:
        _fw_log("bom_part_number", e)
    return ""


def _balloon_text(view, item, kind, custom, comp=None):
    if kind == "Quantity":
        return quantity(view, item)
    if kind == "Text":
        return custom
    if kind == "Part Number (BOM)":
        return bom_part_number(view, item)
    if kind == "Custom Properties":
        kind = "Custom Property"
    if kind in ("Custom Property", "File Name"):
        # the model's property (custom: its name) or its file name, as the BOM's PART NUMBER; on an assembly

        src = DV.source_shapes(view)
        doc = src[0].Document if src else None
        base = _component_object(view, comp)
        base = (getattr(base, "LinkedObject", None) or base) if base is not None else None
        if base is not None:
            if base.Document is not doc:
                doc = base.Document
            elif kind == "File Name":
                return base.Label
        if doc is None:
            return ""
        if kind == "File Name":
            import os
            return os.path.splitext(os.path.basename(doc.FileName or ""))[0] or doc.Label
        try:
            meta = dict(doc.Meta)
        except Exception:
            meta = {}
        return str(meta.get(custom, "") or getattr(doc, custom, "") or "")
    return item


def cut_list_number(page, view, p):
    ""

    shapes = DV.source_shapes(view)
    tables = [o for o in page.Document.Objects if getattr(o, "SWTable", "") == "CutList"]
    if not tables:
        return None
    if not any(getattr(o, "SWTableView", "") == view.Name for o in tables):
        # another view of the same weldment (a cut-list-item view): the sheet's cut list numbers it too
        others = [page.Document.getObject(getattr(o, "SWTableView", "") or "") for o in tables]
        docs = {s.Document.Name for v in others if v is not None for s in DV.source_shapes(v)}
        if not shapes or shapes[0].Document.Name not in docs:
            return None
    if not shapes:
        return None
    try:
        from . import wecutlist
        entries = wecutlist.entries(shapes[0].Document)
    except Exception as _fw_err:
        _fw_log("drawannot.py:4848", _fw_err)
        return None
    if not entries:
        return None
    import Part
    keys = []
    for key, _props, _o in entries:
        if key not in keys:
            keys.append(key)
    d, x, y = D.view_frame(view)
    q = DV.to_model(view, p)
    ray = Part.makeLine(q - d * 1e5, q + d * 1e5)
    hits = []
    for n, (key, _props, o) in enumerate(entries):
        try:
            hits.append((o.Shape.distToShape(ray)[0], n, o.Shape))
        except Exception as _fw_err:
            _fw_log("drawannot.py:4865", _fw_err)
            continue
    dn = App.Vector(d)
    if dn.Length > 1e-12:
        dn.normalize()
    j = _front_of(dn, q, ray, hits)        # bodies one behind another: the one in front, as seen
    return str(keys.index(entries[j][0]) + 1) if j is not None else None


def make_balloon(page, view, tip, at, shape="Circular", text=None, fit="2 Characters", kind="Item Number",
                 custom="", lower_kind="Quantity", lower_custom="", pad=1.5, user=10.0, qty=None, component=None,
                 cut_item=None):
    ""


    own = item_of_component(view, component) if component else None
    if own:
        item, comp = own, component
    else:
        item, comp = item_number(view, tip)
    if comp is None:
        cl = cut_item or cut_list_number(page, view, tip)     # cut_item: Auto Balloon's own cut list item
        if cl:
            item = cl
    text = text or _balloon_text(view, item, kind, custom, comp) or item
    lower = _balloon_text(view, item, lower_kind, lower_custom, comp) if shape == "Circular Split Line" else ""
    at, line = magnetic_snap(page, at)
    qtext, place = "", "Right"
    if qty:
        place, denote, value = qty
        qtext = _qty_text(value or quantity(view, item), denote)
    body, reach = balloon_svg(text, at, tip, "" if shape == "None" else shape, fit=fit, lower=lower, pad=pad,
                              user=user, qty=qtext, qty_place=place)
    b = svg_symbol(page, "Balloon", body, reach, at, "Balloon%d" % (1 + len(
        [o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "Balloon"])), "Balloon")
    b.addProperty("App::PropertyString", "SWItem", "FreeCAD", "balloon text (item number)")
    b.SWItem = text
    b.addProperty("App::PropertyString", "SWView", "FreeCAD", "the view it points into")
    b.SWView = view.Name
    b.addProperty("App::PropertyString", "SWBalloonLower", "FreeCAD", "split balloon lower text")
    b.SWBalloonLower = lower
    b.addProperty("App::PropertyString", "SWBalloonShape", "FreeCAD", "balloon style")
    b.SWBalloonShape = shape
    b.addProperty("App::PropertyString", "SWBalloonTip", "FreeCAD", "where its leader ends (sheet mm)")
    b.SWBalloonTip = "%.3f,%.3f,%.3f,%.3f" % (float(tip[0]), float(tip[1]), float(at[0]), float(at[1]))
    b.addProperty("App::PropertyString", "SWBalloonKind", "FreeCAD", "balloon text kind")
    b.SWBalloonKind = kind if text == item else "Text"
    if component:
        b.addProperty("App::PropertyString", "SWBalloonComponent", "FreeCAD", "the component it is attached to")
        b.SWBalloonComponent = component
    if qtext:
        b.addProperty("App::PropertyString", "SWBalloonQuantity", "FreeCAD", "quantity text beside it")
        b.SWBalloonQuantity = qtext
    join_magnetic(line, b)
    return b


def balloon_tip(b):
    """Where the balloon's leader ends now (sheet mm): its tip as made, moved with the balloon."""
    try:
        v = [float(x) for x in (getattr(b, "SWBalloonTip", "") or "").split(",")]
    except ValueError:
        return None
    if len(v) == 2:
        return v[0], v[1]
    if len(v) == 4:
        return v[0] + float(b.X) - v[2], v[1] + float(b.Y) - v[3]
    return None


def item_of_component(view, name):
    """The item number of the assembly component called name in view (as the BOM numbers it), else None."""
    if not name:
        return None
    try:
        from . import asmdrawing as AD
        asm = AD.assembly_of_view(view)
        if asm is not None:
            comp = asm.Document.getObject(name)
            if comp is None:
                return None
            pn = AD.part_number(comp, asm)
            own = getattr(view, "SWBalloonNumbers", "") or ""
            if own and _view_bom(view) is None:        # Auto Balloon's Item Numbers, no BOM yet
                import json
                got = json.loads(own).get(pn)
                if got:
                    return str(got)
            nums = AD.bom_numbers(view)
            if pn in nums:
                return str(nums[pn])
            order = []
            for c in AD.ac.components(asm):
                n = AD.part_number(c, asm)
                if n not in order:
                    order.append(n)
            return str(order.index(pn) + 1) if pn in order else None
    except Exception as _fw_err:
        _fw_log("drawannot.py:4913", _fw_err)
    order = []
    for o in DV.source_shapes(view):
        if getattr(o, "TypeId", "") != "Assembly::AssemblyObject":
            continue
        for c, key, _sh, _box in _components(o):
            if key not in order:
                order.append(key)
            if c.Name == name:
                return str(order.index(key) + 1)
    return None


def _component_gone(view, name):
    """True when view shows assemblies and none of them has the component name any more."""
    asms = [o for o in DV.source_shapes(view) if o.TypeId == "Assembly::AssemblyObject"]
    if not asms:
        return False
    for a in asms:
        c = a.Document.getObject(name)
        if c is not None and c in a.OutList:
            return False
    return True


def refresh_balloons(doc, page=None):
    ""

    changed, gone = [], []
    for b in list(doc.Objects):
        if getattr(b, "SWAnnotation", "") != "Balloon" or getattr(b, "SWBalloonKind", "") != "Item Number":
            continue
        if page is not None and b not in page.Views:
            continue
        view = doc.getObject(getattr(b, "SWView", "") or "")
        tip = balloon_tip(b)
        if view is None or tip is None:
            continue
        cname = getattr(b, "SWBalloonComponent", "") or ""
        if cname and _component_gone(view, cname):
            gone.append(cname)
            continue                        # number (drawmaint paints it); it never takes another part's
        try:
            own = item_of_component(view, cname)
            if own:                         # attached to its component: no pick needed
                item, comp = own, b.SWBalloonComponent
            else:
                item, comp = item_number(view, tip)
        except Exception as _fw_err:
            _fw_log("drawannot.py:5004", _fw_err)
            continue
        old = getattr(b, "SWItem", "")
        if comp is None or not item or item == old:
            continue
        key = ">%s</text>" % _esc(old)
        if key in b.Symbol:
            b.Symbol = b.Symbol.replace(key, ">%s</text>" % _esc(item), 1)
            b.SWItem = item
            changed.append(b)
    if changed:
        doc.recompute()
    return changed


def auto_balloon(page, view, layout="Square", shape="Circular", ignore_multiple=True, magnetic=False,
                 fit="2 Characters", kind="Item Number", attach="Faces", custom="", lower_kind="Quantity",
                 lower_custom="", user=10.0, start=None, step=None, sequential=False):
    """Auto Balloon: one balloon per part (per component of an assembly) of view, laid out round it.
    start / step / sequential (Item Numbers: Start at, Increment, Order sequentially): see number_items.
    attach (Leader attachment): Faces, the leader ends inside the part; Edges, on the part's edge nearest its
    middle."""
    shapes = DV.source_shapes(view)
    comps = []
    for o in shapes:
        if o.TypeId == "Assembly::AssemblyObject":
            comps += [c for c in o.OutList if hasattr(c, "Shape") and c.Shape.Volume > 1e-9]
    in_assembly = bool(comps)
    weld, wkeys = {}, []
    if not comps and len(shapes) > 1:

        try:
            from . import wecutlist
            for key, _props, body in wecutlist.entries(shapes[0].Document):
                weld[body.Name] = repr(key)
                if repr(key) not in wkeys:
                    wkeys.append(repr(key))        # ITEM NO. order, as cut_list_number counts them
        except Exception:
            weld = {}
        if weld:
            comps = [o for o in shapes if o.Name in weld and hasattr(o, "Shape") and o.Shape.Volume > 1e-9]
    if not comps:
        comps = [o for o in shapes[:1] if hasattr(o, "Shape")]   # rcmenus pkg270: an empty assembly: no balloons
        if not comps:
            return []
    d, x, y = D.view_frame(view)
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    a, b, c, e = DV.view_box(view)
    seen, tips, owners, cut_items = set(), [], [], []
    # the view is centred on what it draws: where the source has no shape of its own (an assembly seen as its
    # components) the components' box gives that centre
    centre = None
    if not any(hasattr(o, "Shape") for o in shapes):
        box = None
        for comp in comps:
            try:
                cb = comp.Shape.BoundBox
            except Exception:
                continue
            if box is None:
                box = App.BoundBox(cb)
            else:
                box.add(cb)
        centre = box.Center if box is not None else None

    def _project(view, p):
        if centre is None:
            return _project0(view, p)
        q = view.projectPoint(p) - view.projectPoint(centre)
        return V(q.x, q.y, 0)

    have = [o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "Balloon" and
            getattr(o, "SWView", "") == view.Name]
    have_items = {str(getattr(o, "SWItem", "")) for o in have} - {""}
    for comp in comps:
        if have and not in_assembly and not weld:
            break
        if have_items and in_assembly:
            try:
                if str(item_of_component(view, comp.Name) or "") in have_items:
                    continue
            except Exception as _fw_err:
                _fw_log("drawannot.py:5038", _fw_err)
        lo = getattr(comp, "LinkedObject", None)
        # the part (its document too: two parts' bodies are both "Body"), so only real instances are one item
        key = (getattr(getattr(lo, "Document", None), "Name", ""), getattr(lo, "Name", comp.Name))
        if comp.Name in weld:
            key = weld[comp.Name]
        if ignore_multiple and key in seen:
            continue
        seen.add(key)
        q = _project(view, comp.Shape.BoundBox.Center)
        if attach == "Edges":
            best = None
            for ed in comp.Shape.Edges:
                try:
                    m = _project(view, ed.valueAt((ed.FirstParameter + ed.LastParameter) / 2))
                except Exception as _fw_err:
                    _fw_log("drawannot.py:5099", _fw_err)
                    continue
                dd = math.hypot(m.x - q.x, m.y - q.y)
                if best is None or dd < best[0]:
                    best = (dd, m)
            if best is not None:
                q = best[1]
        tip = (x0 + q.x * k, y0 + q.y * k)
        if in_assembly and attach != "Edges":
            pts = sorted(_tip_points(comp), key=lambda pt: -pt.dot(d))[:4]      # nearest the viewer first (a few: cost)
            tip = _visible_tip(view, comp, tip, [(x0 + m.x * k, y0 + m.y * k) for m in
                                                 (_project(view, pt) for pt in pts)])
        own = None
        if comp.Name in weld:

            # this body that shows (its box centre can sit behind another member, whose number a pick there gives)
            own = str(wkeys.index(weld[comp.Name]) + 1)
            got = cut_list_number(page, view, tip)
            if got is None:
                own = None                  # no Weldment Cut List table: balloons number as without one
            elif got != own:
                for pt in sorted(_tip_points(comp), key=lambda pt: -pt.dot(d))[:12]:
                    m = _project(view, pt)
                    t2 = (x0 + m.x * k, y0 + m.y * k)
                    if cut_list_number(page, view, t2) == own:
                        tip = t2
                        break
        tips.append(tip)
        owners.append(comp.Name if in_assembly else None)
        cut_items.append(own)
    made = []
    n = len(tips)
    places = balloon_places(tips, layout, (a, b, c, e))
    for i, tip in enumerate(tips):
        at = places[i]
        made.append(make_balloon(page, view, tip, at, shape, fit=fit, kind=kind, component=owners[i],
                                 cut_item=cut_items[i], custom=custom, lower_kind=lower_kind,
                                 lower_custom=lower_custom, user=user))
    page.Document.recompute()
    if in_assembly and made and (sequential or start is not None or step is not None):
        # once this call is over: an exploded / configured view's look-up stands in for the view's model meanwhile
        args = (page.Document.Name, page.Name, view.Name, [o.Name for o in made], list(places), layout, start, step,
                sequential)
        QtCore.QTimer.singleShot(0, lambda: _number_later(*args))
    if magnetic and made:
        # Insert magnetic line(s): one through each straight row of balloons
        xs = [p[0] for p in places] or [a, c]
        ys = [p[1] for p in places] or [b, e]
        lx, hx = min(a, min(xs)) - 6, max(c, max(xs)) + 6      # the row as laid out (it can be wider than the view)
        ly, hy = min(b, min(ys)) - 6, max(e, max(ys)) + 6
        sides = {"Top": [((lx, e + 12), (hx, e + 12))], "Bottom": [((lx, b - 12), (hx, b - 12))],
                 "Left": [((a - 12, ly), (a - 12, hy))], "Right": [((c + 12, ly), (c + 12, hy))]}
        if layout == "Square":
            lines = [((a - 12, e + 12), (c + 12, e + 12)), ((a - 12, b - 12), (c + 12, b - 12)),
                     ((a - 12, b - 12), (a - 12, e + 12)), ((c + 12, b - 12), (c + 12, e + 12))]
            lines = [ln for ln in lines if any(_on_line(o, ln) for o in made)]
        else:
            lines = sides.get(layout, [])
        for ln in lines:
            made.append(magnetic_line(page, ln[0], ln[1], equal=False, catch=0.5))
        page.Document.recompute()
    # the item numbers again once any assembly look-up made for this call is over (as the BOM numbers them)
    dname = page.Document.Name
    QtCore.QTimer.singleShot(0, lambda: _refresh_later(dname))
    return made


def _view_bom(view):
    """The BOM table the view's balloons are numbered by (as asmdrawing.bom_numbers picks it), else None."""
    try:
        from . import asmdrawing as AD
        asm = AD.assembly_of_view(view)
        page = AD._page_of(view)
        if asm is None or page is None:
            return None
        mine = []
        for t in AD._bom_tables(page):
            src = view.Document.getObject(getattr(t, "SWBomView", "") or "")
            if src is not None and AD.assembly_of_view(src) is asm:
                mine.append((src is view or view in AD._family(src), t))
        mine.sort(key=lambda it: not it[0])
        return mine[0][1] if mine else None
    except Exception as _fw_err:
        _fw_log("drawannot.py:view bom", _fw_err)
        return None


def _num(text):
    try:
        return float(str(text).split(".")[0])
    except Exception:
        return 1e9


def _number_later(dname, pname, vname, names, places, layout, start, step, sequential):
    try:
        doc = App.getDocument(dname)
    except Exception:
        return
    page, view = doc.getObject(pname), doc.getObject(vname)
    if page is None or view is None:
        return
    kept = [(doc.getObject(n), at) for n, at in zip(names, places) if doc.getObject(n) is not None]
    try:
        number_items(page, view, [b for b, _at in kept], [at for _b, at in kept], layout, start, step, sequential)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Auto Balloon item numbers: %s\n" % error)


def number_items(page, view, balloons, places, layout, start=None, step=None, sequential=False):
    """Auto Balloon's Item Numbers. Start at / Increment: the item numbers start there and go up by that;
    Order sequentially: they run in the order the balloons are laid out (left to right for Top / Bottom, top to
    bottom for Left / Right, clockwise from the top for Square / Circular), else (Do not change item numbers)
    they keep their order. With a BOM those are the BOM's numbers (renumbered, its rows sorted by them, then kept
    as typed); without one the view keeps them (SWBalloonNumbers). Returns {part number: item number}."""
    import json
    from . import asmdrawing as AD
    from . import drawtables as DT
    asm = AD.assembly_of_view(view)
    if asm is None or not balloons:
        return {}
    doc = page.Document
    bom = _view_bom(view)
    if start is None:
        start = int(getattr(bom, "SWBomStart", 1) or 1) if bom is not None else 1
    if step is None:
        step = int(getattr(bom, "SWBomStep", 1) or 1) if bom is not None else 1
    start, step = int(start), max(1, int(step))
    if bom is not None and not sequential:
        bom.SWBomStart, bom.SWBomStep = start, step
        DT.update_table(bom)
        doc.recompute()
        refresh_balloons(doc, page)
        return AD.bom_numbers(view)
    a, b, c, e = DV.view_box(view)
    cx, cy = (a + c) / 2.0, (b + e) / 2.0

    def key(p):
        if layout in ("Top", "Bottom"):
            return p[0]
        if layout in ("Left", "Right"):
            return -p[1]
        return math.atan2(p[0] - cx, p[1] - cy) % (2.0 * math.pi)
    current = AD.bom_numbers(view)
    everyone = sorted(current, key=lambda pn: _num(current[pn])) if current else list(AD._part_order(asm))
    pairs = []
    for bl, at in zip(balloons, places):
        comp = asm.Document.getObject(getattr(bl, "SWBalloonComponent", "") or "")
        if comp is not None:
            pairs.append((key(at), AD.part_number(comp, asm)))
    order = []
    if sequential:
        for _k, pn in sorted(pairs, key=lambda t: t[0]):
            if pn not in order:
                order.append(pn)
    for pn in everyone:
        if pn not in order:
            order.append(pn)
    new = {pn: str(start + i * step) for i, pn in enumerate(order)}
    if bom is None:
        if "SWBalloonNumbers" not in view.PropertiesList:
            view.addProperty("App::PropertyString", "SWBalloonNumbers", "FreeCAD",
                             "Auto Balloon Item Numbers: {part number: item number} without a BOM")
        view.SWBalloonNumbers = json.dumps(new)
    else:
        omap = {str(current[pn]): new[pn] for pn in new if pn in current}
        rs = DT.rows_of(bom)
        cols = DT.columns_of(bom) if getattr(bom, "SWBomColumns", "") else None
        item = DT._col_index(cols, "Item No.") if cols else 0
        if item is not None:
            for r in rs[1:]:
                if item < len(r) and DT.unstrike(r[item]) in omap:
                    r[item] = omap[DT.unstrike(r[item])]
            DT.set_rows(bom, rs)
        ident = {k: omap.get(str(v), v) for k, v in DT.bom_ident(bom).items()}
        if "SWBomIdent" in bom.PropertiesList:
            bom.SWBomIdent = json.dumps(ident)
        bom.SWBomStart, bom.SWBomStep = start, step
        bom.SWBomFixedNumbers = True
        if item is not None:
            from . import drawtableedit as DTE
            DTE.sort_table(bom, [(rs[0][item], True)], keep_numbers=True)
            doc.recompute()
        DT.update_table(bom)
    doc.recompute()
    refresh_balloons(doc, page)
    return new


def _spread_row(want, lo, hi, pitch):
    """Positions on a line for wanted positions want (in order): at least pitch apart, as near their wants as can
    be, kept in order; the row widens past lo..hi (centred) when they do not fit."""
    n = len(want)
    if n == 0:
        return []
    if (hi - lo) < pitch * (n - 1):
        mid = (lo + hi) / 2.0
        lo, hi = mid - pitch * (n - 1) / 2.0, mid + pitch * (n - 1) / 2.0
    out = [min(max(w, lo), hi) for w in want]
    for i in range(1, n):
        out[i] = max(out[i], out[i - 1] + pitch)
    over = out[-1] - hi
    if over > 0:
        out[-1] -= over
        for i in range(n - 2, -1, -1):
            out[i] = min(out[i], out[i + 1] - pitch)
    return out


def balloon_places(tips, layout, box, off=12.0, pitch=10.0):
    ""




    a, b, c, e = box
    n = len(tips)
    at = [None] * n
    if layout in ("Top", "Bottom", "Left", "Right"):
        horiz = layout in ("Top", "Bottom")
        idx = sorted(range(n), key=lambda i: tips[i][0] if horiz else tips[i][1])
        lo, hi = (a, c) if horiz else (b, e)
        even = [lo + (hi - lo) * (j + 1) / (n + 1) for j in range(n)]
        pos = _spread_row(even, lo, hi, pitch)
        fixed = {"Top": e + off, "Bottom": b - off, "Left": a - off, "Right": c + off}[layout]
        for j, i in enumerate(idx):
            at[i] = (pos[j], fixed) if horiz else (fixed, pos[j])
        return _uncross(tips, at)
    cx, cy = (a + c) / 2.0, (b + e) / 2.0
    dirs = []
    for i, tip in enumerate(tips):
        dx, dy = tip[0] - cx, tip[1] - cy
        if math.hypot(dx, dy) < 1e-6:
            ang = 2 * math.pi * i / max(1, n) + math.pi / 4
            dx, dy = math.cos(ang), math.sin(ang)
        dirs.append((dx, dy))
    if layout == "Circular":
        rr = max(c - a, e - b) / 2.0 + off
        angs = [math.atan2(dy, dx) for dx, dy in dirs]
        idx = sorted(range(n), key=lambda i: angs[i])
        if n > 1:               # start the round at its widest gap, so neighbours across +-180 degrees stay neighbours
            gaps = [(angs[idx[(j + 1) % n]] - angs[idx[j]]) % (2 * math.pi) for j in range(n)]
            j0 = (gaps.index(max(gaps)) + 1) % n
            idx = idx[j0:] + idx[:j0]
            base = angs[idx[0]]
            angs = list(angs)
            for i in idx:
                while angs[i] < base - 1e-12:
                    angs[i] += 2 * math.pi
        step = min(pitch / rr, 2 * math.pi / max(1, n))
        want = [angs[i] for i in idx]
        got = _spread_row(want, min(want) if want else 0.0, max(want) if want else 0.0, step)
        for j, i in enumerate(idx):
            at[i] = (cx + rr * math.cos(got[j]), cy + rr * math.sin(got[j]))
        return _uncross(tips, at)
    sx, sy = (c - a) / 2.0 + off, (e - b) / 2.0 + off
    sides = {"T": [], "B": [], "L": [], "R": []}  # noqa: the Square layout
    for i, (dx, dy) in enumerate(dirs):
        t = min(sx / abs(dx) if abs(dx) > 1e-9 else 1e9, sy / abs(dy) if abs(dy) > 1e-9 else 1e9)
        px, py = cx + dx * t, cy + dy * t
        if abs(abs(px - cx) - sx) < 1e-6:
            sides["R" if px > cx else "L"].append((i, py))
        else:
            sides["T" if py > cy else "B"].append((i, px))
        at[i] = (px, py)
    for side, items in sides.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda t: t[1])
        horiz = side in ("T", "B")
        lo, hi = ((cx - sx, cx + sx) if horiz else (cy - sy, cy + sy))
        pos = _spread_row([w for _i, w in items], lo, hi, pitch)
        for (i, _w), p in zip(items, pos):
            at[i] = (p, at[i][1]) if horiz else (at[i][0], p)
    return _uncross(tips, at)


def _crosses(p1, q1, p2, q2):
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) - (B[1] - A[1]) * (C[0] - A[0])
    return (ccw(p1, p2, q2) > 0) != (ccw(q1, p2, q2) > 0) and (ccw(p1, q1, p2) > 0) != (ccw(p1, q1, q2) > 0)


def _uncross(tips, at):
    """Swap the places of two balloons whose leaders cross (each swap shortens the leaders, so it ends)."""
    at = list(at)
    n = len(at)
    for _round in range(n * n):
        hit = False
        for i in range(n):
            for j in range(i + 1, n):
                if _crosses(tips[i], at[i], tips[j], at[j]):
                    at[i], at[j] = at[j], at[i]
                    hit = True
        if not hit:
            break
    return at


def _tip_points(comp, most=48):
    """Model points on a component to end its balloon leader at: its faces' middles, then its edges' middles."""
    pts = []
    try:
        for f in comp.Shape.Faces:
            u0, u1, v0, v1 = f.ParameterRange
            pts.append(f.valueAt((u0 + u1) / 2, (v0 + v1) / 2))
            if len(pts) >= most // 2:
                break
        for ed in comp.Shape.Edges:
            pts.append(ed.valueAt((ed.FirstParameter + ed.LastParameter) / 2))
            if len(pts) >= most:
                break
    except Exception as _fw_err:
        _fw_log("drawannot.py:5128", _fw_err)
    return pts


def _visible_tip(view, comp, tip, others):
    ""


    want = getattr(getattr(comp, "LinkedObject", None), "Name", None) or comp.Name

    def gives(p):
        try:
            _item, c = item_number(view, p)
        except Exception as _fw_err:
            _fw_log("drawannot.py:5205", _fw_err)
            return False
        return c is not None and (c.Name == comp.Name or
                                  (getattr(getattr(c, "LinkedObject", None), "Name", None) or c.Name) == want)
    if gives(tip):
        return tip
    for p in others:
        if gives(p):
            return p
    return tip


def _refresh_later(dname):
    try:
        refresh_balloons(App.getDocument(dname))
    except Exception as _fw_err:
        _fw_log("drawannot.py:5157", _fw_err)


def _on_line(o, ln):
    (ax, ay), (bx, by) = ln
    x, y = float(o.X), float(o.Y)
    L = math.hypot(bx - ax, by - ay)
    return L > 0 and abs((x - ax) * (by - ay) - (y - ay) * (bx - ax)) / L < 0.5


class AutoBalloonPanel(D._Panel):
    TITLE = "Auto Balloon"
    LAYER = True
    PIXMAP = "TechDraw_Balloon"
    LAYOUTS = ("Top", "Bottom", "Left", "Right", "Square", "Circular")

    GROUP_ORDER = ("Item Numbers", "Balloon Layout", "Balloon Settings")

    def build(self):
        self.say("Select drawing sheet/view(s) to insert balloons.")
        box, lay = D._group("Balloon Layout", self.form)
        self.layout = QtWidgets.QComboBox(box)
        self.layout.setObjectName("SWAutoBalloonLayout")
        self.layout.addItems(self.LAYOUTS)
        self.layout.setCurrentText(_doc_row(self.doc, "Balloons", "Auto balloon layout", "Square",
                                            "pm:Auto Balloon:SWAutoBalloonLayout"))
        lay.addWidget(self.layout)

        self.layout.hide()
        row = QtWidgets.QGridLayout()           # three by two: six in one row made the pane wider than 300 px
        self.layout_buttons = QtWidgets.QButtonGroup(box)
        for n, name in enumerate(self.LAYOUTS):
            b = QtWidgets.QToolButton(box)
            b.setObjectName("SWAutoBalloonLayout" + name)
            b.setText(name)
            b.setToolTip({"Square": "Layout Balloons to Square", "Circular": "Layout Balloons to Circular"}.get(
                name, "Layout Balloons to " + name))
            b.setCheckable(True)
            b.setChecked(name == self.layout.currentText())
            self.layout_buttons.addButton(b, n)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            row.addWidget(b, n // 3, n % 3)
        lay.addLayout(row)
        self.layout_buttons.buttonClicked.connect(lambda b: self.layout.setCurrentText(b.text()))
        self.layout.currentTextChanged.connect(lambda t: [b.setChecked(b.text() == t)
                                                          for b in self.layout_buttons.buttons()])
        self.ignore = QtWidgets.QCheckBox("Ignore multiple instances", box)
        self.ignore.setObjectName("SWAutoBalloonIgnore")
        self.ignore.setChecked(True)
        lay.addWidget(self.ignore)
        self.magnetic = QtWidgets.QCheckBox("Insert magnetic line(s)", box)
        self.magnetic.setObjectName("SWAutoBalloonMagnetic")
        self.magnetic.setChecked(True)
        lay.addWidget(self.magnetic)
        self.layout.currentTextChanged.connect(lambda t: DL.row(self.magnetic, t != "Circular"))
        lay.addWidget(QtWidgets.QLabel("Leader attachment:", box))
        self.attach = QtWidgets.QButtonGroup(box)
        for n, k in enumerate(("Faces", "Edges")):
            b = QtWidgets.QRadioButton(k, box)
            b.setObjectName("SWAutoBalloonAttach" + k)
            b.setChecked(k == "Edges")
            self.attach.addButton(b, n)
            lay.addWidget(b)
        self.lay.addWidget(box)
        box, lay = D._group("Balloon Settings", self.form)
        self.shape = QtWidgets.QComboBox(box)
        self.shape.setObjectName("SWBalloonStyle")
        self.shape.addItems(BalloonPanel.SHAPES)
        self.shape.setCurrentText("Circular")
        lay.addWidget(self.shape)
        self.size = QtWidgets.QComboBox(box)
        self.size.setObjectName("SWBalloonSize")
        self.size.addItems(BALLOON_SIZES)
        self.size.setCurrentText("2 Characters")
        lay.addWidget(self.size)
        self.user = QtWidgets.QDoubleSpinBox(box)
        self.user.setObjectName("SWBalloonUser")
        self.user.setRange(1, 200)
        self.user.setValue(10.0)
        self.user.setPrefix("User defined: ")
        self.user.setSuffix("mm")
        lay.addWidget(self.user)
        lay.addWidget(QtWidgets.QLabel("Balloon text:", box))
        self.text = QtWidgets.QComboBox(box)
        self.text.setObjectName("SWBalloonText")
        self.text.addItems(["Item Number", "Quantity", "Custom Properties", "Part Number (BOM)", "File Name"])
        lay.addWidget(self.text)
        self.custom = QtWidgets.QLineEdit(box)
        self.custom.setObjectName("SWBalloonCustom")
        self.custom.setPlaceholderText("property name, e.g. Description")
        lay.addWidget(self.custom)
        self.lower_label = QtWidgets.QLabel("Lower text:", box)
        lay.addWidget(self.lower_label)
        self.lower_kind = QtWidgets.QComboBox(box)
        self.lower_kind.setObjectName("SWBalloonLowerText")
        self.lower_kind.addItems(["Quantity", "Item Number", "Custom Properties", "Part Number (BOM)", "File Name"])
        lay.addWidget(self.lower_kind)
        self.lower_custom = QtWidgets.QLineEdit(box)
        self.lower_custom.setObjectName("SWBalloonLowerCustom")
        self.lower_custom.setPlaceholderText("property name")
        lay.addWidget(self.lower_custom)
        self.lay.addWidget(box)

        box, lay = D._group("Item Numbers", self.form)
        grid = QtWidgets.QGridLayout()
        grid.addWidget(QtWidgets.QLabel("Start at:", box), 0, 0)
        self.start = QtWidgets.QSpinBox(box)
        self.start.setObjectName("SWAutoBalloonStart")
        self.start.setRange(0, 9999)
        self.start.setValue(1)
        grid.addWidget(self.start, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Increment:", box), 1, 0)
        self.step = QtWidgets.QSpinBox(box)
        self.step.setObjectName("SWAutoBalloonIncrement")
        self.step.setRange(1, 999)
        self.step.setValue(1)
        grid.addWidget(self.step, 1, 1)
        lay.addLayout(grid)
        self.numbers = QtWidgets.QButtonGroup(box)
        self.keep_numbers = QtWidgets.QRadioButton("Do not change item numbers", box)
        self.keep_numbers.setObjectName("SWAutoBalloonKeepNumbers")
        self.sequential = QtWidgets.QRadioButton("Order sequentially", box)
        self.sequential.setObjectName("SWAutoBalloonSequential")
        self.sequential.setToolTip("Renumber the items so the balloons read 1, 2, 3... round the view")
        for n, w in enumerate((self.keep_numbers, self.sequential)):
            self.numbers.addButton(w, n)
            lay.addWidget(w)
        self.keep_numbers.setChecked(True)
        self.numbers_set = False                # Start at / Increment only change the numbers once touched
        for w in (self.start, self.step):
            w.valueChanged.connect(lambda *_: setattr(self, "numbers_set", True))
        self.lay.addWidget(box)
        for w in (self.shape, self.size, self.text, self.lower_kind):
            w.currentTextChanged.connect(lambda *_: self.reshow())
        self.reshow()
        self.done = set()
        pre = D.preselected_view(self.page)
        if pre is not None:
            QtCore.QTimer.singleShot(0, lambda v=pre: self.balloon(v))

    def reshow(self):
        ""

        split = self.shape.currentText() == "Circular Split Line"
        self.user.setVisible(self.size.currentText() == "User Defined")
        self.custom.setVisible(self.text.currentText() in ("Custom Property", "Custom Properties"))
        for w in (self.lower_label, self.lower_kind):
            w.setVisible(split)
        self.lower_custom.setVisible(split and self.lower_kind.currentText() in ("Custom Property", "Custom Properties"))

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if view is None or view.Name in self.done:
            return True
        self.balloon(view)
        return True

    def balloon(self, view):
        if view.Name in self.done:
            return
        self.done.add(view.Name)
        self.made += auto_balloon(self.page, view, self.layout.currentText(), self.shape.currentText(),
                                  self.ignore.isChecked(),
                                  self.magnetic.isEnabled() and self.magnetic.isChecked(),
                                  self.size.currentText(), self.text.currentText(),
                                  attach=self.attach.checkedButton().text(), custom=self.custom.text().strip(),
                                  lower_kind=self.lower_kind.currentText(),
                                  lower_custom=self.lower_custom.text().strip(), user=self.user.value(),
                                  start=self.start.value() if self.numbers_set else None,
                                  step=self.step.value() if self.numbers_set else None,
                                  sequential=self.sequential.isChecked())
        self.say("Ballooned %s. Click another view, or OK." % view.Label)
        return True


def finish_standard(doc):
    """The surface finish standard a new symbol starts on: Document Properties > Surface Finishes
    "Display symbols per ISO 21920-1" when that row is there and on, else ISO 1302."""
    try:
        if _doc_row(doc, "Surface Finishes", "Display symbols per ISO 21920-1", False):
            return "ISO 21920-1"
    except Exception as _fw_err:
        _fw_log("drawannot.py:5247", _fw_err)
    return "ISO 1302"


def _tipped(w, tip):
    w.setToolTip(tip)
    return w


def _narrow_edits(form):
    """The PM's text boxes and its wrapped message take the pane's width instead of setting it: at their own
    width (131 px each, beside their labels) the Surface Finish and Geometric Tolerance panes passed 300 px."""
    for e in form.findChildren(QtWidgets.QLineEdit):
        if isinstance(e.parent(), QtWidgets.QAbstractSpinBox) or isinstance(e.parent(), QtWidgets.QComboBox):
            continue
        e.setMinimumWidth(48)
        e.setSizePolicy(QtWidgets.QSizePolicy.Ignored, e.sizePolicy().verticalPolicy())
    for cb in form.findChildren(QtWidgets.QComboBox):
        if cb.sizeAdjustPolicy() == QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon:
            continue                    # already sized (the Geometric Tolerance lists)
        cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(4)
        try:
            cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 24)     # the open list shows whole names
        except Exception as _fw_err:
            _fw_log("drawannot.py:narrow lists", _fw_err)
    m = form.findChild(QtWidgets.QLabel, "SWDrawMessage")
    if m is not None:
        m.setSizePolicy(QtWidgets.QSizePolicy.Ignored, m.sizePolicy().verticalPolicy())
        m.setMinimumWidth(120)


class _ButtonChoice(QtWidgets.QWidget):
    ""

    currentTextChanged = QtCore.Signal(str)

    def __init__(self, parent, prefix, names, current, tips=None):
        super().__init__(parent)
        # a grid, two a row when the names are long: one row of long names made the pane wider than 300 px
        cols = len(names) if sum(len(n) for n in names) <= 24 else 2 if max(len(n) for n in names) <= 14 else 1
        row = QtWidgets.QGridLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(2)
        row.setVerticalSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for n, name in enumerate(names):
            b = QtWidgets.QToolButton(self)
            b.setText(name)
            b.setToolTip((tips or {}).get(name, name))
            b.setCheckable(True)
            b.setObjectName(prefix + re.sub(r"[^A-Za-z0-9]", "", name))
            b.setChecked(name == current)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.setMinimumWidth(0)
            self.group.addButton(b, n)
            self.buttons[name] = b
            row.addWidget(b, n // cols, n % cols)
        self.group.buttonClicked.connect(lambda b: self.currentTextChanged.emit(b.text()))

    def currentText(self):
        b = self.group.checkedButton()
        return b.text() if b is not None else ""

    def setCurrentText(self, name):
        b = self.buttons.get(name)
        if b is not None and not b.isChecked():
            b.setChecked(True)
            self.currentTextChanged.emit(name)


class SurfaceFinishPanel(_AnnotPanel):
    TITLE = "Surface Finish"
    PIXMAP = "TechDraw_SurfaceFinishSymbols"
    AGAIN = "Symbol placed. Click to place another, or OK."

    def build(self):
        from . import drawpmparts as PP
        self.say("Pick the symbol and roughness, then click where it points and where it goes.")
        PP.style_group(self)
        box, lay = D._group("Symbol", self.form)

        self.kind = _ButtonChoice(box, "SWFinish", ROUGH_SYMBOLS, "Basic")
        self.kind.setObjectName("SWFinishSymbol")
        lay.addWidget(self.kind)
        self.where = _ButtonChoice(box, "SWFinish", ("Local", "All Around"), "Local")
        self.where.setObjectName("SWFinishWhere")
        lay.addWidget(self.where)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Standard:", box))
        self.standard = QtWidgets.QComboBox(box)
        self.standard.setObjectName("SWFinishStandard")
        self.standard.addItems(FINISH_STANDARDS)
        self.standard.setCurrentText(finish_standard(self.doc))
        row.addWidget(self.standard)
        lay.addLayout(row)
        self.lay.addWidget(box)
        box, lay = D._group("Symbol Layout", self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Maximum roughness:", box))
        self.value = QtWidgets.QLineEdit("3.2", box)
        self.value.setObjectName("SWFinishRoughness")
        row.addWidget(self.value)
        lay.addLayout(row)
        grid = QtWidgets.QGridLayout()
        self.fields = {}
        for n, (key, lab) in enumerate((("minimum", "Minimum roughness:"), ("method", "Production method:"),
                                        ("allowance", "Machining allowance:"), ("sampling", "Sampling length:"),
                                        ("other", "Other roughness value:"), ("spacing", "Roughness spacing:"))):
            e = QtWidgets.QLineEdit("", box)
            e.setObjectName("SWFinish" + key.capitalize())
            grid.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(e, n, 1)
            self.fields[key] = e
        self.lay_dir = QtWidgets.QComboBox(box)
        self.lay_dir.setObjectName("SWFinishLay")
        self.lay_dir.addItems([n for n, _ in LAYS])
        grid.addWidget(QtWidgets.QLabel("Lay direction:", box), 6, 0)
        grid.addWidget(self.lay_dir, 6, 1)
        lay.addLayout(grid)
        self.iso_box = QtWidgets.QWidget(box)
        self.iso_box.setObjectName("SWFinishIso21920")
        ig = QtWidgets.QGridLayout(self.iso_box)
        ig.setContentsMargins(0, 0, 0, 0)
        self.iso = {}
        for n, (key, lab, items) in enumerate((
                ("tolerance", "Tolerance type:", [t for t, _ in ISO21920_TOLERANCE]),
                ("parameter", "Parameter:", ISO21920_PARAMS), ("ls", "Short filter (Ls):", None),
                ("lc", "Long filter (Lc):", None), ("ln", "Evaluation length:", None),
                ("rule", "Comparison rule:", ISO21920_RULES))):
            if items is None:
                w = QtWidgets.QLineEdit("", self.iso_box)
            else:
                w = QtWidgets.QComboBox(self.iso_box)
                w.addItems(list(items))
            w.setObjectName("SWFinish21920" + key.capitalize())
            ig.addWidget(QtWidgets.QLabel(lab, self.iso_box), n, 0)
            ig.addWidget(w, n, 1)
            self.iso[key] = w
        lay.addWidget(self.iso_box)
        self.standard.currentTextChanged.connect(self._standard_changed)
        self._standard_changed(self.standard.currentText())
        self.lay.addWidget(box)
        box, lay = D._group("Angle", self.form)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWFinishAngle")
        self.angle.setRange(-360, 360)
        self.angle.setSuffix("\u00b0")
        lay.addWidget(self.angle)
        row = QtWidgets.QGridLayout()           # two a row: one row of four made the pane 450 px wide
        row.setHorizontalSpacing(2)
        row.setVerticalSpacing(2)
        self.turn = QtWidgets.QButtonGroup(box)
        for n, (name, a, short) in enumerate((("Upright", 0.0, "Upright"), ("Rotated 90", 90.0, "Rotated 90"),
                                              ("Perpendicular", None, "Perpendicular"),
                                              ("Perpendicular (Reverse)", None, "Perp. (Reverse)"))):
            b = QtWidgets.QToolButton(box)
            b.setText(short)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setObjectName("SWFinish" + re.sub(r"[^A-Za-z0-9]", "", name))
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            if a is not None:
                b.clicked.connect(lambda *_, a=a: self.angle.setValue(a))
            self.turn.addButton(b, n)
            row.addWidget(b, n // 2, n % 2)
            b.setChecked(n == 0)
        lay.addLayout(row)
        self.lay.addWidget(box)
        self.symbol_leaders("SWFinish")
        _narrow_edits(self.form)
        PP.format_group(self, title="Format")
        PP.layer_group(self)

    def sheet_click(self, p):
        b = self.leader_kind.checkedButton()
        if b is not None and b.text() == "Auto Leader" and self.tip is None and DV.view_at(self.page, p) is None:
            obj = self.place(p, None)            # Auto Leader: no leader when placed on the empty sheet
            if obj is not None:
                self.made.append(obj)
                self.doc.recompute()
            self.say(self.AGAIN)
            return True
        return _AnnotPanel.sheet_click(self, p)

    def all_around(self):
        return self.where.currentText() == "All Around"

    def _standard_changed(self, text):
        """ISO 21920-1: tolerance type, parameter, filters, evaluation length and comparison rule; the
        sampling length and roughness spacing of ISO 1302 go (21920 writes them in the requirement)."""
        on = text == "ISO 21920-1"
        self.iso_box.setVisible(on)
        for key in ("sampling", "other", "spacing"):
            e = self.fields.get(key)
            if e is not None:
                DL.row(e, not on)
        self.say("Pick the symbol and the ISO 21920-1 requirement, then click where it points and where it goes."
                 if on else "Pick the symbol and roughness, then click where it points and where it goes.")

    def iso_values(self):
        if self.standard.currentText() != "ISO 21920-1":
            return None
        return {k: (w.currentText() if isinstance(w, QtWidgets.QComboBox) else w.text()) for k, w in self.iso.items()}

    def edge_angle(self, tip):
        """Perpendicular: the symbol stood on the model edge at the leader point."""
        view = DV.view_at(self.page, tip)
        if view is None:
            return None
        k = DV.view_scale(view)
        hit = edge_at(view, DV.to_geometry(view, tip), 2.0 / k)
        if hit is None:
            return None
        e = hit[1]
        try:
            prm = e.Curve.parameter(V(*DV.to_geometry(view, tip), 0))
            t = e.tangentAt(prm)
        except Exception:
            t = e.Vertexes[-1].Point - e.Vertexes[0].Point
        a = math.degrees(math.atan2(-t.y, t.x))
        while a > 90:
            a -= 180
        while a <= -90:
            a += 180
        return a

    def place(self, p, tip):
        f = {k: e.text() for k, e in self.fields.items()}
        turn = self.turn.checkedButton().toolTip() if self.turn.checkedButton() else "Upright"
        if turn.startswith("Perpendicular") and tip is not None:
            a = self.edge_angle(tip)
            if a is not None:
                self.angle.setValue(a + (180.0 if "Reverse" in turn else 0.0))
        body, reach = finish_svg(self.kind.currentText(), self.value.text(), p, tip, lay=self.lay_dir.currentText(),
                                 around=self.all_around(), angle=self.angle.value(),
                                 arrow=self.arrow.currentText(), leader=self.leader_kind_text(),
                                 iso21920=self.iso_values(), jogs=getattr(self, "_jogs", None) or (), **f)
        s = svg_symbol(self.page, "SurfaceFinish", body, reach, p, "Surface Finish%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "SurfaceFinish"])), "SurfaceFinish")
        s.addProperty("App::PropertyString", "SWFinish", "FreeCAD", "symbol and roughness")
        s.SWFinish = "%s %s" % (self.kind.currentText(), self.value.text())
        s.addProperty("App::PropertyStringList", "SWFinishFields", "FreeCAD", "minimum, method, allowance, "
                      "sampling, lay, all around, angle")
        s.SWFinishFields = [f["minimum"], f["method"], f["allowance"], f["sampling"], self.lay_dir.currentText(),
                            str(self.all_around()), "%g" % self.angle.value(), f["other"], f["spacing"]]
        iso = self.iso_values()
        if iso is not None:
            s.addProperty("App::PropertyMap", "SWFinish21920", "FreeCAD", "ISO 21920-1 requirement")
            s.SWFinish21920 = iso
        return s


class GeometricTolerancePanel(_AnnotPanel):
    TITLE = "Geometric Tolerance"
    PIXMAP = "TechDraw_Annotation"
    AGAIN = "Tolerance placed. Click to place another, or OK."

    def build(self):
        from . import drawpmparts as PP
        self.say("Build the feature control frame, then click where it points and where it goes.")
        PP.style_group(self)
        box, lay = D._group("Properties", self.form)
        grid = QtWidgets.QGridLayout()
        self.symbol = QtWidgets.QComboBox(box)
        self.symbol.setObjectName("SWGtolSymbol")
        self.symbol.addItems([n for n, _ in GTOL])
        self.symbol.setCurrentText("Position")
        self.dia = QtWidgets.QCheckBox("Diameter", box)
        self.dia.setObjectName("SWGtolDiameter")
        self.tol = QtWidgets.QLineEdit("0.1", box)
        self.tol.setObjectName("SWGtolTolerance1")
        self.mat = QtWidgets.QComboBox(box)
        self.mat.setObjectName("SWGtolMaterial")
        self.mat.addItems([n for n, _ in MATERIAL])
        self.datums = []
        grid.addWidget(QtWidgets.QLabel("Symbol:", box), 0, 0)
        grid.addWidget(self.symbol, 0, 1)
        grid.addWidget(self.dia, 1, 0)
        grid.addWidget(self.tol, 1, 1)
        grid.addWidget(_tipped(QtWidgets.QLabel("Condition:", box), "Material condition"), 2, 0)
        grid.addWidget(self.mat, 2, 1)
        self.datum_mats = []
        for n, name in enumerate(("Primary", "Secondary", "Tertiary")):
            e = QtWidgets.QLineEdit(box)
            e.setObjectName("SWGtol" + name)
            grid.addWidget(QtWidgets.QLabel(name + ":", box), 3 + n, 0)
            cell = QtWidgets.QHBoxLayout()      # the datum and its material condition share a cell (pane <= 300 px)
            cell.setSpacing(2)
            cell.addWidget(e, 3)
            grid.addLayout(cell, 3 + n, 1)
            self.datums.append(e)
            m = QtWidgets.QComboBox(box)
            m.setObjectName("SWGtol%sMaterial" % name)
            m.addItems([k for k, _ in MATERIAL])
            m.setToolTip("%s datum material condition" % name)
            cell.addWidget(m, 2)
            self.datum_mats.append(m)
        self.dia2 = QtWidgets.QCheckBox("Diameter 2", box)
        self.dia2.setObjectName("SWGtolDiameter2")
        self.tol2 = QtWidgets.QLineEdit("", box)
        self.tol2.setObjectName("SWGtolTolerance2")
        self.mat2 = QtWidgets.QComboBox(box)
        self.mat2.setObjectName("SWGtolMaterial2")
        self.mat2.addItems([n for n, _ in MATERIAL])
        grid.addWidget(self.dia2, 6, 0)
        grid.addWidget(self.tol2, 6, 1)
        grid.addWidget(_tipped(QtWidgets.QLabel("Condition 2:", box), "Material condition 2"), 7, 0)
        grid.addWidget(self.mat2, 7, 1)
        lay.addLayout(grid)
        # the lists size to a short text (their open list shows the whole names): sized to their longest entry
        # they made the pane 550 px wide at 1366 x 768
        for cb in [self.symbol, self.mat, self.mat2] + self.datum_mats:
            cb.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(4)
            cb.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            try:
                cb.view().setMinimumWidth(cb.view().sizeHintForColumn(0) + 24)
            except Exception as _fw_err:
                _fw_log("drawannot.py:gtol lists", _fw_err)
        self.lay.addWidget(box)
        box, lay = D._group("Modifiers", self.form)
        row = QtWidgets.QHBoxLayout()
        self.projected = QtWidgets.QCheckBox("Projected tolerance zone", box)
        self.projected.setObjectName("SWGtolProjected")
        self.projected_h = QtWidgets.QLineEdit("", box)
        self.projected_h.setObjectName("SWGtolProjectedHeight")
        row.addWidget(self.projected)
        row.addWidget(self.projected_h)
        lay.addLayout(row)
        self.free = QtWidgets.QCheckBox("Free state", box)
        self.free.setObjectName("SWGtolFreeState")
        self.tangent = QtWidgets.QCheckBox("Tangent plane", box)
        self.tangent.setObjectName("SWGtolTangentPlane")
        lay.addWidget(self.free)
        lay.addWidget(self.tangent)
        self.lay.addWidget(box)
        box, lay = D._group("Composite Frame", self.form)
        self.composite = QtWidgets.QCheckBox("Composite frame", box)
        self.composite.setObjectName("SWGtolComposite")
        grid = QtWidgets.QGridLayout()
        self.ctol = QtWidgets.QLineEdit("", box)
        self.ctol.setObjectName("SWGtolCompositeTolerance")
        self.cdatum = QtWidgets.QLineEdit("", box)
        self.cdatum.setObjectName("SWGtolCompositePrimary")
        grid.addWidget(QtWidgets.QLabel("Tolerance:", box), 0, 0)
        grid.addWidget(self.ctol, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Primary:", box), 1, 0)
        grid.addWidget(self.cdatum, 1, 1)
        lay.addWidget(self.composite)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Text", self.form)
        grid = QtWidgets.QGridLayout()
        self.above = QtWidgets.QLineEdit("", box)
        self.above.setObjectName("SWGtolAbove")
        self.below = QtWidgets.QLineEdit("", box)
        self.below.setObjectName("SWGtolBelow")
        grid.addWidget(QtWidgets.QLabel("Above frame:", box), 0, 0)
        grid.addWidget(self.above, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Below frame:", box), 1, 0)
        grid.addWidget(self.below, 1, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Angle", self.form)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWGtolAngle")
        self.angle.setRange(-360, 360)
        self.angle.setSuffix("\u00b0")
        lay.addWidget(self.angle)
        row = QtWidgets.QHBoxLayout()
        self.set_dir = QtWidgets.QButtonGroup(box)
        for n, (name, a) in enumerate((("Set Horizontal", 0.0), ("Set Vertical", 90.0))):
            b = QtWidgets.QToolButton(box)
            b.setText(name)
            b.setToolTip(name)
            b.setCheckable(True)
            b.setObjectName("SWGtol" + name.replace(" ", ""))
            b.setChecked(n == 0)
            b.clicked.connect(lambda *_, a=a: self.angle.setValue(a))
            self.set_dir.addButton(b, n)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.angle.valueChanged.connect(self._dir_shown)
        self.lay.addWidget(box)
        self.symbol_leaders("SWGtol", ("Straight", "Bent", "Perpendicular"))
        _narrow_edits(self.form)
        self.leader_kind.button(3).setChecked(True)
        self._kind_picked()
        self._shapes_shown()
        self.leader_look = self._line_look("Leader Style", "SWGtolLeader")
        self.frame_look = self._line_look("Frame Style", "SWGtolFrame")
        ab = self.angle.parentWidget()
        self.lay.removeWidget(ab)
        self.lay.addWidget(ab)
        PP.format_group(self, title="Format")
        PP.layer_group(self)

    def sheet_click(self, p):
        b = self.leader_kind.checkedButton()
        if b is not None and b.text() == "Auto Leader" and self.tip is None and DV.view_at(self.page, p) is None:
            obj = self.place(p, None)            # Auto Leader: no leader when placed on the empty sheet
            if obj is not None:
                self.made.append(obj)
                self.doc.recompute()
            self.say(self.AGAIN)
            return True
        return _AnnotPanel.sheet_click(self, p)

    def _dir_shown(self, a):
        for n, want in ((0, 0.0), (1, 90.0)):
            b = self.set_dir.button(n)
            b.setChecked(abs(((a - want + 180.0) % 360.0) - 180.0) < 1e-6)
        if not any(b.isChecked() for b in self.set_dir.buttons()):
            self.set_dir.setExclusive(False)
            for b in self.set_dir.buttons():
                b.setChecked(False)
            self.set_dir.setExclusive(True)

    LINES = ("Solid", "Dashed", "Phantom", "Chain", "Center", "Stitch", "Chain thick")
    THICK = ("0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm", "1.4mm", "2mm", "Custom Size")

    def _line_look(self, title, prefix):
        ""

        from . import drawpmparts as PP
        box, lay = D._group(title, self.form)
        use = QtWidgets.QCheckBox("Use document display", box)
        use.setObjectName(prefix + "Doc")
        use.setChecked(True)
        line = QtWidgets.QComboBox(box)
        line.setObjectName(prefix + "Line")
        line.addItems(list(PP.LINE_STYLES) + [n for n in self.LINES if n not in PP.LINE_STYLES])
        thick = QtWidgets.QComboBox(box)
        thick.setObjectName(prefix + "Thickness")
        thick.addItems(self.THICK)
        custom = QtWidgets.QDoubleSpinBox(box)           # Custom Size: the thickness typed
        custom.setObjectName(prefix + "CustomThickness")
        custom.setRange(0.01, 10.0)
        custom.setDecimals(2)
        custom.setValue(0.18)
        custom.setSuffix(" mm")
        custom.setVisible(False)
        thick.currentTextChanged.connect(lambda t: custom.setVisible(t == "Custom Size"))
        DL.sets(use, False, line, thick, custom)
        for w in (use, line, thick, custom):
            lay.addWidget(w)
        self.lay.addWidget(box)
        return use, line, thick, custom

    @staticmethod
    def _look(group):
        """(dash pattern, thickness mm) of a Leader Style / Frame Style group; ("", 0) on the document display."""
        from . import drawpmparts as PP
        use, line, thick, custom = group
        if use.isChecked():
            return "", 0.0
        th = thick.currentText()
        dash = PP.DASHES.get(line.currentText(), PP.DASHES.get("Chain", "") if line.currentText() == "Chain thick" else "")
        if th == "Custom Size":
            return dash, float(custom.value())
        return dash, (float(th[:-2]) if th.endswith("mm") else 0.0)

    def second_row(self):
        if not self.composite.isChecked():
            return None
        sym = dict(GTOL).get(self.symbol.currentText(), self.symbol.currentText())
        cells = [sym, ("\u2300" if self.dia.isChecked() else "") + self.ctol.text()]
        if self.cdatum.text().strip():
            cells.append(self.cdatum.text().strip())
        return cells

    def cells(self):
        return gtol_cells(self.symbol.currentText(), self.dia.isChecked(), self.tol.text(), self.mat.currentText(),
                          [e.text().strip() + (dict(MATERIAL).get(m.currentText(), "") if e.text().strip() else "")
                           for e, m in zip(self.datums, self.datum_mats)], self.tol2.text().strip(), self.dia2.isChecked(),
                          self.mat2.currentText(), self.projected_h.text().strip() if self.projected.isChecked()
                          else None, self.free.isChecked(), self.tangent.isChecked())

    def place(self, p, tip):
        cells = self.cells()
        second = self.second_row()
        ld, lw = self._look(self.leader_look)
        fd, fw = self._look(self.frame_look)
        jogs = getattr(self, "_jogs", None) or ()
        if not jogs:
            j = self.perpendicular_jog(tip, p)
            jogs = (j,) if j is not None else ()
        body, reach = gtol_svg(cells, p, tip, second, angle=self.angle.value(), leader=self.leader_kind_text(),
                               arrow=self.arrow.currentText(), jogs=jogs,
                               leader_dash=ld, leader_width=lw, frame_dash=fd, frame_width=fw)
        half = TEXT_SIZE * (2 if second else 1)            # half the frame's height
        for text, y in ((self.above.text(), -half - 1.0), (self.below.text(), half + TEXT_SIZE + 0.5)):
            if text:
                body += ('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g">%s</text>'
                         % (-sum(max(TEXT_SIZE * 2, _text_width(c, TEXT_SIZE) + 2.5) for c in cells) / 2, y,
                            TEXT_SIZE, _esc(text)))
                reach = max(reach, half + TEXT_SIZE * 2)
        s = svg_symbol(self.page, "GeometricTolerance", body, reach, p, "Geometric Tolerance%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "GeometricTolerance"])),
            "GeometricTolerance")
        s.addProperty("App::PropertyStringList", "SWCells", "FreeCAD", "feature control frame cells")
        s.SWCells = cells
        s.addProperty("App::PropertyStringList", "SWCells2", "FreeCAD", "composite frame lower row")
        s.SWCells2 = second or []
        s.addProperty("App::PropertyStringList", "SWGtolText", "FreeCAD", "text above and below the frame")
        s.SWGtolText = [self.above.text(), self.below.text()]
        return s


class DatumFeaturePanel(D._Panel):
    TITLE = "Datum Feature"
    LAYER = True
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        from . import drawpmparts as PP
        self.say("Click the edge the datum goes on, then where its label goes.")
        PP.style_group(self)
        box, lay = D._group("Label Settings", self.form)
        self.label = QtWidgets.QLineEdit(peek_datum(self.page), box)
        self.label.setObjectName("SWDatumLabel")
        lay.addWidget(self.label)
        self.doc_style = QtWidgets.QCheckBox("Use document style", box)
        self.doc_style.setObjectName("SWDatumDocStyle")
        self.doc_style.setChecked(True)
        lay.addWidget(self.doc_style)

        self.frame = _ButtonChoice(box, "SWDatumFrame", DATUM_FRAMES, DATUM_FRAMES[0],
                                   {"Square": "Square", "Round": "Round (GB)"})
        self.frame.setObjectName("SWDatumFrame")
        self.leader_style = _ButtonChoice(box, "SWDatumEnd", DATUM_LEADERS, DATUM_LEADERS[0],
                                          {n: n.title() for n in DATUM_LEADERS})
        self.leader_style.setObjectName("SWDatumLeaderStyle")
        lay.addWidget(self.frame)
        lay.addWidget(self.leader_style)
        try:
            f0, l0 = doc_datum_style(self.doc)          # start on the document's style, as it draws
            self.frame.setCurrentText(f0)
            self.leader_style.setCurrentText(l0)
        except Exception as e:
            _fw_log("datum style", e)
        self.leader_style.currentTextChanged.connect(lambda *_: self.doc_style.setChecked(False))
        self.doc_style.toggled.connect(lambda on: self.frame.setVisible(not on))
        self.frame.setVisible(not self.doc_style.isChecked())
        self.lay.addWidget(box)
        box, lay = D._group("Text", self.form)
        self.text = QtWidgets.QPlainTextEdit(box)
        self.text.setObjectName("SWDatumText")
        self.text.setMaximumHeight(50)
        lay.addWidget(self.text)
        self.lay.addWidget(box)
        PP.format_group(self, title="Format")
        self.tip = None

    def sheet_click(self, p):
        if self.tip is None:
            self.tip = p
            self.say("Click where the datum label goes.")
            return True
        tip, self.tip = self.tip, None
        letter = self.label.text().strip()
        letter = next_datum(self.page) if not letter or letter == peek_datum(self.page) else letter
        if self.doc_style.isChecked():
            frame, leader = doc_datum_style(self.doc)         # Document Properties > Annotations > Datums
        else:
            frame, leader = self.frame.currentText(), self.leader_style.currentText()
        body, reach = datum_svg(letter, p, tip, frame, leader, self.text.toPlainText())
        s = svg_symbol(self.page, "DatumFeature", body, reach, p, "Datum Feature%s" % letter, "DatumFeature")
        if self.text.toPlainText():
            s.addProperty("App::PropertyString", "SWDatumText", "FreeCAD", "text under the datum frame")
            s.SWDatumText = self.text.toPlainText()
        s.addProperty("App::PropertyString", "SWDatumStyle", "FreeCAD", "datum frame and leader style")
        s.SWDatumStyle = "%s|%s" % (frame, leader)
        s.addProperty("App::PropertyString", "SWDatum", "FreeCAD", "datum letter")
        s.SWDatum = letter
        s.addProperty("App::PropertyVector", "SWTip", "FreeCAD", "leader point")
        s.SWTip = V(tip[0], tip[1], 0)
        s.addProperty("App::PropertyBool", "SWDatumDoc", "FreeCAD", "on the document's datum style")
        s.SWDatumDoc = bool(self.doc_style.isChecked())
        self.made.append(s)
        self.doc.recompute()
        self.label.setText(peek_datum(self.page))
        self.say("Datum %s placed. Click for the next one, or OK." % letter)
        return True


# --------------------------------------------------------------------------- more annotations
class DatumTargetPanel(_AnnotPanel):
    TITLE = "Datum Target"
    LAYER = True
    PIXMAP = "TechDraw_Annotation"
    AGAIN = "Datum target placed. Click for the next one, or OK."

    def build(self):
        self.say("Click the target point on the part, then where the symbol goes.")
        box, lay = D._group("Settings", self.form)
        grid = QtWidgets.QGridLayout()
        self.area = QtWidgets.QComboBox(box)
        self.area.setObjectName("SWDatumTargetArea")
        self.area.addItems(["Point", "Circle", "Rectangle", "None"])
        self.size = QtWidgets.QLineEdit("", box)
        self.size.setObjectName("SWDatumTargetSize")
        self.height = QtWidgets.QLineEdit("", box)
        self.height.setObjectName("SWDatumTargetHeight")
        self.ref = QtWidgets.QLineEdit("A1", box)
        self.ref.setObjectName("SWDatumTargetRef")
        self.refs = [self.ref]
        refrow = QtWidgets.QHBoxLayout()
        refrow.addWidget(self.ref)
        for k in (2, 3):
            e = QtWidgets.QLineEdit("", box)
            e.setObjectName("SWDatumTargetRef%d" % k)
            self.refs.append(e)
            refrow.addWidget(e)
        self.height_label = QtWidgets.QLabel("Height:", box)
        for n, (lab, w) in enumerate((("Target area:", self.area), ("Target area size:", self.size),
                                      (self.height_label, self.height))):
            grid.addWidget(lab if isinstance(lab, QtWidgets.QLabel) else QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        grid.addWidget(QtWidgets.QLabel("Datum references:", box), 3, 0, 1, 2)
        grid.addLayout(refrow, 4, 0, 1, 2)       # under its label: beside it made the pane 331 px wide
        lay.addLayout(grid)
        self.symbol = QtWidgets.QCheckBox("Target symbol", box)
        self.symbol.setObjectName("SWDatumTargetShowSymbol")
        self.symbol.setChecked(True)
        lay.addWidget(self.symbol)
        self.outside = QtWidgets.QCheckBox("Display size outside the\nsymbol", box)
        self.outside.setObjectName("SWDatumTargetOutside")
        lay.addWidget(self.outside)

        def area(t):
            DL.row(self.size, t not in ("Point", "None"))
            DL.row(self.height, t == "Rectangle")
        self.area.currentTextChanged.connect(area)
        area(self.area.currentText())
        self.lay.addWidget(box)
        lbox, llay = D._group("Leader", self.form)
        self.bent = QtWidgets.QCheckBox("Bent leader", lbox)
        self.bent.setObjectName("SWDatumTargetBent")
        llay.addWidget(self.bent)
        self.lay.addWidget(lbox)
        self.leader = QtWidgets.QCheckBox("Leader", self.form)
        self.leader.setChecked(True)
        self.leader.hide()
        self.tip = None

    def place(self, p, tip):
        r = 5.0
        kind = self.area.currentText()
        size = self.size.text().strip() if kind != "Point" else ""
        if size and kind == "Circle" and not size.startswith("⌀"):
            size = "⌀" + size
        if size and kind == "Rectangle" and self.height.text().strip():
            size = "%s X %s" % (size, self.height.text().strip())
        if kind == "None":
            size = ""
        refs = ",".join(e.text().strip() for e in self.refs if e.text().strip())
        body = ['<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (r, STROKE),
                '<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (-r, r, STROKE),
                '<text x="0" y="%g" font-family="osifont, Arial" font-size="2.5" text-anchor="middle">%s</text>'
                % (3.4, _esc(refs))]
        if not self.symbol.isChecked():
            body = []                  # target area only: the leader starts at the click
        elif self.outside.isChecked():
            body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="2.5">%s</text>'
                        % (r + 1, -r * 0.6, _esc(size)))
        else:
            body.append('<text x="0" y="%g" font-family="osifont, Arial" font-size="2.5" text-anchor="middle">%s</text>'
                        % (-1.2, _esc(size)))
        if tip is not None:
            tx, ty = _rel(p, tip)
            L = math.hypot(tx, ty)
            r0 = r if self.symbol.isChecked() else 0.0
            if self.bent.isChecked() and abs(tx) > r0 + 4:
                sx = (r0 + 4) * (1 if tx > 0 else -1)      # bent leader: a short shoulder level with the symbol
                body.append('<path d="M%g 0 L%g 0 L%g %g" fill="none" stroke="#000" stroke-width="%g"/>'
                            % (r0 * (1 if tx > 0 else -1), sx, tx, ty, STROKE))
            elif L > r0:
                body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                            % (tx * r0 / L, ty * r0 / L, tx, ty, STROKE))
            a = 1.5
            if self.area.currentText() == "Point":
                body.append('<path d="M%g %g L%g %g M%g %g L%g %g" stroke="#000" stroke-width="%g"/>'
                            % (tx - a, ty - a, tx + a, ty + a, tx - a, ty + a, tx + a, ty - a, STROKE * 2))
            else:
                # the target area on the part, at the view's scale, in phantom line
                k = 1.0
                v = DV.view_at(self.page, tip)
                if v is not None:
                    k = DV.view_scale(v)

                def num(t):
                    try:
                        return float(t.strip().lstrip("⌀"))
                    except Exception:
                        return 0.0
                w = num(self.size.text()) * k
                h = (num(self.height.text()) or num(self.size.text())) * k
                ph = 'fill="none" stroke="#000" stroke-width="%g" stroke-dasharray="3,0.8,0.6,0.8"' % STROKE
                if kind == "Circle" and w > 0:
                    body.append('<circle cx="%g" cy="%g" r="%g" %s/>' % (tx, ty, w / 2, ph))
                elif kind == "Rectangle" and w > 0:
                    body.append('<rect x="%g" y="%g" width="%g" height="%g" %s/>' % (tx - w / 2, ty - h / 2, w, h, ph))
                elif kind == "None":
                    pass
                else:
                    body.append('<circle cx="%g" cy="%g" r="0.6" fill="#000"/>' % (tx, ty))
        s = svg_symbol(self.page, "DatumTarget", "".join(body), r + _reach(p, tip) + 20, p,
                       "Datum Target %s" % (refs or self.ref.text()), "DatumTarget")
        s.addProperty("App::PropertyString", "SWTarget", "FreeCAD", "datum target")
        s.SWTarget = "%s %s %s" % (self.area.currentText(), size, refs)
        s.addProperty("App::PropertyStringList", "SWTargetRefs", "FreeCAD", "datum references")
        s.SWTargetRefs = [e.text().strip() for e in self.refs]
        s.addProperty("App::PropertyBool", "SWTargetSymbol", "FreeCAD", "target symbol shown")
        s.SWTargetSymbol = self.symbol.isChecked()
        s.addProperty("App::PropertyBool", "SWTargetBent", "FreeCAD", "bent leader")
        s.SWTargetBent = self.bent.isChecked()
        return s


WELDS = ("None", "Fillet", "Square", "V-groove", "Bevel", "U-groove", "J-groove", "Flare-V", "Flare-bevel", "Plug",
         "Spot", "Seam", "Backing", "Surfacing", "Edge", "Corner flange", "Stud", "Melt-thru", "Slot")
WELD_CONTOURS = ("None", "Flat", "Convex", "Concave")
WELD_FINISHES = ("None", "C", "G", "H", "M", "R", "U")


def _weld_glyph(kind, below):
    """SVG of a weld symbol on the reference line (y 0), below for the arrow side, above for the other side."""
    s = 1.0 if below else -1.0
    h = 3.0
    if kind == "Fillet":
        return '<polygon points="0,0 0,%g %g,0" fill="none" stroke="#000" stroke-width="%g"/>' % (s * h, h, STROKE)
    if kind == "Square":
        return '<path d="M0 0 L0 %g M%g 0 L%g %g" stroke="#000" stroke-width="%g"/>' % (s * h, h * 0.6, h * 0.6, s * h, STROKE)
    if kind == "V-groove":
        return '<polyline points="%g,%g 0,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>' % (-h * 0.6, s * h, h * 0.6, s * h, STROKE)
    if kind == "Bevel":
        return '<polyline points="0,%g 0,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>' % (s * h, h * 0.8, s * h, STROKE)
    if kind in ("Plug", "Slot"):
        return '<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (
            -h * 0.6, 0 if below else -h * 0.8, h * 1.2, h * 0.8, STROKE)
    st = 'fill="none" stroke="#000" stroke-width="%g"' % STROKE
    if kind == "U-groove":
        r = h * 0.45
        return '<path d="M0 0 L0 %g M%g %g A%g %g 0 0 %d %g %g" %s/>' % (
            s * (h - r), -r, s * h, r, r, 1 if below else 0, r, s * h, st)
    if kind == "J-groove":
        r = h * 0.5
        return '<path d="M0 %g L0 0 M0 %g Q%g %g %g %g" %s/>' % (s * h, s * (h - r), r * 0.2, s * (h - r), r, s * h, st)
    if kind == "Flare-V":
        return '<path d="M%g %g Q%g %g %g 0 M%g %g Q%g %g %g 0" %s/>' % (
            -h * 0.8, s * h, -h * 0.15, s * h * 0.9, -h * 0.15, h * 0.8, s * h, h * 0.15, s * h * 0.9, h * 0.15, st)
    if kind == "Flare-bevel":
        return '<path d="M0 %g L0 0 M%g %g Q%g %g %g 0" %s/>' % (s * h, h * 0.9, s * h, h * 0.25, s * h * 0.9, h * 0.25, st)
    if kind == "Spot":
        return '<circle cx="0" cy="%g" r="%g" %s/>' % (s * h * 0.45, h * 0.45, st)
    if kind == "Seam":
        r = h * 0.45
        return ('<circle cx="0" cy="%g" r="%g" %s/>' % (s * r, r, st) +
                '<path d="M%g %g L%g %g M%g %g L%g %g" %s/>' % (-r * 1.6, s * r * 0.6, r * 1.6, s * r * 0.6,
                                                               -r * 1.6, s * r * 1.4, r * 1.6, s * r * 1.4, st))
    if kind == "Backing":
        r = h * 0.45
        return '<path d="M%g 0 A%g %g 0 0 %d %g 0" %s/>' % (-r, r, r, 0 if below else 1, r, st)
    if kind == "Surfacing":
        r = h * 0.3
        return '<path d="M%g 0 A%g %g 0 0 %d 0 0 A%g %g 0 0 %d %g 0" %s/>' % (
            -2 * r, r, r, 0 if below else 1, r, r, 0 if below else 1, 2 * r, st)
    if kind == "Edge":
        return '<path d="M%g %g L%g %g L%g 0 M%g %g L%g %g L%g 0" %s/>' % (
            -h * 0.6, s * h, -h * 0.2, s * h * 0.4, -h * 0.2, h * 0.6, s * h, h * 0.2, s * h * 0.4, h * 0.2, st)
    if kind == "Corner flange":
        return '<path d="M0 %g L0 0 M%g %g L%g %g L%g 0" %s/>' % (
            s * h, h * 0.8, s * h, h * 0.4, s * h * 0.4, h * 0.4, st)
    if kind == "Stud":
        r = h * 0.45
        q = r * 0.7
        return ('<circle cx="0" cy="%g" r="%g" %s/>' % (s * r, r, st) +
                '<path d="M%g %g L%g %g M%g %g L%g %g" %s/>' % (-q, s * r - q, q, s * r + q, -q, s * r + q, q,
                                                               s * r - q, st))
    if kind == "Melt-thru":
        r = h * 0.45
        return '<path d="M%g 0 A%g %g 0 0 %d %g 0 Z" fill="#000" stroke="#000" stroke-width="%g"/>' % (
            -r, r, r, 0 if not below else 1, r, STROKE)
    return ""



ISO_WELDS = (("Square Butt", "Square"), ("Single V Butt", "V-groove"), ("Single Bevel Butt", "Bevel"),
             ("Single U Butt", "U-groove"), ("Single J Butt", "J-groove"), ("Backing Run", "Backing"),
             ("Fillet", "Fillet"), ("Plug or Slot", "Plug"), ("Spot", "Spot"), ("Seam", "Seam"))


class WeldSymbolsPopup(QtWidgets.QDialog):
    """The Weld symbol... popup: the standard's weld symbols as buttons (tooltips their names), and none."""

    def __init__(self, parent, iso=True):
        super().__init__(parent)
        self.setObjectName("SWWeldSymbolsPopup")
        self.setWindowTitle("ISO Weld Symbols" if iso else "ANSI Weld Symbols")
        grid = QtWidgets.QGridLayout(self)
        self.picked = None
        items = [("None", "None")] + (list(ISO_WELDS) if iso else [(k, k) for k in WELDS if k != "None"])
        for n, (name, kind) in enumerate(items):
            b = QtWidgets.QToolButton(self)
            b.setText(name)
            b.setToolTip(name)
            b.setObjectName("SWWeldPick" + re.sub(r"[^A-Za-z0-9]", "", name))
            b.clicked.connect(lambda *_, k=kind: self._pick(k))
            grid.addWidget(b, n // 4, n % 4)

    def _pick(self, kind):
        self.picked = kind
        self.accept()


class WeldPropertiesDialog(QtWidgets.QDialog):
    ""


    def __init__(self, panel, iso=True):
        super().__init__(Gui.getMainWindow())
        self.panel = panel
        self.setObjectName("SWWeldProperties")
        self.setWindowTitle("Properties")
        self.setModal(False)
        lay = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget(self)
        # the tab scrolls when the box is taller than the screen (1366 x 768: it was 793 px high, its OK off screen)
        self.scroll = QtWidgets.QScrollArea(self.tabs)
        self.scroll.setObjectName("SWWeldPropertiesScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        page = QtWidgets.QWidget(self.scroll)
        self.page = page
        cols = QtWidgets.QHBoxLayout(page)
        self.body = QtWidgets.QVBoxLayout()
        self.side = QtWidgets.QVBoxLayout()
        cols.addLayout(self.body, 3)
        cols.addLayout(self.side, 2)
        self.scroll.setWidget(page)
        self.tabs.addTab(self.scroll, "ISO Weld Symbol" if iso else "ANSI Weld Symbol")
        lay.addWidget(self.tabs)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.setObjectName("SWWeldPropertiesButtons")
        bb.accepted.connect(lambda: self.panel.accept())
        bb.rejected.connect(lambda: self.panel.reject())
        lay.addWidget(bb)
        self._closing = False

    def place_beside(self):
        """To the right of the main window's graphics area, clear of the sheet's left part, kept on the screen."""
        mw = Gui.getMainWindow()
        try:
            g = mw.geometry()
            self.adjustSize()
            scr = (mw.screen() or QtWidgets.QApplication.primaryScreen()).availableGeometry()
            hint = self.page.sizeHint()
            chrome = self.sizeHint().height() - self.scroll.sizeHint().height()
            frame = max(0, self.frameGeometry().height() - self.height()) or 32     # the title bar
            want_w = max(self.width(), hint.width() + self.scroll.verticalScrollBar().sizeHint().width() + 30)
            want_h = min(hint.height() + chrome + 30, scr.height() - frame - 20)
            self.resize(min(want_w, scr.width() - 20), want_h)
            x = min(g.right() - self.width() - 40, scr.right() - self.width() - 10)
            y = min(g.top() + 120, scr.bottom() - self.height() - 10)
            self.move(max(scr.left(), x), max(scr.top(), y))
        except Exception as _fw_err:
            _fw_log("drawannot.py:weld properties place", _fw_err)

    def closeEvent(self, ev):
        if not self._closing:                # the box's own close button: the command ends, as Cancel
            self._closing = True
            try:
                self.panel.reject()
            except Exception as _fw_err:
                _fw_log("drawannot.py:weld properties close", _fw_err)
        super().closeEvent(ev)


class WeldSymbolPanel(_AnnotPanel):
    TITLE = "Weld Symbol"
    LAYER = True
    PIXMAP = "TechDraw_WeldSymbol"
    AGAIN = "Weld symbol placed. Click for the next one, or OK."
    LINES = ("Solid", "Dashed", "Phantom", "Chain", "Center", "Stitch", "Chain thick")
    THICK = ("0.18mm", "0.25mm", "0.35mm", "0.5mm", "0.7mm", "1mm", "1.4mm", "2mm", "Custom Size")

    BOX_GROUPS = ("Arrow Side", "Options", "Other Side", "Format", "Layer", "Style")

    def __init__(self, page):
        super().__init__(page)
        iso = "ISO" in str(_standard(page)).upper() or "DIN" in str(_standard(page)).upper() or \
            "BSI" in str(_standard(page)).upper() or "GOST" in str(_standard(page)).upper() or \
            "GB" in str(_standard(page)).upper()
        self.iso = iso
        self.props = WeldPropertiesDialog(self, iso)
        boxes = {}
        for i in range(self.lay.count()):
            wdg = self.lay.itemAt(i).widget()
            if isinstance(wdg, QtWidgets.QGroupBox) and wdg.title() in self.BOX_GROUPS:
                boxes[wdg.title()] = wdg
        for title in self.BOX_GROUPS:
            b = boxes.get(title)
            if b is not None:
                self.lay.removeWidget(b)
                b.setParent(None)
                (self.props.side if title in ("Format", "Layer", "Style") else self.props.body).addWidget(b)
        self.props.body.addStretch(1)
        self.props.side.addStretch(1)
        self.props.show()
        self.props.place_beside()
        # the box goes with the command however it ends (another command closing the task pane too)
        self._watch = QtCore.QTimer(self.props)
        self._watch.setInterval(500)
        self._watch.timeout.connect(lambda: None if Gui.Control.activeDialog() else self._close_props())
        self._watch.start()

    def _close_props(self):
        p = getattr(self, "props", None)
        if p is not None and not p._closing:
            p._closing = True
            p.close()

    def accept(self):
        self._close_props()
        return _AnnotPanel.accept(self)

    def reject(self):
        self._close_props()
        return _AnnotPanel.reject(self)

    def _symbol_button(self, box, lay, side, combo):
        """Weld symbol...: the standard's popup of weld symbols; the kind list stays behind it."""
        b = QtWidgets.QPushButton("Weld symbol...", box)
        b.setObjectName("SWWeld%sSymbolButton" % side)
        b.setToolTip("Weld symbol")

        def show(*_):
            names = dict((k, n) for n, k in ISO_WELDS) if getattr(self, "iso", True) else {}
            k = combo.currentText()
            b.setText("Weld symbol..." if k == "None" else names.get(k, k))

        def pick():
            pop = WeldSymbolsPopup(b, getattr(self, "iso", True))
            if pop.exec_() and pop.picked is not None:
                combo.setCurrentText(pop.picked)
        b.clicked.connect(pick)
        combo.currentTextChanged.connect(show)
        combo.hide()
        lay.addWidget(b)
        show()
        return b

    def build(self):
        from . import drawpmparts as PP
        self.say("Select a face, edge or sketch segment for Weld Symbol insertion.")
        self.leader_look = GeometricTolerancePanel._line_look(self, "Leader Style", "SWWeldLeader")
        PP.style_group(self)
        box, lay = D._group("Arrow Side", self.form)
        self.arrow_kind = QtWidgets.QComboBox(box)
        self.arrow_kind.setObjectName("SWWeldArrowSymbol")
        self.arrow_kind.addItems(WELDS)
        self.arrow_kind.setCurrentText("Fillet")
        self.arrow_size = QtWidgets.QLineEdit("", box)
        self.arrow_size.setObjectName("SWWeldArrowSize")
        lay.addWidget(self.arrow_kind)
        self._symbol_button(box, lay, "Arrow", self.arrow_kind)
        lay.addWidget(self.arrow_size)
        self.arrow_length, self.arrow_contour = self._side_fields(box, lay, "Arrow")
        self.lay.addWidget(box)
        box, lay = D._group("Other Side", self.form)
        self.other_kind = QtWidgets.QComboBox(box)
        self.other_kind.setObjectName("SWWeldOtherSymbol")
        self.other_kind.addItems(WELDS)
        self.other_size = QtWidgets.QLineEdit("", box)
        self.other_size.setObjectName("SWWeldOtherSize")
        lay.addWidget(self.other_kind)
        self._symbol_button(box, lay, "Other", self.other_kind)
        lay.addWidget(self.other_size)
        self.other_length, self.other_contour = self._side_fields(box, lay, "Other")
        self.lay.addWidget(box)
        box, lay = D._group("Options", self.form)
        self.field = QtWidgets.QCheckBox("Field/Site", box)
        self.field.setObjectName("SWWeldField")
        self.around = QtWidgets.QCheckBox("All around", box)
        self.around.setObjectName("SWWeldAllAround")
        lay.addWidget(self.field)
        lay.addWidget(self.around)
        self.stagger = QtWidgets.QCheckBox("Stagger", box)
        self.stagger.setObjectName("SWWeldStagger")
        lay.addWidget(self.stagger)
        self.symmetric = QtWidgets.QCheckBox("Symmetric", box)
        self.symmetric.setObjectName("SWWeldSymmetric")
        self.symmetric.toggled.connect(self._symmetric)
        lay.addWidget(self.symmetric)
        self.anchor = QtWidgets.QComboBox(box)
        self.anchor.setObjectName("SWWeldLeaderAnchor")
        self.anchor.addItems(["Closest", "Left", "Right", "None"])
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Leader anchor:", box))
        row.addWidget(self.anchor)
        lay.addLayout(row)
        grid = QtWidgets.QGridLayout()
        self.ident = QtWidgets.QComboBox(box)
        self.ident.setObjectName("SWWeldIdentLine")
        self.ident.addItems(["None", "Above", "Below"])
        self.process = QtWidgets.QLineEdit("", box)
        self.process.setObjectName("SWWeldProcess")
        grid.addWidget(QtWidgets.QLabel("Identification line:", box), 0, 0)
        grid.addWidget(self.ident, 0, 1)
        process_label = QtWidgets.QLabel("Process:", box)
        process_label.setToolTip("The welding process, written in the symbol's tail")
        grid.addWidget(process_label, 1, 0)
        grid.addWidget(self.process, 1, 1)
        lay.addLayout(grid)
        self.in_table = QtWidgets.QCheckBox("Include this symbol in weld table", box)
        self.in_table.setObjectName("SWWeldInTable")
        self.in_table.setChecked(True)
        lay.addWidget(self.in_table)
        self.lay.addWidget(box)
        PP.format_group(self, title="Format")
        self.leader = QtWidgets.QCheckBox("Leader", self.form)
        self.leader.setChecked(True)
        self.leader.hide()
        self.tip = None

    def _side_fields(self, box, lay, side):
        grid = QtWidgets.QGridLayout()
        length = QtWidgets.QLineEdit("", box)
        length.setObjectName("SWWeld%sLength" % side)
        length.setPlaceholderText("length-pitch")
        contour = QtWidgets.QComboBox(box)
        contour.setObjectName("SWWeld%sContour" % side)
        contour.addItems(WELD_CONTOURS)
        angle = QtWidgets.QLineEdit("", box)
        angle.setObjectName("SWWeld%sGrooveAngle" % side)
        root = QtWidgets.QLineEdit("", box)
        root.setObjectName("SWWeld%sRootOpening" % side)
        grid.addWidget(QtWidgets.QLabel("Length:", box), 0, 0)
        grid.addWidget(length, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Contour:", box), 1, 0)
        grid.addWidget(contour, 1, 1)
        grid.addWidget(QtWidgets.QLabel("Groove angle:", box), 2, 0)
        grid.addWidget(angle, 2, 1)
        grid.addWidget(QtWidgets.QLabel("Root opening:", box), 3, 0)
        grid.addWidget(root, 3, 1)
        finish = QtWidgets.QComboBox(box)
        finish.setObjectName("SWWeld%sFinish" % side)
        finish.addItems(WELD_FINISHES)
        finish.setToolTip("Finishing method: C chipping, G grinding, H hammering, M machining, R rolling, U unspecified")
        grid.addWidget(QtWidgets.QLabel("Finish method:", box), 4, 0)
        grid.addWidget(finish, 4, 1)
        lay.addLayout(grid)
        setattr(self, side.lower() + "_angle", angle)
        setattr(self, side.lower() + "_root", root)
        setattr(self, side.lower() + "_finish", finish)
        return length, contour

    def _symmetric(self, on):
        """Symmetric: the other side the same as the arrow side."""
        pairs = ((self.arrow_kind, self.other_kind), (self.arrow_size, self.other_size),
                 (self.arrow_length, self.other_length), (self.arrow_contour, self.other_contour),
                 (self.arrow_angle, self.other_angle), (self.arrow_root, self.other_root),
                 (self.arrow_finish, self.other_finish))
        for a, b in pairs:
            if on:
                if isinstance(a, QtWidgets.QComboBox):
                    b.setCurrentText(a.currentText())
                else:
                    b.setText(a.text())
            if not getattr(b, "_fw_live", False):         # NO DEAD CONTROLS: typing the other side turns Symmetric off
                b._fw_live = True
                DL.sets(self.symmetric, False, b)

    def place(self, p, tip):
        L = 18.0
        tx, ty = _rel(p, tip) if tip else (-12.0, 8.0)
        f = weld_scale(self.doc)
        tx, ty = tx / f, ty / f                      # the leader still ends on the weld once the symbol is scaled
        if self.symmetric.isChecked():
            self._symmetric(True)
        x0 = -L / 2 if tx < 0 else L / 2          # the leader leaves the reference line's end nearer the weld
        if self.anchor.currentText() != "Closest":
            x0 = -L / 2 if self.anchor.currentText() == "Left" else L / 2
        ld, lw = GeometricTolerancePanel._look(self.leader_look) if getattr(self, "leader_look", None) else ("", 0.0)
        lead = "" if self.anchor.currentText() == "None" else _restroke(_arrow(tx, ty, x0, 0), ld, lw)
        body = ['<line x1="%g" y1="0" x2="%g" y2="0" stroke="#000" stroke-width="%g"/>' % (-L / 2, L / 2, STROKE), lead]
        gx = 0.0
        body.append('<g transform="translate(%g 0)">%s</g>' % (gx, _weld_glyph(self.arrow_kind.currentText(), True)))
        ox = 2.5 if self.stagger.isChecked() else 0.0          # Stagger: the other side's weld moved along
        body.append('<g transform="translate(%g 0)">%s</g>' % (gx + ox, _weld_glyph(self.other_kind.currentText(), False)))
        if self.arrow_size.text():
            body.append('<text x="%g" y="4" font-family="osifont, Arial" font-size="2.5" text-anchor="end">%s</text>'
                        % (gx - 1, _esc(self.arrow_size.text())))
        if self.other_size.text():
            body.append('<text x="%g" y="-1.5" font-family="osifont, Arial" font-size="2.5" text-anchor="end">%s</text>'
                        % (gx - 1, _esc(self.other_size.text())))
        for below, length, contour, kind in ((True, self.arrow_length, self.arrow_contour, self.arrow_kind),
                                             (False, self.other_length, self.other_contour, self.other_kind)):
            sgn = 1.0 if below else -1.0
            dx = 0.0 if below else ox
            if length.text():
                body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="2.5">%s</text>'
                            % (gx + dx + 3.8, 4 if below else -1.5, _esc(length.text())))
            ga = (self.arrow_angle if below else self.other_angle).text()
            ro = (self.arrow_root if below else self.other_root).text()
            if ga:
                body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="2.2" text-anchor="middle">'
                            '%s\u00b0</text>' % (gx + dx + 1.5, 7.6 if below else -5.2, _esc(ga.rstrip("\u00b0"))))
            if ro:
                body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="2.2" text-anchor="middle">'
                            '%s</text>' % (gx + dx + 1.5, 2.6 if below else -0.6, _esc(ro)))
            c = contour.currentText()
            fin = (self.arrow_finish if below else self.other_finish).currentText()
            if fin != "None" and kind.currentText() != "None":       # the finish letter beyond the contour
                body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="2.2" text-anchor="middle">%s</text>'
                            % (gx + dx + 1.5, sgn * 7.2 + (0.8 if below else 0.0), _esc(fin)))
            if c != "None" and kind.currentText() != "None":
                yy = sgn * 4.2
                if c == "Flat":
                    body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>'
                                % (gx + dx - 0.5, yy, gx + dx + 3.5, yy, STROKE))
                else:
                    bulge = (1.0 if c == "Convex" else -1.0) * sgn
                    body.append('<path d="M%g %g Q%g %g %g %g" fill="none" stroke="#000" stroke-width="%g"/>'
                                % (gx + dx - 0.5, yy, gx + dx + 1.5, yy + bulge * 1.2, gx + dx + 3.5, yy, STROKE))
        if self.ident.currentText() != "None":
            yy = 1.2 if self.ident.currentText() == "Below" else -1.2      # ISO's dashed identification line
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g" stroke-dasharray="1.2,0.8"/>'
                        % (-L / 2, yy, L / 2, yy, STROKE))
        far = L / 2 if x0 < 0 else -L / 2
        if self.process.text():
            sg = 1.0 if far > 0 else -1.0
            body.append('<polyline points="%g,%g %g,0 %g,%g" fill="none" stroke="#000" stroke-width="%g"/>'
                        % (far + sg * 2.5, -2.5, far, far + sg * 2.5, 2.5, STROKE))
            body.append('<text x="%g" y="0.9" font-family="osifont, Arial" font-size="2.5" text-anchor="%s">%s</text>'
                        % (far + sg * 3.2, "start" if sg > 0 else "end", _esc(self.process.text())))
        if self.around.isChecked():
            body.append('<circle cx="%g" cy="0" r="1.2" fill="none" stroke="#000" stroke-width="%g"/>' % (x0, STROKE))
        if self.field.isChecked():
            body.append('<path d="M%g 0 L%g -5 L%g -4 L%g -3 Z" fill="#000" stroke="#000" stroke-width="%g"/>'
                        % (x0, x0, x0 + 2.5, x0, STROKE))
        try:
            from . import drawpmparts as PP
            font = PP.font_of(self)
            if font and font != "osifont, Arial":
                body = [b.replace('font-family="osifont, Arial"', 'font-family="%s"' % _esc(font)) for b in body]
        except Exception as _fw_err:
            _fw_log("drawannot.py:6083", _fw_err)
        if f != 1.0:
            body = ['<g transform="scale(%g)">%s</g>' % (f, "".join(body))]
        s = svg_symbol(self.page, "WeldSymbol", "".join(body), (L / 2) * f + _reach(p, tip), p, "Weld Symbol%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "WeldSymbol"])), "WeldSymbol")
        s.addProperty("App::PropertyString", "SWWeld", "FreeCAD", "weld symbol")
        s.SWWeld = "%s|%s|%s|%s|%s|%s" % (self.arrow_kind.currentText(), self.arrow_size.text(),
                                          self.other_kind.currentText(), self.other_size.text(),
                                          self.field.isChecked(), self.around.isChecked())
        s.addProperty("App::PropertyStringList", "SWWeldMore", "FreeCAD", "arrow length, arrow contour, other "
                      "length, other contour, stagger, identification line, process")
        s.SWWeldMore = [self.arrow_length.text(), self.arrow_contour.currentText(), self.other_length.text(),
                        self.other_contour.currentText(), str(self.stagger.isChecked()), self.ident.currentText(),
                        self.process.text(), self.arrow_angle.text(), self.arrow_root.text(), self.other_angle.text(),
                        self.other_root.text(), str(self.symmetric.isChecked()), self.anchor.currentText(),
                        self.arrow_finish.currentText(), self.other_finish.currentText()]
        s.addProperty("App::PropertyBool", "SWWeldInTable", "FreeCAD", "Include this symbol in weld table")
        s.SWWeldInTable = bool(self.in_table.isChecked())
        return s


STACK_SHAPES = ("Circular", "Triangle", "Hexagon", "Square", "Diamond")


def _stack_outline(shape, cx, cy, r):
    st = 'fill="none" stroke="#000" stroke-width="%g"' % STROKE
    if shape == "Square":
        return '<rect x="%g" y="%g" width="%g" height="%g" %s/>' % (cx - r, cy - r, 2 * r, 2 * r, st)
    sides = {"Triangle": (3, -90.0), "Hexagon": (6, 0.0), "Diamond": (4, 0.0)}.get(shape)
    if sides is None:
        return '<circle cx="%g" cy="%g" r="%g" %s/>' % (cx, cy, r, st)
    n, a0 = sides
    rr = r * (1.6 if n == 3 else 1.25 if n == 4 else 1.08)
    pts = " ".join("%g,%g" % (cx + rr * math.cos(math.radians(a0 + 360.0 * i / n)),
                              cy + rr * math.sin(math.radians(a0 + 360.0 * i / n))) for i in range(n))
    return '<polygon points="%s" %s/>' % (pts, st)


class StackedBalloonPanel(D._Panel):
    ""

    TITLE = "Stacked Balloon"
    LAYER = True
    PIXMAP = "TechDraw_Balloon"

    def build(self):
        self.say("Click a component for the first balloon, then where the stack goes. Then click more components "
                 "to add them to the stack.")
        box, lay = D._group("Settings", self.form)
        self.items = QtWidgets.QLineEdit("", box)
        self.items.setObjectName("SWStackedItems")
        self.items.setPlaceholderText("Item numbers (from the components picked)")
        self.items.editingFinished.connect(self.retype)
        lay.addWidget(self.items)
        self.direction = QtWidgets.QComboBox(box)
        self.direction.setObjectName("SWStackDirection")
        self.direction.addItems(["Up", "Down", "Left", "Right"])
        self.direction.setCurrentText("Right")
        self.direction.currentIndexChanged.connect(lambda *_: self.rebuild())
        lay.addWidget(self.direction)
        self.lay.addWidget(box)

        box, lay = D._group("Balloon Settings", self.form)
        self.shape = QtWidgets.QComboBox(box)
        self.shape.setObjectName("SWStackStyle")
        self.shape.addItems(list(STACK_SHAPES))
        self.size = QtWidgets.QComboBox(box)
        self.size.setObjectName("SWStackSize")
        self.size.addItems(["Tight Fit", "1 Character", "2 Characters", "3 Characters", "4 Characters", "5 Characters"])
        self.size.setCurrentText("2 Characters")
        for lab, w in (("Style:", self.shape), ("Size:", self.size)):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(lab, box))
            row.addWidget(w)
            lay.addLayout(row)
            w.currentIndexChanged.connect(lambda *_: self.rebuild())
        self.lay.addWidget(box)
        box, lay = D._group("Quantity", self.form)
        box.setCheckable(True)
        box.setChecked(False)
        box.setObjectName("SWStackQuantity")
        self.qty_box = box
        self.qty_where = QtWidgets.QComboBox(box)
        self.qty_where.setObjectName("SWStackQtyPlacement")
        self.qty_where.addItems(["Right", "Left", "Top", "Bottom"])
        self.qty_denote = QtWidgets.QComboBox(box)
        self.qty_denote.setObjectName("SWStackQtyDenote")
        self.qty_denote.addItems(["X", "x", " X", "PLCS", "PLACES"])
        for lab, w in (("Placement:", self.qty_where), ("Denotation:", self.qty_denote)):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(lab, box))
            row.addWidget(w)
            lay.addLayout(row)
            w.currentIndexChanged.connect(lambda *_: self.rebuild())
        box.toggled.connect(lambda *_: self.rebuild())
        self.lay.addWidget(box)
        self.tip = None
        self.view = None
        self.stack = None          # the stack being built: (symbol, tip, at, items)

    def typed(self):
        return [s.strip() for s in self.items.text().replace(";", ",").split(",") if s.strip()]

    def _number(self, view, p):
        try:
            return str(item_number(view, p)[0])
        except Exception:
            return "1"

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if self.stack is not None and self.tip is None and view is not None:
            sym, tip, at, items = self.stack
            n = self._number(view, p)
            if n not in items:
                items.append(n)
            self.stack = (sym, tip, at, items)
            self.rebuild()
            self.say("Balloon %s added to the stack. Click more components, or OK." % n)
            return True
        if self.tip is None:
            if view is None:
                self.say("Click a component inside a drawing view.")
                return True
            self.tip = p
            self.view = view
            self.first = self.typed() or [self._number(view, p)]
            self.say("Click where the stack goes.")
            return True
        tip, self.tip = self.tip, None
        p = magnetic_snap(self.page, p)[0]
        self.stack = (None, tip, p, list(self.first))
        self.rebuild()
        self.say("Stack placed. Click more components to add balloons to it, or OK.")
        return True

    def retype(self):
        if self.stack is not None and self.typed():
            sym, tip, at, _items = self.stack
            self.stack = (sym, tip, at, self.typed())
            self.rebuild()

    def rebuild(self):
        ""
        if self.stack is None:
            return
        sym, tip, p, items = self.stack
        fit = self.size.currentText()
        chars = max([len(str(i)) for i in items] + [1]) if fit == "Tight Fit" else int(fit.split()[0])
        r = max(2.0, TEXT_SIZE * (0.45 * chars + 0.75))
        step = {"Up": (0, -2 * r), "Down": (0, 2 * r), "Left": (-2 * r, 0), "Right": (2 * r, 0)}[
            self.direction.currentText()]
        body = []
        shape = self.shape.currentText()
        for n, it in enumerate(items):
            cx, cy = step[0] * n, step[1] * n
            body.append(_stack_outline(shape, cx, cy, r))
            body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                        % (cx, cy + TEXT_SIZE * 0.35, TEXT_SIZE, _esc(it)))
            if self.qty_box.isChecked() and self.view is not None:
                try:
                    q = quantity(self.view, it)
                except Exception:
                    q = ""
                if q:
                    t = "%s%s" % (q, self.qty_denote.currentText()) if self.qty_denote.currentText() in ("X", "x", " X") \
                        else "%s %s" % (q, self.qty_denote.currentText())
                    where = self.qty_where.currentText()
                    qx, qy, anchor = {"Right": (cx + r + 0.8, cy + TEXT_SIZE * 0.35, "start"),
                                      "Left": (cx - r - 0.8, cy + TEXT_SIZE * 0.35, "end"),
                                      "Top": (cx, cy - r - 0.8, "middle"),
                                      "Bottom": (cx, cy + r + TEXT_SIZE + 0.4, "middle")}[where]
                    body.append('<text x="%g" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="%s">%s</text>'
                                % (qx, qy, TEXT_SIZE, anchor, _esc(t)))
        tx, ty = _rel(p, tip)
        L = math.hypot(tx, ty)
        if L > r:
            body.append(_arrow(tx, ty, tx * r / L, ty * r / L, "Dot"))
        reach = max(abs(step[0]), abs(step[1])) * len(items) + r + _reach(p, tip)
        if sym is not None:
            try:
                self.doc.removeObject(sym.Name)
            except Exception as _fw_err:
                _fw_log("drawannot.py:6263", _fw_err)
            if sym in self.made:
                self.made.remove(sym)
        s = svg_symbol(self.page, "StackedBalloon", "".join(body), reach, p, "Stacked Balloon%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "StackedBalloon"])), "StackedBalloon")
        s.addProperty("App::PropertyStringList", "SWItems", "FreeCAD", "stacked item numbers")
        s.SWItems = list(items)
        line = magnetic_snap(self.page, p, 0.01)[1]
        join_magnetic(line, s)
        self.made.append(s)
        self.stack = (s, tip, p, list(items))
        self.items.blockSignals(True)
        self.items.setText(", ".join(items))
        self.items.blockSignals(False)
        self.doc.recompute()
        return s


def _doc_row(doc, page, text, default, key=None):
    from . import drawdocprops
    return drawdocprops.row(doc, page, text, default, key)


CLOUD_DASHES = {"Solid": "", "Dashed": "2,1", "Phantom": "6,1,1,1,1,1"}


def cloud_dash(doc):
    """Document Properties > Revision Clouds > Line style as the cloud's stroke."""
    d = CLOUD_DASHES.get(str(_doc_row(doc, "Revision Clouds", "Line style", "Solid", "cloud_line")), "")
    return ' stroke-dasharray="%s"' % d if d else ""


def cloud_width(doc):
    """Document Properties > Revision Clouds > Line thickness as the cloud's stroke width."""
    from . import drawdocprops
    name = _doc_row(doc, "Revision Clouds", "Line thickness", "Thick")
    return drawdocprops.thickness_mm(name, 0.35, doc)


def weld_scale(doc):
    ""
    if _doc_row(doc, "Weld Symbols", "Fixed size weld symbols", True, "weld_fixed"):
        return 1.0
    return max(0.4, float(TEXT_SIZE) / 2.5)


def cloud_path(points, arc):
    """A revision cloud: scallops of about arc mm along the closed polygon points (svg coordinates)."""
    d = []
    n = len(points)
    for i in range(n):
        (x0, y0), (x1, y1) = points[i], points[(i + 1) % n]
        L = math.hypot(x1 - x0, y1 - y0)
        k = max(1, int(round(L / arc)))
        for j in range(k):
            ax, ay = x0 + (x1 - x0) * j / k, y0 + (y1 - y0) * j / k
            bx, by = x0 + (x1 - x0) * (j + 1) / k, y0 + (y1 - y0) * (j + 1) / k
            if not d:
                d.append("M%g %g" % (ax, ay))
            r = math.hypot(bx - ax, by - ay) / 2
            d.append("A%g %g 0 0 1 %g %g" % (r, r, bx, by))
    return " ".join(d) + " Z"


class RevisionCloudPanel(D._Panel):
    TITLE = "Revision Cloud"
    LAYER = True
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Click two opposite corners of the cloud.")
        box, lay = D._group("Cloud Shape", self.form)
        self.shape = QtWidgets.QComboBox(box)
        self.shape.setObjectName("SWCloudShape")
        self.shape.addItems(["Rectangle", "Ellipse", "Irregular polygon", "Freehand"])
        self.shape.currentTextChanged.connect(self._shape_changed)
        lay.addWidget(self.shape)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Maximum arc radius:", box))
        self.arc = QtWidgets.QDoubleSpinBox(box)
        self.arc.setObjectName("SWCloudArc")
        self.arc.setRange(0.5, 100)
        self.arc.setValue(float(_doc_row(self.doc, "Revision Clouds", "Maximum arc radius", 3.0,
                                         "pm:Revision Cloud:SWCloudArc")))
        self.arc.setSuffix("mm")
        row.addWidget(self.arc)
        lay.addLayout(row)
        self.lay.addWidget(box)
        self.first = None
        self.points = []

    def _shape_changed(self, name):
        self.first, self.points = None, []
        self.drawing = False
        self.say("Click the corners of the cloud; click the first corner again (or OK) to close it."
                 if name == "Irregular polygon" else
                 "Click where the cloud starts, move the pointer around the area, then click to close it."
                 if name == "Freehand" else "Click two opposite corners of the cloud.")

    def sheet_move(self, p):
        """Freehand: the pointer's path, a point every arc or so."""
        if self.shape.currentText() != "Freehand" or not getattr(self, "drawing", False):
            return
        last = self.points[-1]
        if math.hypot(p[0] - last[0], p[1] - last[1]) >= max(1.0, self.arc.value()):
            self.points.append(p)

    def _polygon(self):
        pts, self.points = self.points, []
        if len(pts) < 3:
            return None
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        rel = [(q[0] - cx, -(q[1] - cy)) for q in pts]
        body = '<path d="%s" fill="none" stroke="#000" stroke-width="%g"%s/>' % (cloud_path(rel, 2 * self.arc.value()),
                                                                                 cloud_width(self.doc), cloud_dash(self.doc))
        reach = max(math.hypot(x, y) for x, y in rel) + self.arc.value()
        s = svg_symbol(self.page, "RevisionCloud", body, reach, (cx, cy), "Revision Cloud%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "RevisionCloud"])), "RevisionCloud")
        s.addProperty("App::PropertyString", "SWCloud", "FreeCAD", "cloud shape")
        s.SWCloud = "%s %d" % (self.shape.currentText(), len(pts))
        self.made.append(s)
        self.doc.recompute()
        return s

    def finish(self):
        self.drawing = False
        if self.points:
            self._polygon()

    def sheet_click(self, p):
        if self.shape.currentText() == "Freehand":
            if not getattr(self, "drawing", False):
                self.drawing, self.points = True, [p]
                self.say("Move the pointer around the area, then click to close the cloud.")
                return True
            self.drawing = False
            self.points.append(p)
            if self._polygon() is None:
                self.say("Move further around the area before closing. Click where the cloud starts.")
            else:
                self.say("Cloud placed. Click to start another, or OK.")
            return True
        if self.shape.currentText() == "Irregular polygon":
            if len(self.points) >= 3 and math.hypot(p[0] - self.points[0][0], p[1] - self.points[0][1]) < 2.0:
                self._polygon()
                self.say("Cloud placed. Click the corners of another, or OK.")
                return True
            self.points.append(p)
            self.say("Corner %d. Click the next corner; click the first corner again (or OK) to close it."
                     % len(self.points))
            return True
        if self.first is None:
            self.first = p
            self.say("Click the opposite corner.")
            return True
        a, self.first = self.first, None
        cx, cy = (a[0] + p[0]) / 2, (a[1] + p[1]) / 2
        w, h = abs(p[0] - a[0]) / 2, abs(p[1] - a[1]) / 2
        if w < 1 or h < 1:
            self.say("The cloud needs a size. Click a first corner again.")
            return True
        if self.shape.currentText() == "Ellipse":
            m = max(12, int(2 * math.pi * max(w, h) / (2 * self.arc.value())))
            pts = [(w * math.cos(2 * math.pi * i / m), h * math.sin(2 * math.pi * i / m)) for i in range(m)]
        else:
            pts = [(-w, -h), (w, -h), (w, h), (-w, h)]
        body = '<path d="%s" fill="none" stroke="#000" stroke-width="%g"%s/>' % (cloud_path(pts, 2 * self.arc.value()),
                                                                                 cloud_width(self.doc), cloud_dash(self.doc))
        s = svg_symbol(self.page, "RevisionCloud", body, max(w, h) + self.arc.value(), (cx, cy), "Revision Cloud%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "RevisionCloud"])), "RevisionCloud")
        s.addProperty("App::PropertyString", "SWCloud", "FreeCAD", "cloud shape")
        s.SWCloud = "%s %g x %g" % (self.shape.currentText(), 2 * w, 2 * h)
        self.made.append(s)
        self.doc.recompute()
        self.say("Cloud placed. Click two corners for another, or OK.")
        return True


class MultiJogLeaderPanel(D._Panel):
    TITLE = "Multi-jog Leader"
    LAYER = True
    PIXMAP = "TechDraw_LeaderLine"

    def build(self):
        self.say("Click where the arrow points, then each bend; OK ends the leader.")
        box, lay = D._group("Arrow", self.form)
        self.arrow = QtWidgets.QComboBox(box)
        self.arrow.setObjectName("SWAnnotArrow")
        self.arrow.addItems(["Filled arrow", "Open arrow", "Dot", "Filled triangle", "None"])
        lay.addWidget(self.arrow)
        self.lay.addWidget(box)
        self.points = []
        self.symbol = None

    def sheet_click(self, p):
        self.points.append(p)
        if len(self.points) >= 2:
            self.redraw()
        return True

    def redraw(self):
        pts = self.points
        cx = sum(x for x, _ in pts) / len(pts)
        cy = sum(y for _, y in pts) / len(pts)
        rel = [(x - cx, -(y - cy)) for x, y in pts]
        body = ['<polyline points="%s" fill="none" stroke="#000" stroke-width="%g"/>'
                % (" ".join("%g,%g" % q for q in rel[1:]), STROKE), _arrow(rel[0][0], rel[0][1], rel[1][0], rel[1][1],
                                                                           self.arrow.currentText())]
        reach = max(math.hypot(x, y) for x, y in rel)
        R = max(5.0, reach + 5.0)
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
               % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, "".join(body)))
        if self.symbol is None:
            self.symbol = svg_symbol(self.page, "MultiJogLeader", "".join(body), reach, (cx, cy), "Multi-jog Leader%d" % (
                1 + len([o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "MultiJogLeader"])),
                "MultiJogLeader")
            self.symbol.addProperty("App::PropertyInteger", "SWJogs", "FreeCAD", "leader points")
            self.made.append(self.symbol)
        else:
            self.symbol.Symbol = svg
            self.symbol.X, self.symbol.Y = cx, cy
        self.symbol.SWJogs = len(pts)
        self.doc.recompute()


# --------------------------------------------------------------------------- Area Hatch/Fill
def region_at(view, g):
    """The closed area of the view's lines around geometry point g, as a Part face (islands cut out), else None.
    A plane over the view is split by every visible line; the piece that holds g is the area."""
    import Part
    es = []
    for i, e in edges(view):
        try:
            es.append(e.copy())
        except Exception as _fw_err:
            _fw_log("drawannot.py:6497", _fw_err)
    if not es:
        return None
    bb = Part.Compound(es).BoundBox
    m = 1.0 + 0.1 * max(bb.XLength, bb.YLength)
    plane = Part.makePlane(bb.XLength + 2 * m, bb.YLength + 2 * m, V(bb.XMin - m, bb.YMin - m, 0))
    try:
        res, _ = plane.generalFuse(es, 1e-5)
    except Exception:
        return None
    pt = V(g[0], g[1], 0)
    inside = [f for f in res.Faces if f.isInside(pt, 1e-6, True)]
    if not inside:
        return None
    face = min(inside, key=lambda f: f.Area).copy()      # a copy of its own, with every edge given a 3D curve:
    try:                                                  # discretizing a fuse piece's bare edge crashed OpenCASCADE
        face.fix(1e-7, 1e-7, 1e-7)
    except Exception as _fw_err:
        _fw_log("drawannot.py:region fix", _fw_err)
    fb = face.BoundBox
    if fb.XMin <= bb.XMin - m / 2 or fb.YMin <= bb.YMin - m / 2:
        return None                     # outside the part: the piece reaches the plane's own border
    return face


HATCHES = ("ANSI31 (Iron BrickStone)", "ANSI32 (Steel)", "ANSI33 (Bronze Brass)", "ANSI34 (Plastic Rubber)",
           "ANSI35 (Fire Brick)", "ANSI36 (Marble)", "ANSI37 (Lead Zinc)", "ANSI38 (Aluminum)", "Concrete", "Earth",
           "Wood", "Solid")
DOUBLE = ("ANSI32", "ANSI33", "ANSI34", "ANSI35")       # a second, closer line beside each line
CROSS = ("ANSI36", "ANSI37", "ANSI38", "Earth")          # lines across too
WIDE = ("ANSI37", "ANSI38", "Concrete", "Earth", "Wood")  # twice the spacing


def hatch_defaults():
    """System Options > Drawings > Area Hatch/Fill: (fill, pattern, scale, angle) new hatches start with."""
    fill = str(D.system_option("Area Hatch/Fill", "Hatch", "Hatch"))
    pattern = str(D.system_option("Area Hatch/Fill", "Pattern", HATCHES[0]))
    try:
        scale = float(str(D.system_option("Area Hatch/Fill", "Scale", "1")).split()[0])
    except ValueError:
        scale = 1.0
    try:
        angle = float(str(D.system_option("Area Hatch/Fill", "Angle", "0.00deg")).replace("deg", "").replace("°", ""))
    except ValueError:
        angle = 0.0
    return (fill if fill in ("Hatch", "Solid", "None") else "Hatch",
            pattern if pattern in HATCHES else HATCHES[0], scale, angle)


def _wire_points(w, deflection=0.02):
    """The points along a closed wire, edge by edge and chained end to start. Discretizing the whole wire of a
    fuse piece by deflection crashed OpenCASCADE (a segfault no try can catch); each edge on its own is safe."""
    pts = []
    try:
        edges = w.OrderedEdges
    except Exception:
        edges = w.Edges
    for e in edges:
        try:
            q = e.discretize(Deflection=deflection) if type(e.Curve).__name__ != "Line" else \
                [e.Vertexes[0].Point, e.Vertexes[-1].Point]
        except Exception as _fw_err:
            _fw_log("drawannot.py:hatch edge", _fw_err)
            continue
        if len(q) < 2:
            continue
        if pts:
            last = pts[-1]
            if (q[-1] - last).Length < (q[0] - last).Length:
                q = list(reversed(q))
            q = q[1:]
        elif len(edges) > 1:            # the first edge runs towards the second
            n = edges[1].Vertexes
            ends = [v.Point for v in n]
            if min((q[0] - x).Length for x in ends) < min((q[-1] - x).Length for x in ends):
                q = list(reversed(q))
        pts.extend(q)
    return pts


def hatch_svg(face, view, spacing=2.5, angle=45.0, pattern="ANSI31 (Iron BrickStone)", color="#000000"):
    """SVG of face (view geometry) hatched, on the sheet at the view's scale, centred on the face's box."""
    k = DV.view_scale(view)
    bb = face.BoundBox
    cx, cy = (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2
    paths, polys = [], []
    for w in face.Wires:
        pts = _wire_points(w)
        paths.append("M" + " L".join("%g %g" % ((q.x - cx) * k, -(q.y - cy) * k) for q in pts) + " Z")
        polys.append([((q.x - cx) * k, (q.y - cy) * k) for q in pts])
    d = " ".join(paths)
    R = max(bb.XLength, bb.YLength) * k / 2 * 1.5 + 1
    cid = "fwclip%d" % (abs(hash(d)) % 100000)
    lines = []
    if pattern == "Solid":
        fill = '<path d="%s" fill="%s" fill-rule="evenodd" stroke="none"/>' % (d, color)
    else:
        gap = spacing * (2 if pattern.startswith(WIDE) else 1)
        a = math.radians(angle)
        ux, uy = math.cos(a), -math.sin(a)
        nx, ny = -uy, ux
        n = int(2 * R / gap) + 1
        for j in range(-n, n + 1):
            ox, oy = nx * j * gap, ny * j * gap
            lines.append("M%g %g L%g %g" % (ox - ux * 2 * R, oy - uy * 2 * R, ox + ux * 2 * R, oy + uy * 2 * R))
            if pattern.startswith(DOUBLE):
                ox2, oy2 = ox + nx * gap * 0.25, oy + ny * gap * 0.25
                lines.append("M%g %g L%g %g" % (ox2 - ux * 2 * R, oy2 - uy * 2 * R, ox2 + ux * 2 * R, oy2 + uy * 2 * R))
            if pattern.startswith(CROSS):
                lines.append("M%g %g L%g %g" % (ox - nx * 2 * R, oy - ny * 2 * R, ox + nx * 2 * R, oy + ny * 2 * R))
        # SVG Tiny (TechDraw's symbols) draws no clipPath: the lines are cut to the face here
        segs = DV.hatch_segments(polys, angle, gap)
        if pattern.startswith(DOUBLE):
            segs += DV.hatch_segments(polys, angle, gap, shift=0.25)
        if pattern.startswith(CROSS):
            segs += DV.hatch_segments(polys, angle + 90.0, gap)
        fill = '<path d="%s" stroke="%s" stroke-width="0.18" fill="none"/>' % (" ".join(
            "M%g %g L%g %g" % (a0[0], -a0[1], a1[0], -a1[1]) for a0, a1 in segs), color)
    x0, y0 = D.view_position(view)
    return fill, R, (x0 + cx * k, y0 + cy * k)


class AreaHatchPanel(D._Panel):
    TITLE = "Area Hatch/Fill"
    LAYER = True
    PIXMAP = "TechDraw_Hatch"

    def build(self):
        self.say("Click inside a closed area of a view to hatch it.")

        box, lay = D._group("Area to Hatch", self.form)
        row = QtWidgets.QHBoxLayout()
        self.area_kind = []
        for name in ("Region", "Boundary"):
            b = QtWidgets.QRadioButton(name, box)
            b.setObjectName("SWHatchArea" + name)
            b.setChecked(name == "Region")
            row.addWidget(b)
            self.area_kind.append(b)
        lay.addLayout(row)
        self.area_kind[1].toggled.connect(lambda on: (self.boundary.clear(), self.say(
            "Click the edges that bound the area; it is hatched when they close." if on else
            "Click inside a closed area of a view to hatch it.")))
        self.boundary = []          # (view, edge index, edge) picked for Boundary
        self.lay.addWidget(box)
        box, lay = D._group("Properties", self.form)
        row = QtWidgets.QHBoxLayout()
        self.fill = []
        for name in ("Hatch", "Solid", "None"):
            b = QtWidgets.QRadioButton(name, box)
            b.setObjectName("SWHatchFill" + name)
            b.setChecked(name == "Hatch")
            row.addWidget(b)
            self.fill.append(b)
        lay.addLayout(row)
        self.color = QtGui.QColor("#000000")
        self.color_button = QtWidgets.QPushButton("Color...", box)
        self.color_button.setObjectName("SWHatchColor")
        self.color_button.setVisible(False)

        def pick_color():
            c = QtWidgets.QColorDialog.getColor(self.color, self.form, "Color")
            if c.isValid():
                self.color = c
        self.color_button.clicked.connect(pick_color)
        lay.addWidget(self.color_button)
        self.pattern = QtWidgets.QComboBox(box)
        self.pattern.setObjectName("SWHatchPattern")
        self.pattern.addItems(HATCHES)
        lay.addWidget(self.pattern)
        grid = QtWidgets.QGridLayout()
        self.scale = QtWidgets.QDoubleSpinBox(box)
        self.scale.setObjectName("SWHatchScale")
        self.scale.setRange(0.1, 100)
        self.scale.setValue(1.0)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWHatchAngle")
        self.angle.setRange(-360, 360)
        self.angle.setValue(0.0)
        self.angle.setSuffix("°")
        grid.addWidget(QtWidgets.QLabel("Pattern scale:", box), 0, 0)
        grid.addWidget(self.scale, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Pattern angle:", box), 1, 0)
        grid.addWidget(self.angle, 1, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)

        def kind(*a):
            k = self.fill_kind()
            self.color_button.setVisible(k == "Solid")       # what does not apply is hidden, never greyed
            for x in (self.pattern, self.scale, self.angle):
                DL.row(x, k == "Hatch")
        fill, pattern, scale, angle = hatch_defaults()
        for b in self.fill:
            b.setChecked(b.text() == fill)
        self.pattern.setCurrentText(pattern)
        self.scale.setValue(scale)
        self.angle.setValue(angle)
        for b in self.fill:
            b.toggled.connect(kind)
        kind()

    def fill_kind(self):
        return next((b.text() for b in self.fill if b.isChecked()), "Hatch")

    def boundary_click(self, view, p):
        import Part
        k = DV.view_scale(view)
        hit = edge_at(view, DV.to_geometry(view, p), 2.0 / k)
        if hit is None:
            self.say("Click an edge of the boundary.")
            return True
        self.boundary = [b for b in self.boundary if b[0] is view]
        if any(i == hit[0] for _v, i, _e in self.boundary):
            self.boundary = [b for b in self.boundary if b[1] != hit[0]]       # a second click takes it off
            self.say("Edge taken off the boundary (%d picked)." % len(self.boundary))
            return True
        self.boundary.append((view, hit[0], hit[1]))
        es = [e.copy() for _v, _i, e in self.boundary]
        face = None
        try:
            for group in Part.sortEdges(es):
                w = Part.Wire(group)
                if w.isClosed():
                    face = Part.Face(w)
                    break
        except Exception:
            face = None
        if face is None or face.Area < 1e-9:
            self.say("%d edges picked. Click the next edge of the boundary." % len(self.boundary))
            return True
        self.boundary = []
        return self.hatch(view, face)

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if view is None:
            self.say("Click inside a closed area of a drawing view.")
            return True
        if self.area_kind[1].isChecked():
            return self.boundary_click(view, p)
        try:            # extapps85: inside a closed drawing sketch entity, that sketch profile is hatched
            from . import drawsketchopts
            face = drawsketchopts.sketch_region(view, DV.to_geometry(view, p))
        except Exception as _fw_err:
            _fw_log("drawannot.py:sketch-hatch", _fw_err)
            face = None
        if face is not None:
            self.sketch_area = True
            try:                # extapps88: the flag never outlives this hatch
                return self.hatch(view, face)
            finally:
                self.sketch_area = False
        face = region_at(view, DV.to_geometry(view, p))
        if face is None:
            self.say("That is not inside a closed area. Click inside one.")
            return True
        return self.hatch(view, face)

    def hatch(self, view, face):
        k = self.fill_kind()
        # an area hatched before: None takes it off, Hatch / Solid put the new one in its place
        c = face.BoundBox.Center
        old = [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "AreaHatch" and o in self.page.Views
               and abs(getattr(o, "SWHatchArea", -1) - face.Area) < 1e-6 and getattr(o, "SWHatchView", "") == view.Name
               and getattr(o, "SWHatchCentre", None) is not None and (o.SWHatchCentre - c).Length < 1e-6]
        for o in old:
            self.doc.removeObject(o.Name)
        if k == "None":
            self.doc.recompute()
            self.say("Hatch taken off. Click another area, or OK." if old else "That area has no hatch. Click a "
                     "hatched area, or OK.")
            return True
        if k == "Solid":
            body, R, at = hatch_svg(face, view, pattern="Solid", color=self.color.name())
        else:
            body, R, at = hatch_svg(face, view, 2.5 * self.scale.value(), 45.0 + self.angle.value(),
                                    self.pattern.currentText())
        s = svg_symbol(self.page, "AreaHatch", body, R, at, "Area Hatch%d" % (1 + len(
            [o for o in self.doc.Objects if getattr(o, "SWAnnotation", "") == "AreaHatch"])), "AreaHatch")
        s.addProperty("App::PropertyFloat", "SWHatchArea", "FreeCAD", "hatched area (model units)")
        s.SWHatchArea = face.Area
        s.addProperty("App::PropertyString", "SWHatchPattern", "FreeCAD", "hatch pattern")
        s.SWHatchPattern = "Solid" if k == "Solid" else self.pattern.currentText()
        s.addProperty("App::PropertyString", "SWHatchView", "FreeCAD", "the hatched view")
        s.SWHatchView = view.Name
        s.addProperty("App::PropertyVector", "SWHatchCentre", "FreeCAD", "the hatched area's center (view geometry)")
        s.SWHatchCentre = c
        if getattr(self, "sketch_area", False):        # extapps85: a sketch hatch, behind or over the view's lines
            self.sketch_area = False
            try:
                from . import drawsketchopts
                drawsketchopts.mark_hatch(s, view)
            except Exception as _fw_err:
                _fw_log("drawannot.py:sketch-hatch-mark", _fw_err)
        self.made.append(s)
        self.doc.recompute()
        self.say("Area hatched. Click another area, or OK.")
        return True


# --------------------------------------------------------------------------- land11: more annotations
def _count(doc, kind):
    return 1 + len([o for o in doc.Objects if getattr(o, "SWAnnotation", "") == kind])


def edge_at(view, g, tol):
    """The visible edge of view nearest geometry point g within tol: (index, edge), else None."""
    import Part
    best = None
    pt = Part.Vertex(V(g[0], g[1], 0))
    for i, e in edges(view):
        try:
            dist = e.distToShape(pt)[0]
        except Exception:
            continue
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, i, e)
    return best[1:] if best else None


class MagneticLinePanel(D._Panel):
    ""

    TITLE = "Magnetic Line"
    LAYER = True
    PIXMAP = "TechDraw_LeaderLine"
    CATCH = 10.0           # mm: annotations this near the line are pulled onto it

    def build(self):
        self.say("Click the start and the end of the magnetic line.")
        box, lay = D._group("Spacing", self.form)
        self.equal = QtWidgets.QRadioButton("Equal spacing", box)
        self.equal.setObjectName("SWMagEqual")
        self.equal.setChecked(True)
        self.free = QtWidgets.QRadioButton("Free drag", box)
        self.free.setObjectName("SWMagFree")
        lay.addWidget(self.equal)
        lay.addWidget(self.free)
        self.lay.addWidget(box)
        self.first = None

    def sheet_click(self, p):
        if self.first is None:
            self.first = p
            self.say("Click the end of the line.")
            return True
        a, self.first = self.first, None
        L = math.hypot(p[0] - a[0], p[1] - a[1])
        if L < 2:
            self.say("The line needs a length. Click a start point again.")
            return True
        line = magnetic_line(self.page, a, p, self.equal.isChecked(), self.CATCH)
        self.made.append(line)
        self.doc.recompute()
        self.say("Magnetic line placed with %d annotation(s). Click for another, or OK." % len(line.SWMembers))
        return True



# as well as balloons
MAGNETIC_KINDS = ("Balloon", "StackedBalloon", "Note", "RevisionSymbol", "GeometricTolerance", "WeldSymbol",
                  "SurfaceFinish")


def redraw_note(o, text=None):
    """A note drawn again where it is now, with its own format and its leader still ending where it was attached.
    text: what it shows (default: its text with its $PRP links read)."""
    import inspect
    import json
    page = next((p for p in o.InList if p.TypeId == "TechDraw::DrawPage"), None)
    raw = getattr(o, "SWText", "") or ""
    tip = getattr(o, "SWTip", None)
    tip = (tip.x, tip.y) if tip is not None and tip.z >= 0 else None
    try:
        f = json.loads(getattr(o, "SWNoteOptions", "") or "{}")
    except Exception:
        f = {}
    if not f:
        fmt = (getattr(o, "SWNoteFormat", "") or "").split("|")
        if len(fmt) == 4:
            f = dict(align=fmt[0], angle=float(fmt[1]), size=float(fmt[2]), border=fmt[3])
    names = set(inspect.signature(note_svg).parameters)
    f = {k: v for k, v in f.items() if k in names and k not in ("text", "at", "tip")}
    if text is None:
        text = resolve_properties(page, raw, tip) if page is not None and "$PRP" in raw else raw
    body, reach = note_svg(text or " ", (float(o.X), float(o.Y)), tip, **f)
    font = doc_font(o.Document)
    if font:
        body = with_font(body, font)
    o.Symbol = symbol_svg(body, reach)
    return True


def magnetic_line(page, a, b, equal=True, catch=10.0):
    doc = page.Document
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    ux, uy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(ux, uy)
    ux, uy = ux / L, uy / L
    found = []
    for o in doc.Objects:
        if getattr(o, "SWAnnotation", "") not in MAGNETIC_KINDS or o not in page.Views:
            continue
        x, y = float(o.X), float(o.Y)
        t = (x - a[0]) * ux + (y - a[1]) * uy
        d = abs((x - a[0]) * uy - (y - a[1]) * ux)
        if -catch <= t <= L + catch and d <= catch:
            found.append((t, o))
    found.sort(key=lambda q: q[0])
    n = len(found)
    for k, (t, o) in enumerate(found):
        if equal:
            t = L * (k + 1) / (n + 1)
        t = max(0.0, min(L, t))
        o.X, o.Y = a[0] + ux * t, a[1] + uy * t
        if getattr(o, "SWAnnotation", "") == "Note" and getattr(o, "SWTip", None) is not None and o.SWTip.z >= 0:
            try:
                redraw_note(o)          # the note moves onto the line; its leader stays on what it points at
            except Exception as error:
                App.Console.PrintLog("FreeCAD: magnetic line note: %s\n" % error)
    body = '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="%g"/>' % (
        a[0] - cx, -(a[1] - cy), b[0] - cx, -(b[1] - cy), STROKE)
    s = svg_symbol(page, "MagneticLine", body, L / 2, (cx, cy), "Magnetic Line%d" % _count(doc, "MagneticLine"),
                   "MagneticLine")
    s.addProperty("App::PropertyStringList", "SWMembers", "FreeCAD", "annotations on the line")
    s.SWMembers = [o.Name for _, o in found]
    s.addProperty("App::PropertyString", "SWLineEnds", "FreeCAD", "start and end on the sheet (mm)")
    s.SWLineEnds = "%.4f,%.4f,%.4f,%.4f" % (a[0], a[1], b[0], b[1])
    return s


def _line_ends(line):
    """A magnetic line's start and end on the sheet: as stored, or read from its drawn line (older lines)."""
    try:
        v = [float(x) for x in (getattr(line, "SWLineEnds", "") or "").split(",")]
        if len(v) == 4:
            return (v[0], v[1]), (v[2], v[3])
    except ValueError:
        pass
    import re
    m = re.search(r'x1="([-\d.e]+)" y1="([-\d.e]+)" x2="([-\d.e]+)" y2="([-\d.e]+)"', getattr(line, "Symbol", "") or "")
    if not m:
        return None
    x1, y1, x2, y2 = [float(g) for g in m.groups()]
    cx, cy = float(line.X), float(line.Y)
    return (cx + x1, cy - y1), (cx + x2, cy - y2)


def magnetic_snap(page, at, catch=5.0):
    ""

    best = None
    for line in page.Views:
        if getattr(line, "SWAnnotation", "") != "MagneticLine":
            continue
        ends = _line_ends(line)
        if not ends:
            continue
        (ax, ay), (bx, by) = ends
        L = math.hypot(bx - ax, by - ay)
        if L < 1e-9:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        t = (at[0] - ax) * ux + (at[1] - ay) * uy
        d = abs((at[0] - ax) * uy - (at[1] - ay) * ux)
        if -catch <= t <= L + catch and d <= catch and (best is None or d < best[0]):
            t = max(0.0, min(L, t))
            best = (d, (ax + ux * t, ay + uy * t), line)
    return (best[1], best[2]) if best else (at, None)


def join_magnetic(line, obj):
    if line is not None and obj is not None and obj.Name not in list(line.SWMembers):
        line.SWMembers = list(line.SWMembers) + [obj.Name]


def _along(edge, k, step):
    """Points along a view edge (geometry coordinates) about step apart, with the unit normal at each."""
    L = edge.Length
    n = max(1, int(L / step))
    out = []
    for j in range(n + 1):
        u = edge.getParameterByLength(min(L, L * j / n))
        q = edge.valueAt(u)
        tg = edge.tangentAt(u)
        out.append((q, V(-tg.y, tg.x, 0)))
    return out


def make_caterpillar(page, view, i, e, radius=1.5, spacing=1.5, flip=False):
    """Caterpillar: weld bead arcs along view edge e (index i)."""
    k = DV.view_scale(view)
    x0, y0 = D.view_position(view)
    pts = _along(e, k, spacing / k)
    bb = e.BoundBox
    cx, cy = (bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2
    r = radius
    s = -1.0 if flip else 1.0
    arcs = []
    for q, nrm in pts:
        sx, sy = (q.x - cx) * k, -(q.y - cy) * k
        mx, my = sx + s * nrm.x * r, sy - s * nrm.y * r
        arcs.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="#000" stroke-width="%g"/>'
                    % ((sx + mx) / 2, (sy + my) / 2, r / 2, STROKE))
    reach = max(bb.XLength, bb.YLength) * k / 2 + r
    obj = svg_symbol(page, "Caterpillar", "".join(arcs), reach, (x0 + cx * k, y0 + cy * k),
                     "Caterpillar%d" % _count(page.Document, "Caterpillar"), "Caterpillar")
    obj.addProperty("App::PropertyInteger", "SWBeads", "FreeCAD", "beads drawn")
    obj.SWBeads = len(pts)
    obj.addProperty("App::PropertyString", "SWEdge", "FreeCAD", "view and edge")
    obj.SWEdge = "%s Edge%d" % (view.Name, i)
    return obj


def make_end_treatment(page, view, end, other, side, kind="Filled", w=3.0):
    """End Treatment at view geometry point end of a weld edge running to other, on the side of point side."""
    k = DV.view_scale(view)
    d = other - end
    if d.Length < 1e-9:
        return None
    d.normalize()
    nrm = V(-d.y, d.x, 0)
    if nrm.x * (side[0] - end.x) + nrm.y * (side[1] - end.y) < 0:
        nrm = -nrm
    x0, y0 = D.view_position(view)
    at = (x0 + end.x * k, y0 + end.y * k)
    p1 = (d.x * w, -d.y * w)                       # svg coordinates (y down) relative to the edge end
    p2 = (nrm.x * w, -nrm.y * w)
    if kind == "Filled":
        shape = '<polygon points="0,0 %g,%g %g,%g" fill="#000" stroke="#000" stroke-width="%g"/>' % (
            p1[0], p1[1], p2[0], p2[1], STROKE)
    else:
        sweep = 1 if kind == "Concave" else 0
        shape = ('<path d="M0 0 L%g %g A%g %g 0 0 %d %g %g Z" fill="#000" stroke="#000" stroke-width="%g"/>'
                 % (p1[0], p1[1], w, w, sweep, p2[0], p2[1], STROKE))
    obj = svg_symbol(page, "EndTreatment", shape, w, at, "End Treatment%d" % _count(page.Document, "EndTreatment"),
                     "EndTreatment")
    obj.addProperty("App::PropertyString", "SWEndTreatment", "FreeCAD", "type and size")
    obj.SWEndTreatment = "%s %g" % (kind, w)
    return obj


def _beads(views):
    return [o for o in _unique_objects(views) if hasattr(o, "SymbolText") and hasattr(o, "Paths")]


def _bead_size(bead):
    import json
    try:
        return max(float(p.get("size", 3.0)) for p in json.loads(bead.Paths or "[]")) or 3.0
    except Exception:
        return 3.0


def bead_edges(view, bead, tol=1.0):
    """The visible edges of view along weld bead (inside the bead's outline in the view, the longest first)."""
    try:
        sh = bead.Shape
        if sh.isNull():
            return []
        pts = [_project(view, q.Point) for q in sh.Vertexes]
    except Exception:
        return []
    if not pts:
        return []
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    t = tol / max(DV.view_scale(view), 1e-9)
    x0, x1, y0, y1 = min(xs) - t, max(xs) + t, min(ys) - t, max(ys) + t
    out = []
    for i, e in edges(view):
        bb = e.BoundBox
        if bb.XMin >= x0 and bb.XMax <= x1 and bb.YMin >= y0 and bb.YMax <= y1 and e.Length > 1e-6:
            out.append((i, e))
    out.sort(key=lambda ie: -ie[1].Length)
    return out


def model_caterpillars(page, views, eliminate_duplicates=True):
    """Model Items' Caterpillar: weld bead arcs along each weld bead's edge in each view."""
    made = []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for bead in _beads(views):
        for v in views:
            if bead not in _model_objects(v):
                continue
            key = "caterpillar:%s/%s" % (v.Name, bead.Name)
            es = bead_edges(v, bead)
            if key in seen or not es:
                continue
            i, e = es[0]
            o = make_caterpillar(page, v, i, e, radius=max(0.5, min(_bead_size(bead) / 2.0, 3.0)))
            o.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
            o.SWModelItemKey = key
            seen.add(key)
            made.append(o)
    return made


def model_end_treatments(page, views, eliminate_duplicates=True):
    """Model Items' End treatment: a filled weld end at both ends of each weld bead's edge in each view."""
    made = []
    seen = {getattr(o, "SWModelItemKey", "") for o in page.Document.Objects if hasattr(o, "SWModelItemKey")} \
        if eliminate_duplicates else set()
    for bead in _beads(views):
        for v in views:
            if bead not in _model_objects(v):
                continue
            key = "endtreatment:%s/%s" % (v.Name, bead.Name)
            es = bead_edges(v, bead)
            if key in seen or not es or len(es[0][1].Vertexes) < 2:
                continue
            e = es[0][1]
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            try:
                c = _project(v, bead.Shape.BoundBox.Center)
                side = (c.x, c.y)
            except Exception:
                side = ((a.x + b.x) / 2 + 1, (a.y + b.y) / 2 + 1)
            w = _bead_size(bead)
            for end, other in ((a, b), (b, a)):
                o = make_end_treatment(page, v, end, other, side, "Filled", w)
                if o is None:
                    continue
                o.addProperty("App::PropertyString", "SWModelItemKey", "FreeCAD", "model item it came from")
                o.SWModelItemKey = key
                made.append(o)
            seen.add(key)
    return made


class CaterpillarPanel(D._Panel):
    """Click an edge of a view: weld bead arcs are drawn along it."""
    TITLE = "Caterpillar"
    LAYER = True
    PIXMAP = "TechDraw_WeldSymbol"

    def build(self):
        self.say("Click the weld edge in a view.")
        box, lay = D._group("Parameters", self.form)
        grid = QtWidgets.QGridLayout()
        self.radius = QtWidgets.QDoubleSpinBox(box)
        self.radius.setObjectName("SWCaterpillarRadius")
        self.radius.setRange(0.2, 50)
        self.radius.setValue(1.5)
        self.radius.setSuffix("mm")
        self.spacing = QtWidgets.QDoubleSpinBox(box)
        self.spacing.setObjectName("SWCaterpillarSpacing")
        self.spacing.setRange(0.2, 50)
        self.spacing.setValue(1.5)
        self.spacing.setSuffix("mm")
        self.flip = QtWidgets.QCheckBox("Reverse direction", box)
        self.flip.setObjectName("SWCaterpillarFlip")
        grid.addWidget(QtWidgets.QLabel("Bead radius:", box), 0, 0)
        grid.addWidget(self.radius, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Spacing:", box), 1, 0)
        grid.addWidget(self.spacing, 1, 1)
        lay.addLayout(grid)
        lay.addWidget(self.flip)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if view is None:
            self.say("Click an edge inside a drawing view.")
            return True
        k = DV.view_scale(view)
        hit = edge_at(view, DV.to_geometry(view, p), 3.0 / k)
        if hit is None:
            self.say("Click right on an edge.")
            return True
        i, e = hit
        obj = make_caterpillar(self.page, view, i, e, self.radius.value(), self.spacing.value(),
                               self.flip.isChecked())
        self.made.append(obj)
        self.doc.recompute()
        self.say("Caterpillar placed. Click another edge, or OK.")
        return True


class EndTreatmentPanel(D._Panel):
    """Click near the end of a weld edge: a filled weld end (fillet leg triangle) is drawn there."""
    TITLE = "End Treatment"
    LAYER = True
    PIXMAP = "TechDraw_WeldSymbol"

    def build(self):
        self.say("Click near the end of the weld edge in a view.")
        box, lay = D._group("Parameters", self.form)
        self.kind = QtWidgets.QComboBox(box)
        self.kind.setObjectName("SWEndTreatmentType")
        self.kind.addItems(["Filled", "Concave", "Convex"])
        lay.addWidget(self.kind)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Weld size:", box))
        self.size = QtWidgets.QDoubleSpinBox(box)
        self.size.setObjectName("SWEndTreatmentSize")
        self.size.setRange(0.2, 50)
        self.size.setValue(3.0)
        self.size.setSuffix("mm")
        row.addWidget(self.size)
        lay.addLayout(row)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        view = DV.view_at(self.page, p)
        if view is None:
            self.say("Click a weld edge inside a drawing view.")
            return True
        k = DV.view_scale(view)
        g = DV.to_geometry(view, p)
        hit = edge_at(view, g, 3.0 / k)
        if hit is None or len(hit[1].Vertexes) < 2:
            self.say("Click right on an edge, near its end.")
            return True
        e = hit[1]
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        end, other = (a, b) if math.hypot(g[0] - a.x, g[1] - a.y) <= math.hypot(g[0] - b.x, g[1] - b.y) else (b, a)
        obj = make_end_treatment(self.page, view, end, other, g, self.kind.currentText(), self.size.value())
        if obj is None:
            return True
        self.made.append(obj)
        self.doc.recompute()
        self.say("End treatment placed. Click another weld end, or OK.")
        return True


class DowelPinPanel(D._Panel):
    ""
    TITLE = "Dowel Pin Symbol"
    LAYER = True
    PIXMAP = "TechDraw_ExtensionCircleCenterLines"

    def build(self):
        self.say("Click a circular edge in a view.")
        box, lay = D._group("Display", self.form)
        self.flip = QtWidgets.QCheckBox("Flip symbol", box)
        self.flip.setObjectName("SWDowelFlip")
        lay.addWidget(self.flip)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        view, hit = circle_under(self.page, p, 3.0)
        if view is None:
            self.say("Click a circle inside a drawing view.")
            return True
        k = DV.view_scale(view)
        if hit is None:
            self.say("Click right on a circle.")
            return True
        i, c, r = hit
        R = r * k
        x0, y0 = D.view_position(view)
        q = (0, 2) if not self.flip.isChecked() else (1, 3)
        body = ['<circle cx="0" cy="0" r="%g" fill="none" stroke="#000" stroke-width="%g"/>' % (R, STROKE)]
        for j in q:
            a0, a1 = math.radians(90 * j), math.radians(90 * (j + 1))
            body.append('<path d="M0 0 L%g %g A%g %g 0 0 0 %g %g Z" fill="#000" stroke="none"/>'
                        % (R * math.cos(a0), -R * math.sin(a0), R, R, R * math.cos(a1), -R * math.sin(a1)))
        body.append('<path d="M%g 0 L%g 0 M0 %g L0 %g" stroke="#000" stroke-width="%g"/>' % (-R, R, -R, R, STROKE))
        obj = svg_symbol(self.page, "DowelPin", "".join(body), R, (x0 + c.x * k, y0 + c.y * k),
                         "Dowel Pin%d" % _count(self.doc, "DowelPin"), "DowelPin")
        obj.addProperty("App::PropertyFloat", "SWDiameter", "FreeCAD", "pin diameter (model units)")
        obj.SWDiameter = 2 * r
        self.made.append(obj)
        self.doc.recompute()
        self.say("Dowel pin symbol placed. Click another circle, or OK.")
        return True


def sheet_zone(page, x, y):
    """The sheet's grid zone at sheet point x, y: rows A.. from the bottom, columns 1.. from the right (Sheet
    Properties' Zone Parameters)."""
    try:
        from . import drawsheet
        return drawsheet.zone_at(page, x, y)
    except Exception as _fw_err:
        _fw_log("drawannot.py:7176", _fw_err)
    try:
        W, H = float(page.Template.Width), float(page.Template.Height)
    except Exception:
        W, H = 279.4, 215.9
    cols = max(2, int(round(W / 50.0)))
    rows = max(2, int(round(H / 50.0)))
    c = min(cols, max(1, cols - int(x / (W / cols))))
    r = min(rows - 1, max(0, int(y / (H / rows))))
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    return "%s%d" % (letters[r], c)


def location_text(view):
    """'SECTION A-A' / 'DETAIL B' + scale + where the cut or the detail circle is on the sheet."""
    page = None
    for o in view.InList:
        if o.TypeId == "TechDraw::DrawPage":
            page = o
    k = DV.view_scale(view)
    scale = "SCALE %g : 1" % round(k, 4) if k >= 1 else "SCALE 1 : %g" % round(1 / k, 4)
    if view.TypeId == "TechDraw::DrawViewSection":
        name = "SECTION %s-%s" % (view.SectionSymbol, view.SectionSymbol)
        base = view.BaseView
    elif view.TypeId == "TechDraw::DrawViewDetail":
        name = "DETAIL %s" % view.Reference
        base = view.BaseView
    else:
        name, base = view.Label.upper(), None
    lines = [name, scale]
    if base is not None and page is not None:
        bx, by = D.view_position(base)
        if view.TypeId == "TechDraw::DrawViewDetail":
            bk = DV.view_scale(base)
            bx, by = bx + view.AnchorPoint.x * bk, by + view.AnchorPoint.y * bk
        lines.append("LOCATION %s" % sheet_zone(page, bx, by))
    return lines


class LocationLabelPanel(D._Panel):
    TITLE = "Location Label"
    LAYER = True
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Click a section or detail view: its label (with where it is cut) goes under it.")

    def sheet_click(self, p):
        view = None
        for v in D.views_of(self.page):
            if v.TypeId not in ("TechDraw::DrawViewSection", "TechDraw::DrawViewDetail"):
                continue
            a, b, c, d = DV.view_box(v) if v.TypeId != "TechDraw::DrawViewDetail" else _detail_box(v)
            if a - 3 <= p[0] <= c + 3 and b - 3 <= p[1] <= d + 3:
                view = v
        if view is None:
            self.say("Click a section view or a detail view.")
            return True
        lines = location_text(view)
        a, b, c, d = DV.view_box(view) if view.TypeId != "TechDraw::DrawViewDetail" else _detail_box(view)
        at = ((a + c) / 2, b - 8)
        body = "".join('<text x="0" y="%g" font-family="osifont, Arial" font-size="%g" text-anchor="middle">%s</text>'
                       % (j * TEXT_SIZE * 1.4, TEXT_SIZE, _esc(s)) for j, s in enumerate(lines))
        obj = svg_symbol(self.page, "LocationLabel", body, _text_width(max(lines, key=len)) / 2 + 5, at,
                         "Location Label%d" % _count(self.doc, "LocationLabel"), "LocationLabel")
        obj.addProperty("App::PropertyStringList", "SWLines", "FreeCAD", "label lines")
        obj.SWLines = lines
        obj.addProperty("App::PropertyString", "SWView", "FreeCAD", "labeled view")
        obj.SWView = view.Name
        self.made.append(obj)
        self.doc.recompute()
        self.say("Label placed. Click another view, or OK.")
        return True


def _detail_box(v):
    x, y = D.view_position(v)
    r = float(v.Radius) * DV.view_scale(v)
    return x - r, y - r, x + r, y + r


NOTE_KINDS = ("Note", "Balloon", "SurfaceFinish", "GeometricTolerance", "DatumFeature", "WeldSymbol", "DatumTarget")


def nearest_note(page, p, tol=12.0):
    best = None
    for o in page.Views:
        if getattr(o, "SWAnnotation", "") not in NOTE_KINDS:
            continue
        dist = math.hypot(float(o.X) - p[0], float(o.Y) - p[1])
        if dist <= tol and (best is None or dist < best[0]):
            best = (dist, o)
    return best[1] if best else None


def copy_note(page, src, x, y):
    s = svg_symbol(page, src.Name.rstrip("0123456789") or "Note", "", 0, (x, y), src.Label, src.SWAnnotation)
    s.Symbol = src.Symbol
    for name in src.PropertiesList:
        if name.startswith("SW") and name != "SWAnnotation":
            try:
                if name not in s.PropertiesList:
                    s.addProperty(src.getTypeIdOfProperty(name), name, "FreeCAD", "")
                setattr(s, name, getattr(src, name))
            except Exception as _fw_err:
                _fw_log("drawannot.py:7281", _fw_err)
    s.addProperty("App::PropertyString", "SWPatternOf", "FreeCAD", "seed annotation")
    s.SWPatternOf = src.Name
    return s


class LinearNotePatternPanel(D._Panel):
    TITLE = "Linear Note Pattern"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Click the note to pattern.")
        box, lay = D._group("Direction 1", self.form)
        grid = QtWidgets.QGridLayout()
        self.spacing = QtWidgets.QDoubleSpinBox(box)
        self.spacing.setObjectName("SWNotePatSpacing")
        self.spacing.setRange(-1000, 1000)
        self.spacing.setValue(10.0)
        self.spacing.setSuffix("mm")
        self.count = QtWidgets.QSpinBox(box)
        self.count.setObjectName("SWNotePatCount")
        self.count.setRange(2, 200)
        self.count.setValue(3)
        self.angle = QtWidgets.QDoubleSpinBox(box)
        self.angle.setObjectName("SWNotePatAngle")
        self.angle.setRange(-360, 360)
        self.angle.setSuffix("°")
        for n, (lab, w) in enumerate((("Spacing:", self.spacing), ("Instances:", self.count), ("Angle:", self.angle))):
            grid.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)

    def sheet_click(self, p):
        src = nearest_note(self.page, p)
        if src is None:
            self.say("Click on a note, balloon or symbol.")
            return True
        a = math.radians(self.angle.value())
        dx, dy = math.cos(a) * self.spacing.value(), math.sin(a) * self.spacing.value()
        x, y = float(src.X), float(src.Y)
        for j in range(1, self.count.value()):
            self.made.append(copy_note(self.page, src, x + dx * j, y + dy * j))
        self.doc.recompute()
        self.say("Pattern made. Click another note, or OK.")
        return True


class CircularNotePatternPanel(D._Panel):
    TITLE = "Circular Note Pattern"
    PIXMAP = "TechDraw_Annotation"

    def build(self):
        self.say("Click the pattern center, then the note to pattern.")
        box, lay = D._group("Parameters", self.form)
        grid = QtWidgets.QGridLayout()
        self.count = QtWidgets.QSpinBox(box)
        self.count.setObjectName("SWNotePatCount")
        self.count.setRange(2, 200)
        self.count.setValue(4)
        self.total = QtWidgets.QDoubleSpinBox(box)
        self.total.setObjectName("SWNotePatTotal")
        self.total.setRange(-360, 360)
        self.total.setValue(360)
        self.total.setSuffix("°")
        self.equal = QtWidgets.QCheckBox("Equal spacing", box)
        self.equal.setObjectName("SWNotePatEqual")
        self.equal.setChecked(True)
        grid.addWidget(QtWidgets.QLabel("Instances:", box), 0, 0)
        grid.addWidget(self.count, 0, 1)
        grid.addWidget(QtWidgets.QLabel("Angle:", box), 1, 0)
        grid.addWidget(self.total, 1, 1)
        lay.addLayout(grid)
        lay.addWidget(self.equal)
        self.lay.addWidget(box)
        self.centre = None

    def sheet_click(self, p):
        if self.centre is None:
            self.centre = p
            self.say("Click the note to pattern.")
            return True
        src = nearest_note(self.page, p)
        if src is None:
            self.say("Click on a note, balloon or symbol.")
            return True
        cx, cy = self.centre
        x, y = float(src.X) - cx, float(src.Y) - cy
        n = self.count.value()
        tot = self.total.value()
        step = tot / n if (self.equal.isChecked() and abs(abs(tot) - 360) < 1e-6) else \
            (tot / (n - 1) if self.equal.isChecked() else tot)
        for j in range(1, n):
            a = math.radians(step * j)
            self.made.append(copy_note(self.page, src, cx + x * math.cos(a) - y * math.sin(a),
                                       cy + x * math.sin(a) + y * math.cos(a)))
        self.centre = None
        self.doc.recompute()
        self.say("Pattern made. Click a center for another, or OK.")
        return True


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawCenterMark": ("Center Mark", "TechDraw_ExtensionCircleCenterLines",
                                 "Adds a center mark to circles or arcs."),
    "FreeWorks_DrawCenterline": ("Centerline", "TechDraw_2LineCenterLine",
                                 "Adds a centerline between two edges of a view."),
    "FreeWorks_DrawModelItems": ("Model Items", "TechDraw_Dimension",
                                 "Brings dimensions from the model into the drawing views."),
    "FreeWorks_DrawHoleCallout": ("Hole Callout", "TechDraw_Balloon",
                                  "Adds a hole callout to a hole in a view."),
    "FreeWorks_DrawNote": ("Note", "TechDraw_Annotation", "Adds a note, with or without a leader."),
    "FreeWorks_DrawBalloon": ("Balloon", "TechDraw_Balloon", "Adds a balloon that points at a part."),
    "FreeWorks_DrawAutoBalloon": ("Auto Balloon", "TechDraw_Balloon", "Adds balloons for all the parts of a view."),
    "FreeWorks_DrawSurfaceFinish": ("Surface Finish", "TechDraw_SurfaceFinishSymbols",
                                    "Adds a surface finish symbol."),
    "FreeWorks_DrawGeometricTolerance": ("Geometric Tolerance", "TechDraw_Annotation",
                                         "Adds a geometric tolerance (feature control frame)."),
    "FreeWorks_DrawDatumFeature": ("Datum Feature", "TechDraw_Annotation", "Adds a datum feature symbol."),
    "FreeWorks_DrawDatumTarget": ("Datum Target", "TechDraw_Annotation", "Adds a datum target symbol."),
    "FreeWorks_DrawWeldSymbol": ("Weld Symbol", "TechDraw_WeldSymbol", "Adds a weld symbol."),
    "FreeWorks_DrawStackedBalloon": ("Stacked Balloon", "TechDraw_Balloon",
                                     "Adds a stack of balloons with one leader."),
    "FreeWorks_DrawRevisionCloud": ("Revision Cloud", "TechDraw_Annotation", "Adds a revision cloud."),
    "FreeWorks_DrawMultiJogLeader": ("Multi-jog Leader", "TechDraw_LeaderLine", "Adds a leader with bends."),
    "FreeWorks_DrawAreaHatch": ("Area Hatch/Fill", "TechDraw_Hatch", "Hatches or fills a closed area of a view."),
    "FreeWorks_DrawMagneticLine": ("Magnetic Line", "TechDraw_LeaderLine", "Lines up balloons, notes, revision symbols, geometric tolerances, weld and surface finish symbols along a line."),
    "FreeWorks_DrawCaterpillar": ("Caterpillar", "TechDraw_WeldSymbol", "Shows a weld bead along an edge."),
    "FreeWorks_DrawEndTreatment": ("End Treatment", "TechDraw_WeldSymbol", "Shows the end of a weld bead."),
    "FreeWorks_DrawDowelPin": ("Dowel Pin Symbol", "TechDraw_ExtensionCircleCenterLines",
                               "Adds a dowel pin symbol to a circle."),
    "FreeWorks_DrawLocationLabel": ("Location Label", "TechDraw_Annotation",
                                    "Labels a section or detail view with where it is cut."),
    "FreeWorks_DrawLinearNotePattern": ("Linear Note Pattern", "TechDraw_Annotation", "Copies a note in a row."),
    "FreeWorks_DrawCircularNotePattern": ("Circular Note Pattern", "TechDraw_Annotation",
                                          "Copies a note around a center."),
}
PANELS = {"FreeWorks_DrawCenterMark": CenterMarkPanel, "FreeWorks_DrawCenterline": CenterlinePanel,
          "FreeWorks_DrawModelItems": ModelItemsPanel, "FreeWorks_DrawHoleCallout": HoleCalloutPanel,
          "FreeWorks_DrawNote": NotePanel, "FreeWorks_DrawBalloon": BalloonPanel,
          "FreeWorks_DrawAutoBalloon": AutoBalloonPanel, "FreeWorks_DrawSurfaceFinish": SurfaceFinishPanel,
          "FreeWorks_DrawGeometricTolerance": GeometricTolerancePanel,
          "FreeWorks_DrawDatumFeature": DatumFeaturePanel, "FreeWorks_DrawDatumTarget": DatumTargetPanel,
          "FreeWorks_DrawWeldSymbol": WeldSymbolPanel, "FreeWorks_DrawStackedBalloon": StackedBalloonPanel,
          "FreeWorks_DrawRevisionCloud": RevisionCloudPanel, "FreeWorks_DrawMultiJogLeader": MultiJogLeaderPanel,
          "FreeWorks_DrawAreaHatch": AreaHatchPanel, "FreeWorks_DrawMagneticLine": MagneticLinePanel,
          "FreeWorks_DrawCaterpillar": CaterpillarPanel, "FreeWorks_DrawEndTreatment": EndTreatmentPanel,
          "FreeWorks_DrawDowelPin": DowelPinPanel, "FreeWorks_DrawLocationLabel": LocationLabelPanel,
          "FreeWorks_DrawLinearNotePattern": LinearNotePatternPanel,
          "FreeWorks_DrawCircularNotePattern": CircularNotePatternPanel}



def _model3d():
    """drawmbd when a part or assembly window is active (the 3D, MBD versions of the commands)."""
    try:
        from . import drawmbd
    except Exception:
        return None
    return drawmbd if drawmbd.model_doc() is not None else None

class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        model = _model3d()
        if model is not None:
            return model.active(self.name)     # in a part or assembly: the 3D (MBD) annotation
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        try:
            from . import drawsheet
            if drawsheet.greyed_on_format(page, self.name):
                return False
        except Exception as _fw_err:
            _fw_log("drawannot.py:7463", _fw_err)
        if self.name in ("FreeWorks_DrawNote", "FreeWorks_DrawSurfaceFinish", "FreeWorks_DrawGeometricTolerance",
                         "FreeWorks_DrawWeldSymbol", "FreeWorks_DrawRevisionCloud", "FreeWorks_DrawMultiJogLeader",
                         "FreeWorks_DrawDatumTarget", "FreeWorks_DrawMagneticLine"):
            return True            # these go anywhere on the sheet
        if self.name in ("FreeWorks_DrawLinearNotePattern", "FreeWorks_DrawCircularNotePattern"):
            return any(getattr(v, "SWAnnotation", "") in NOTE_KINDS for v in page.Views)
        return True

    def Activated(self):
        model = _model3d()
        if model is not None:
            model.run(self.name)
            return
        page = D.active_page()
        if page is not None:
            D._show(PANELS[self.name](page))


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
