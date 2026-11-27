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

import html
import math
import os
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import evaluate, paths

V = App.Vector
Qt = QtCore.Qt


def _p():
    return paths.params()


def _hex(rgb):
    return QtGui.QColor.fromRgbF(*rgb[:3]).name()


def _rgb(text, default):
    c = QtGui.QColor(text)
    return (c.redF(), c.greenF(), c.blueF()) if c.isValid() else default


# --------------------------------------------------------------------------- shared: colour settings
class ClassRows(QtWidgets.QGroupBox):
    ""

    changed = QtCore.Signal()

    def __init__(self, key, classes, labels, colours, title="Color Settings", parent=None):
        super().__init__(title, parent)
        self.key = key
        self.setObjectName("SWClassRows" + key)
        grid = QtWidgets.QGridLayout(self)
        self.shown, self.colour, self.count = {}, {}, {}
        for r, k in enumerate(classes):
            box = QtWidgets.QCheckBox(labels[k])
            box.setObjectName("SWShow_%s_%s" % (key, k))
            box.setChecked(_p().GetBool("%sShow_%s" % (key, k), True))
            box.toggled.connect(lambda on, k=k: (_p().SetBool("%sShow_%s" % (self.key, k), on), self.changed.emit()))
            btn = QtWidgets.QPushButton()
            btn.setObjectName("SWColor_%s_%s" % (key, k))
            btn.setFixedWidth(28)
            btn.setToolTip("Edit Color")
            self.colour[k] = _rgb(_p().GetString("%sColor_%s" % (key, k), ""), colours[k])
            btn.clicked.connect(lambda _c=False, k=k: self.edit(k))
            n = QtWidgets.QLabel("")
            grid.addWidget(box, r, 0)
            grid.addWidget(btn, r, 1)
            grid.addWidget(n, r, 2)
            self.shown[k], self.count[k] = box, n
            self._paint_button(k, btn)
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(4)
        self.buttons = {k: grid.itemAtPosition(r, 1).widget() for r, k in enumerate(classes)}

    def _paint_button(self, k, btn):
        btn.setStyleSheet("background:%s" % _hex(self.colour[k]))

    def edit(self, k, colour=None):
        if colour is None:
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(_hex(self.colour[k])), self, "Edit Color")
            if not c.isValid():
                return
            colour = (c.redF(), c.greenF(), c.blueF())
        self.colour[k] = tuple(colour)
        _p().SetString("%sColor_%s" % (self.key, k), _hex(colour))
        self._paint_button(k, self.buttons[k])
        self.changed.emit()

    def face_colour(self, k, grey=(0.8, 0.8, 0.8)):
        return self.colour[k] if self.shown[k].isChecked() else grey

    def set_counts(self, counts):
        for k, n in self.count.items():
            c = counts.get(k, 0)
            n.setText("%d face%s" % (c, "" if c == 1 else "s"))


def _save_report(title, rows, summary=""):
    """A results page in the reports folder (the one Compare's Report Manager lists)."""
    try:
        from . import compare
        folder = compare.reports_folder()
    except Exception:
        folder = os.path.join(App.getUserAppDataDir(), "FreeWorks", "Reports")
    os.makedirs(folder, exist_ok=True)
    doc = App.ActiveDocument
    name = "%s-%s-%s.html" % (title.replace(" ", ""), doc.Label if doc else "", time.strftime("%Y%m%d-%H%M%S"))
    path = os.path.join(folder, name)
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in r) for r in rows)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<html><head><meta charset='utf-8'><title>%s</title></head><body><h1>%s</h1><p>%s</p>"
                "<table border=1 cellpadding=4>%s</table><p>%s</p></body></html>"
                % (title, title, doc.Label if doc else "", body, summary))
    return path


def _table_rows(win):
    t = win.table
    return [[t.topLevelItem(i).text(j) for j in range(t.columnCount())] for i in range(t.topLevelItemCount())]


# --------------------------------------------------------------------------- Check (Check Entity)
def min_radius(shape):
    """The smallest radius of curvature on the shape's faces and edges, with its entity, or (None, '')."""
    best, where = None, ""

    def take(r, ent):
        nonlocal best, where
        if r is not None and r > 1e-9 and (best is None or r < best):
            best, where = r, ent
    for i, f in enumerate(shape.Faces):
        s = f.Surface
        kind = type(s).__name__
        if kind in ("Cylinder", "Sphere"):
            take(s.Radius, "Face%d" % (i + 1))
        elif kind == "Toroid":
            take(s.MinorRadius, "Face%d" % (i + 1))
        elif kind in ("BSplineSurface", "BezierSurface", "SurfaceOfRevolution", "SurfaceOfExtrusion"):
            u0, u1, v0, v1 = f.ParameterRange
            for a in range(4):
                for b in range(4):
                    try:
                        k1, k2 = f.curvatureAt(u0 + (u1 - u0) * (a + .5) / 4, v0 + (v1 - v0) * (b + .5) / 4)
                        k = max(abs(k1), abs(k2))
                        if k > 1e-9:
                            take(1.0 / k, "Face%d" % (i + 1))
                    except Exception as _fw_err:
                        _fw_log("evalpm.py:169", _fw_err)
    for i, e in enumerate(shape.Edges):
        if type(getattr(e, "Curve", None)).__name__ == "Circle":
            take(e.Curve.Radius, "Edge%d" % (i + 1))
    return best, where


def check_entity(objs, strict=False, faces=True, edges=True, short=True, short_len=0.01,
                 radius=True, edge_gap=True, vertex_gap=True, only=None):
    """[(problem, object, entity, value)] and {"min radius": .., "edge gap": .., "vertex gap": ..}.
    only: {object name: set of sub names} to look at (Selected items)."""
    found = []
    info = {}
    for obj in objs:
        shape = obj.Shape
        pick = (only or {}).get(obj.Name)
        try:
            if strict:
                shape.check(True)
            elif not shape.isValid():
                found.append(("Invalid solid", obj, "", "the shape is not valid"))
        except Exception as error:
            found.append(("Invalid solid", obj, "", str(error).strip().split("\n")[0][:120]))
        if faces:
            for i, f in enumerate(shape.Faces):
                n = "Face%d" % (i + 1)
                if (pick is None or n in pick) and not f.isValid():
                    found.append(("Invalid face", obj, n, ""))
        if edges or short:
            for i, e in enumerate(shape.Edges):
                n = "Edge%d" % (i + 1)
                if pick is not None and n not in pick:
                    continue
                if edges and not e.isValid():
                    found.append(("Invalid edge", obj, n, ""))
                if short and e.Length < short_len:
                    found.append(("Short edge", obj, n, evaluate.len_text(e.Length, fmt="%.6f")))
        if radius:
            r, ent = min_radius(shape)
            if r is not None and (info.get("min radius") is None or r < info["min radius"][0]):
                info["min radius"] = (r, obj, ent)
        if edge_gap and shape.Edges:
            i, e = max(enumerate(shape.Edges), key=lambda x: x[1].Tolerance)
            if info.get("edge gap") is None or e.Tolerance > info["edge gap"][0]:
                info["edge gap"] = (e.Tolerance, obj, "Edge%d" % (i + 1))
        if vertex_gap and shape.Vertexes:
            i, v = max(enumerate(shape.Vertexes), key=lambda x: x[1].Tolerance)
            if info.get("vertex gap") is None or v.Tolerance > info["vertex gap"][0]:
                info["vertex gap"] = (v.Tolerance, obj, "Vertex%d" % (i + 1))
    return found, info


INFO_ROWS = (("min radius", "Minimum radius"), ("edge gap", "Maximum edge gap"), ("vertex gap", "Maximum vertex gap"))


class CheckEntityWindow(evaluate.ReportWindow):
    ""

    def __init__(self):
        super().__init__("Check Entity", ["Problem", "Body", "Entity", "Value"])
        self.setObjectName("SWCheckEntity")
        self.recalc.setText("Check")
        top = QtWidgets.QHBoxLayout()
        check = QtWidgets.QGroupBox("Check")
        cl = QtWidgets.QVBoxLayout(check)
        self.strict = QtWidgets.QCheckBox("Strict check")
        self.all = QtWidgets.QRadioButton("All")
        self.selected = QtWidgets.QRadioButton("Selected items")
        self.feature = QtWidgets.QRadioButton("Feature")
        (self.selected if Gui.Selection.getSelection() else self.all).setChecked(True)
        for w in (self.strict, self.all, self.selected, self.feature):
            cl.addWidget(w)
        top.addWidget(check)
        look = QtWidgets.QGroupBox("Look for")
        ll = QtWidgets.QGridLayout(look)
        self.faces = QtWidgets.QCheckBox("Invalid face(s)")
        self.edges = QtWidgets.QCheckBox("Invalid edge(s)")
        self.short = QtWidgets.QCheckBox("Short edge(s)")
        self.short_len = QtWidgets.QDoubleSpinBox()
        self.short_len.setDecimals(4)
        self.short_len.setRange(0.0001, 1000)
        self.short_len.setValue(0.01)
        self.short_len.setSuffix(" mm")
        evaluate.unit_spin(self.short_len)
        self.short_len.valueChanged.connect(lambda _v: self.short.setChecked(True))   # the length is for Short edge(s)
        self.radius = QtWidgets.QCheckBox("Minimum radius")
        self.edge_gap = QtWidgets.QCheckBox("Maximum edge gap")
        self.vertex_gap = QtWidgets.QCheckBox("Maximum vertex gap")
        for w in (self.faces, self.edges, self.radius, self.edge_gap, self.vertex_gap):
            w.setChecked(True)
        ll.addWidget(self.faces, 0, 0)
        ll.addWidget(self.edges, 1, 0)
        ll.addWidget(self.short, 2, 0)
        ll.addWidget(self.short_len, 2, 1)
        ll.addWidget(self.radius, 3, 0)
        ll.addWidget(self.edge_gap, 4, 0)
        ll.addWidget(self.vertex_gap, 5, 0)
        top.addWidget(look)
        self.layout_.insertLayout(1, top)
        self.info = {}

        # problems in it (look audit EV-3). Each value still selects its face, edge or vertex.
        values = QtWidgets.QGridLayout()
        values.setObjectName("SWCheckEntityValues")
        self.value_labels = {}
        for r, (key, text) in enumerate(INFO_ROWS):
            values.addWidget(QtWidgets.QLabel(text + ":"), r, 0)
            lab = QtWidgets.QLabel("")
            lab.setObjectName("SWCheckEntity_" + key.replace(" ", "_"))
            lab.setTextInteractionFlags(QtCore.Qt.LinksAccessibleByMouse)
            lab.linkActivated.connect(lambda _l, key=key: self._select_info(key))
            values.addWidget(lab, r, 1)
            self.value_labels[key] = lab
        values.setColumnStretch(2, 1)
        self.layout_.insertLayout(self.layout_.indexOf(self.table) + 1, values)

    def _select_info(self, key):
        """A value's link: selects the face, edge or vertex it was found on."""
        if key not in self.info:
            return
        _v, o, ent = self.info[key]
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(o.Document.Name, o.Name, ent)
        except Exception as _fw_err:
            _fw_log("evalpm.py:check-info", _fw_err)

    def info_lines(self):
        """The values as "Minimum radius: 8 mm (Body, Face7)" lines (for Copy to Clipboard)."""
        out = []
        for key, text in INFO_ROWS:
            if key in self.info:
                v, o, ent = self.info[key]
                out.append("%s: %s (%s, %s)" % (text, evaluate.len_text(v, fmt="%.6g"), o.Label, ent))
        return out

    def _copy(self):
        super()._copy()
        board = QtWidgets.QApplication.clipboard()
        board.setText(board.text() + "\n" + "\n".join(self.info_lines()))

    def targets(self):
        sels = Gui.Selection.getSelectionEx()
        if self.all.isChecked() or not sels:
            return evaluate.visible_bodies(), None
        objs, only = [], {}
        for s in sels:
            o = s.Object
            if self.feature.isChecked() or not s.SubElementNames:
                if getattr(o, "Shape", None) is not None and not o.Shape.isNull():
                    objs.append(o)
                continue
            body = o.getParentGeoFeatureGroup() if hasattr(o, "getParentGeoFeatureGroup") else None
            tgt = body if body is not None and body.isDerivedFrom("PartDesign::Body") else o
            if tgt not in objs:
                objs.append(tgt)
            only.setdefault(tgt.Name, set()).update(s.SubElementNames)
        return objs, (only or None) if not self.feature.isChecked() else None

    def compute(self):
        objs, only = self.targets()
        found, self.info = check_entity(objs, self.strict.isChecked(), self.faces.isChecked(), self.edges.isChecked(),
                                        self.short.isChecked(), evaluate.mm_of(self.short_len), self.radius.isChecked(),
                                        self.edge_gap.isChecked(), self.vertex_gap.isChecked(), only)
        rows = [((k, o.Label, ent, val), [(o.Document.Name, o.Name, ent)]) for k, o, ent, val in found]
        self.set_rows(rows)
        for key, _text in INFO_ROWS:
            lab = self.value_labels.get(key)
            if lab is None:
                continue
            if key in self.info:
                v, o, ent = self.info[key]
                lab.setText('%s  <a href="pick">%s, %s</a>' % (evaluate.len_text(v, fmt="%.6g"), html.escape(o.Label), ent))
            else:
                lab.setText("")
        bad = [f for f in found if f[0].startswith("Invalid")]
        self.summary.setText("%d bodies checked: %s" % (len(objs), "no invalid geometry found." if not bad else
                                                        "%d invalid item(s). Click a row to select it." % len(bad)))
        self.found = found


# --------------------------------------------------------------------------- Section Properties
class SectionWindow(evaluate.SectionPropertiesWindow):
    ""


    def __init__(self):
        super().__init__()
        self.setObjectName("SWSectionProperties")

    def compute(self):
        from . import massprops
        super().compute()
        text = self.text.toPlainText()
        system = massprops.report_system()
        unit, scale, name = massprops.SYSTEMS[system][:3]
        decimals = _p().GetInt("MassDecimals", 2) if _p().GetBool("MassCustomUnits", False) else 2
        if "millimeters" not in text:
            scale = 1.0        # evaluate.section_report already wrote the report's units (units-1120)
        if scale != 1.0 or decimals != 2:
            self.text.setPlainText(_rescale(text, scale, name, decimals))


def _rescale(text, scale, name, decimals):
    """The report in another length unit and decimals: lengths / scale, areas / scale^2, moments / scale^4."""
    import re
    out = []
    power = 1
    for line in text.split("\n"):
        if "square millimeters" in line:
            power = 2
        elif "millimeters ^ 4" in line:
            power = 4
        elif "( millimeters )" in line:
            power = 1
        line2 = line.replace("square millimeters", "square " + name).replace("millimeters ^ 4", name + " ^ 4") \
            .replace("( millimeters )", "( %s )" % name)

        def num(m, p=power):
            v = float(m.group(0)) / (scale ** p)
            return "%.*f" % (decimals, v)
        if "degrees" in line2:
            pass
        elif "=" in line2 and not re.search(r"P\w = ", line2):
            head, _sep, tail = line2.partition("=")
            line2 = head + "=" + re.sub(r"-?\d+\.\d+(e[-+]?\d+)?", num, tail)
        elif "=" in line2:
            line2 = re.sub(r"(P\w = )(-?\d+\.\d+)", lambda m: m.group(1) + num(re.match(r"-?\d+\.\d+", m.group(2))), line2)
        out.append(line2)
    return "\n".join(out)


# --------------------------------------------------------------------------- Geometry Analysis
GEO_KINDS = ("Knife edge", "Knife vertex", "Short edge", "Small face", "Sliver face", "Discontinuous face",
             "Discontinuous edge")


def geometry_problems(objs, ignore=0.0, knife_edges=True, knife_vertices=True, short=True, short_len=0.1,
                      small=True, small_area=0.01, sliver=True, discont_faces=True, discont_edges=True, knife_angle=10.0):
    import Part
    found = []
    for obj in objs:
        shape, doc = obj.Shape, obj.Document.Name
        base = evaluate.geometry_problems([obj], short_len, knife_angle)
        for kind, ent, val, pick, _o in base:
            if kind == "Knife edge" and not knife_edges or kind == "Short edge" and not short or \
                    kind == "Sliver face" and not sliver or kind == "Small face":
                continue
            found.append((kind, obj, ent, val, pick))
        for i, e in enumerate(shape.Edges):
            if ignore and e.Length <= ignore:
                found = [f for f in found if not (f[1] is obj and f[2] == "Edge%d" % (i + 1))]
        for i, f in enumerate(shape.Faces):
            n = "Face%d" % (i + 1)
            if ignore and f.Area <= ignore ** 2:
                found = [x for x in found if not (x[1] is obj and x[2] == n)]
                continue
            if small and f.Area < small_area:
                found.append(("Small face", obj, n, evaluate.len_text(f.Area, 2, 4), (doc, obj.Name, n)))
            if discont_faces:
                try:
                    s = f.Surface
                    if hasattr(s, "Continuity") and s.Continuity in ("C0",):
                        found.append(("Discontinuous face", obj, n, "C0", (doc, obj.Name, n)))
                except Exception as _fw_err:
                    _fw_log("evalpm.py:382", _fw_err)
        if discont_edges:
            for i, e in enumerate(shape.Edges):
                try:
                    c = e.Curve
                    if hasattr(c, "Continuity") and c.Continuity == "C0":
                        found.append(("Discontinuous edge", obj, "Edge%d" % (i + 1), "C0", (doc, obj.Name, "Edge%d" % (i + 1))))
                except Exception as _fw_err:
                    _fw_log("evalpm.py:390", _fw_err)
        if knife_vertices:
            for i, v in enumerate(shape.Vertexes):
                faces = shape.ancestorsOfType(v, Part.Face)
                edges = shape.ancestorsOfType(v, Part.Edge)
                if len(edges) < 2:
                    continue
                # a knife vertex: two of its edges leave it almost along each other (a needle point)
                dirs = []
                for e in edges:
                    try:
                        t = e.parameterAt(v)
                        d = e.tangentAt(t)
                        if (e.valueAt(e.LastParameter) - v.Point).Length < 1e-7:
                            d = d * -1
                        dirs.append(d)
                    except Exception as _fw_err:
                        _fw_log("evalpm.py:407", _fw_err)
                sharp = min((math.degrees(a.getAngle(b)) for k, a in enumerate(dirs) for b in dirs[k + 1:]), default=180.0)
                if sharp < knife_angle and len(faces) >= 1:
                    found.append(("Knife vertex", obj, "Vertex%d" % (i + 1), "%.2f °" % sharp, (doc, obj.Name, "Vertex%d" % (i + 1))))
    return found


class GeometryWindow(evaluate.ReportWindow):
    ""

    def __init__(self):
        super().__init__("Geometry Analysis", ["Problem", "Body", "Entity", "Value"])
        self.setObjectName("SWGeometryAnalysis")
        self.recalc.setText("Calculate")
        box = QtWidgets.QGroupBox("Analysis Parameters")
        g = QtWidgets.QGridLayout(box)

        def spin(value, suffix, lo=0.0, hi=1e4, dec=4):
            s = QtWidgets.QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(dec)
            s.setValue(value)
            s.setSuffix(suffix)
            return s
        self.ignore_on = QtWidgets.QCheckBox("Ignore edges/faces up to this size:")
        self.ignore = spin(0.001, " mm")
        # each value box sits under its check box (look audit AO2: side by side the page asked for a 472 px pane)
        g.addWidget(self.ignore_on, 0, 0)
        g.addWidget(self.ignore, 1, 0)
        for s in (self.ignore,):
            s.setStyleSheet("margin-left:18px")
        self.knife = QtWidgets.QCheckBox("Knife geometry")
        self.knife_edges = QtWidgets.QCheckBox("Knife edges")
        self.knife_vertices = QtWidgets.QCheckBox("Knife vertices")
        self.knife_angle = spin(10.0, " °", 0.1, 90.0, 2)
        self.short = QtWidgets.QCheckBox("Short edges")
        self.short_len = spin(0.1, " mm")
        self.small = QtWidgets.QCheckBox("Small faces")
        self.small_area = spin(0.01, " mm²")
        self.sliver = QtWidgets.QCheckBox("Sliver faces")
        self.discont = QtWidgets.QCheckBox("Discontinuous geometry")
        self.discont_faces = QtWidgets.QCheckBox("Faces")
        self.discont_edges = QtWidgets.QCheckBox("Edges")
        for s, power in ((self.ignore, 1), (self.short_len, 1), (self.small_area, 2)):
            evaluate.unit_spin(s, power)
        rows = [(self.knife, None), (self.knife_edges, self.knife_angle), (self.knife_vertices, None),
                (self.short, self.short_len), (self.small, self.small_area), (self.sliver, None),
                (self.discont, None), (self.discont_faces, None), (self.discont_edges, None)]
        r = 1
        for w, s in rows:
            r += 1
            w.setChecked(True)
            g.addWidget(w, r, 0)
            if w in (self.knife_edges, self.knife_vertices, self.discont_faces, self.discont_edges):
                w.setContentsMargins(18, 0, 0, 0)
                w.setStyleSheet("margin-left:18px")
            if s is not None:
                r += 1
                s.setStyleSheet("margin-left:%dpx" % (36 if w in (self.knife_edges, self.knife_vertices) else 18))
                g.addWidget(s, r, 0)
        # a sub-option stays usable: ticking it ticks its group, unticking the group unticks it (never greyed)
        for parent, subs in ((self.knife, (self.knife_edges, self.knife_vertices)),
                             (self.discont, (self.discont_faces, self.discont_edges))):
            parent.toggled.connect(lambda on, subs=subs: on or [w.setChecked(False) for w in subs])
            for w in subs:
                w.toggled.connect(lambda on, parent=parent: on and parent.setChecked(True))
        self.layout_.insertWidget(0, box)
        row = self.layout_.itemAt(self.layout_.count() - 1).layout()
        self.save = QtWidgets.QPushButton("Save Report")
        self.save.clicked.connect(self.save_report)
        self.reset = QtWidgets.QPushButton("Reset")
        self.reset.clicked.connect(self.reset_all)
        row.insertWidget(2, self.save)
        row.insertWidget(3, self.reset)
        self.found = []
        self.saved = None

    def compute(self):
        objs = evaluate.picked_or_visible()
        k = self.knife.isChecked()
        d = self.discont.isChecked()
        self.found = geometry_problems(objs, evaluate.mm_of(self.ignore) if self.ignore_on.isChecked() else 0.0,
                                       k and self.knife_edges.isChecked(), k and self.knife_vertices.isChecked(),
                                       self.short.isChecked(), evaluate.mm_of(self.short_len), self.small.isChecked(),
                                       evaluate.mm_of(self.small_area), self.sliver.isChecked(),
                                       d and self.discont_faces.isChecked(), d and self.discont_edges.isChecked(),
                                       self.knife_angle.value())
        self.set_rows([((kind, o.Label, ent, val), [pick]) for kind, o, ent, val, pick in self.found])
        counts = {}
        for f in self.found:
            counts[f[0]] = counts.get(f[0], 0) + 1
        self.summary.setText("%d bodies analyzed. " % len(objs) + (", ".join("%s: %d" % kv for kv in counts.items())
                                                                     or "No problem geometry found."))

    def save_report(self):
        self.saved = _save_report("Geometry Analysis", [["Problem", "Body", "Entity", "Value"]] + _table_rows(self),
                                  self.summary.text())
        self.summary.setText(self.summary.text() + "  Report saved: " + self.saved)
        return self.saved

    def reset_all(self):
        self.set_rows([])
        self.found = []
        self.summary.setText("")
        Gui.Selection.clearSelection()


# --------------------------------------------------------------------------- Draft Analysis
DRAFT_CLASSES = ("positive", "requires", "negative", "straddle", "positive_steep", "negative_steep")
DRAFT_LABELS = dict(evaluate.LABELS, positive_steep="Positive steep faces", negative_steep="Negative steep faces")
DRAFT_COLOURS = dict(evaluate.COLOURS, positive_steep=(0.55, 0.95, 0.55), negative_steep=(1.0, 0.55, 0.55))


def classify_draft(face, pull, angle, steep=False):
    a = evaluate._face_angles(face, pull)
    k = evaluate.classify_draft(face, pull, angle)
    if steep and k == "straddle":
        if min(a) >= -1e-6:
            return "positive_steep"
        if max(a) <= 1e-6:
            return "negative_steep"
    return k


def gradual(angle, limit):
    """Gradual transition: the colour runs from the negative draft colour through the requires draft
    colour (at 0) to the positive draft colour, reaching them at three times the draft angle."""
    t = max(-1.0, min(1.0, angle / max(3.0 * limit, 1e-6)))
    mid, pos, neg = evaluate.REQUIRES, evaluate.POSITIVE, evaluate.NEGATIVE
    end = pos if t >= 0 else neg
    t = abs(t)
    return tuple(mid[k] + (end[k] - mid[k]) * t for k in range(3))


class DraftWindow(evaluate.DraftAnalysisWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("SWDraftAnalysis")
        extra = QtWidgets.QHBoxLayout()
        self.classify = QtWidgets.QCheckBox("Face classification")
        self.classify.setChecked(True)
        self.steep = QtWidgets.QCheckBox("Find steep faces")
        self.gradual = QtWidgets.QCheckBox("Gradual transition")
        for w in (self.classify, self.steep, self.gradual):
            extra.addWidget(w)
            w.toggled.connect(self.refresh)
        extra.addStretch(1)
        self.layout_.insertLayout(1, extra)
        self.classes = ClassRows("Draft", DRAFT_CLASSES, DRAFT_LABELS, DRAFT_COLOURS)
        self.classes.changed.connect(self.refresh)
        self.layout_.insertWidget(2, self.classes)
        self.classify.toggled.connect(lambda on: self.gradual.setVisible(not on))   # a choice only without classes
        self.gradual.setVisible(False)

    def compute(self):
        pull, name = evaluate._pull_from_selection()
        if pull is not None:
            self.pull = pull
            self.direction.setText(name)
        pull = self.pull * (-1.0 if self.reverse.isChecked() else 1.0)
        self.colours.restore()
        angle = self.angle.value()
        counts = dict.fromkeys(DRAFT_CLASSES, 0)
        steep = self.steep.isChecked()
        for obj in evaluate.visible_bodies():
            cols = []
            for f in obj.Shape.Faces:
                k = classify_draft(f, pull, angle, steep)
                counts[k] += 1
                if not self.classify.isChecked() and self.gradual.isChecked():
                    a = evaluate._face_angles(f, pull)
                    cols.append(gradual(sum(a) / len(a), angle))
                else:
                    cols.append(self.classes.face_colour(k))
            self.colours.paint(obj, cols)
        self.counts = counts
        self.classes.set_counts(counts)
        for k in ("positive_steep", "negative_steep"):
            self.classes.shown[k].setVisible(steep)
            self.classes.buttons[k].setVisible(steep)
            self.classes.count[k].setVisible(steep)
        self.set_rows([((DRAFT_LABELS[k], counts[k]), []) for k in DRAFT_CLASSES if steep or "steep" not in k])
        if getattr(self, "direction_name", None) or pull_name_set(self):
            need = counts.get("requires", 0)
            self.summary.setText("Direction of pull: %s%s. %s" % (
                self.direction.text(), " (reversed)" if self.reverse.isChecked() else "",
                "Every face has the draft angle." if not need else
                "%d face%s need%s draft." % (need, "" if need == 1 else "s", "s" if need == 1 else "")))
        else:
            self.summary.setText("Pick a planar face or a straight edge, then Calculate, to set the direction of pull.")


def pull_name_set(win):
    """A direction of pull was picked (the window starts on the Z axis until a pick)."""
    return win.direction.text() not in ("", "Z axis")


# --------------------------------------------------------------------------- Parting Line Analysis
PARTING_CLASSES = ("positive", "negative", "requires", "straddle", "line")
PARTING_LABELS = dict(evaluate.LABELS, requires="Draft required", straddle="Straddle faces", line="Parting line")


def _parting_window():
    from . import partingline
    colours = dict(evaluate.COLOURS, line=partingline.LINE)

    class PartingWin(partingline.PartingLineWindow):
        ""


        def __init__(self):
            super().__init__()
            self.setObjectName("SWPartingLineAnalysis")
            self.classes = ClassRows("Parting", PARTING_CLASSES, PARTING_LABELS, colours)
            self.classes.changed.connect(self.refresh)
            self.layout_.insertWidget(1, self.classes)

        def compute(self):
            pull, name = evaluate._pull_from_selection()
            if pull is not None:
                self.pull = pull
                self.direction.setText(name)
            pull = self.pull * (-1.0 if self.reverse.isChecked() else 1.0)
            self.colours.restore()
            self.lines.clear()
            counts = dict.fromkeys(PARTING_CLASSES, 0)
            self.found, rows_line, edges = {}, [], []
            doc = App.ActiveDocument.Name if App.ActiveDocument else ""
            for obj in evaluate.visible_bodies():
                kinds, line = partingline.analyse(obj.Shape, pull, self.angle.value())
                self.found[obj.Name] = (kinds, line)
                for k in kinds:
                    counts[k] += 1
                self.colours.paint(obj, [self.classes.face_colour(k) for k in kinds])
                edges += [obj.Shape.Edges[k] for k in line]
                rows_line += [(doc, obj.Name, "Edge%d" % (k + 1)) for k in line]
            counts["line"] = len(rows_line)
            self.counts = counts
            self.classes.set_counts(counts)
            self.classes.count["line"].setText("%d edges" % counts["line"])
            if self.classes.shown["line"].isChecked():
                partingline.LINE = self.classes.colour["line"]
                self.lines.add(edges)
            rows = [((PARTING_LABELS[k], counts[k]), []) for k in PARTING_CLASSES[:4]]
            rows.append((("Parting line edges", len(rows_line)), rows_line))
            self.set_rows(rows)
            self.summary.setText("The bright line is the possible parting line. Pick a planar face or a straight "
                                 "edge, then Calculate, to set the direction of pull.")
    return PartingWin


# --------------------------------------------------------------------------- Undercut Analysis
def _parting_plane():
    """The plane of the picked edges (a parting line): (point, normal), else None."""
    import Part
    edges = [shp for s in Gui.Selection.getSelectionEx() for n, shp in zip(s.SubElementNames, s.SubObjects)
             if n.startswith("Edge")]
    if not edges:
        return None
    try:
        pl = Part.Compound(edges).findPlane()
        if pl is None:
            return None
        return Part.Compound(edges).CenterOfMass if hasattr(Part.Compound(edges), "CenterOfMass") else \
            edges[0].Vertexes[0].Point, pl.Axis
    except Exception:
        return None


def _undercut_window():
    from . import undercut

    class UndercutWin(undercut.UndercutWindow):
        def __init__(self):
            super().__init__()
            self.setObjectName("SWUndercutAnalysis")
            mode = QtWidgets.QHBoxLayout()
            self.by_dir = QtWidgets.QRadioButton("Direction of pull")
            self.by_line = QtWidgets.QRadioButton("Parting line")
            self.by_dir.setChecked(True)
            mode.addWidget(self.by_dir)
            mode.addWidget(self.by_line)
            mode.addStretch(1)
            self.layout_.insertLayout(0, mode)
            self.by_line.toggled.connect(self.refresh)
            self.classes = ClassRows("Undercut", undercut.CLASSES, undercut.LABELS, undercut.COLOURS, "Undercut Faces")
            self.classes.changed.connect(self.repaint_faces)
            self.layout_.insertWidget(2, self.classes)
            self.parting = None

        def compute(self):
            if self.by_line.isChecked():
                plane = _parting_plane()
                if plane is not None:
                    self.parting = plane
                if self.parting is None:
                    self.summary.setText("Pick the edges of the parting line, then Calculate.")
                    return
                base, normal = self.parting
                self.pull = normal
                self.direction.setText("Parting line")
                pull = normal * (-1.0 if self.reverse.isChecked() else 1.0)
                self.colours.restore()
                counts = dict.fromkeys(undercut.CLASSES, 0)
                self.kinds = {}
                for obj in evaluate.visible_bodies():
                    kinds = []
                    for f in obj.Shape.Faces:
                        # above the parting line the face is judged against direction 1, below against direction 2
                        side = (f.CenterOfMass - base).dot(pull)
                        k = undercut.classify(obj.Shape.Solids[0] if obj.Shape.Solids else obj.Shape, f,
                                              pull if side >= 0 else pull * -1.0)
                        if side < 0 and k == "dir1":
                            k = "dir2"
                        kinds.append(k)
                    self.kinds[obj.Name] = kinds
                    for k in kinds:
                        counts[k] += 1
                self.counts = counts
                self.set_rows([((undercut.LABELS[k], counts[k]), []) for k in undercut.CLASSES])
            else:
                super().compute()
            self.repaint_faces()

        def repaint_faces(self):
            self.colours.restore()
            for name, kinds in self.kinds.items():
                obj = App.ActiveDocument.getObject(name) if App.ActiveDocument else None
                if obj is not None:
                    self.colours.paint(obj, [self.classes.face_colour(k) for k in kinds])
            self.classes.set_counts(self.counts)
    return UndercutWin


# --------------------------------------------------------------------------- Thickness Analysis
def _thickness_targets():
    """The bodies in the selection (the PM's Faces or Bodies box puts them there), else every visible body."""
    out = []
    for sel in Gui.Selection.getSelectionEx():
        obj = sel.Object
        body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        top = body if body is not None and body.isDerivedFrom("PartDesign::Body") else obj
        try:
            if top not in out and top.Shape.Solids:
                out.append(top)
        except Exception:
            continue
    return out or evaluate.visible_bodies()


RESOLUTION = {"Low": 3, "Medium": 5, "High": 8}


def _concave_faces(shape):
    """Faces meeting another face at an inside corner (a concave edge)."""
    import Part
    out = set()
    for e in shape.Edges:
        faces = shape.ancestorsOfType(e, Part.Face)
        if len(faces) != 2:
            continue
        try:
            p = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            n1 = faces[0].normalAt(*faces[0].Surface.parameter(p))
            n2 = faces[1].normalAt(*faces[1].Surface.parameter(p))
            c1 = faces[0].CenterOfMass - p
            if n2.dot(c1) > 1e-6 and abs(n1.dot(n2)) < 0.999:
                for f in faces:
                    out.add(next(i for i, g in enumerate(shape.Faces) if g.isSame(f)))
        except Exception:
            continue
    return out


def _thickness_window():
    from . import thickness

    class ThicknessWin(thickness.ThicknessWindow):
        def __init__(self):
            super().__init__()
            self.setObjectName("SWThicknessAnalysis")
            box = QtWidgets.QGroupBox("Analysis Parameters")
            g = QtWidgets.QGridLayout(box)
            g.addWidget(QtWidgets.QLabel("Thick region limit:"), 0, 0)
            self.limit = QtWidgets.QDoubleSpinBox()
            self.limit.setObjectName("SWThickLimit")
            self.limit.setRange(0.001, 1e6)
            self.limit.setDecimals(3)
            self.limit.setSuffix(" mm")
            self.limit.setValue(10.0)
            evaluate.unit_spin(self.limit)
            g.addWidget(self.limit, 0, 1)
            g.addWidget(QtWidgets.QLabel("Resolution:"), 1, 0)
            self.resolution = QtWidgets.QComboBox()
            self.resolution.setObjectName("SWThicknessResolution")
            self.resolution.addItems(list(RESOLUTION))
            self.resolution.setCurrentText("Medium")
            g.addWidget(self.resolution, 1, 1)
            self.corners = QtWidgets.QCheckBox("Treat corners as zero thickness")
            g.addWidget(self.corners, 2, 0, 1, 2)
            self.layout_.insertWidget(1, box)
            col = QtWidgets.QGroupBox("Color Settings")
            c = QtWidgets.QGridLayout(col)
            self.full = QtWidgets.QCheckBox("Full color range")
            self.continuous = QtWidgets.QRadioButton("Continuous")
            self.discrete = QtWidgets.QRadioButton("Discrete")
            self.continuous.setChecked(True)
            self.ncolours = QtWidgets.QSpinBox()
            self.ncolours.setRange(2, 16)
            self.ncolours.setValue(6)
            self.ncolours.setPrefix("Number of colors: ")
            c.addWidget(self.full, 0, 0, 1, 2)
            c.addWidget(self.continuous, 1, 0)
            c.addWidget(self.discrete, 1, 1)
            c.addWidget(self.ncolours, 2, 0, 1, 2)
            self.layout_.insertWidget(2, col)
            for w in (self.full, self.continuous, self.discrete):
                w.toggled.connect(self._paint)
            self.ncolours.valueChanged.connect(self._paint)
            self.limit.valueChanged.connect(self._paint)
            row = self.layout_.itemAt(self.layout_.count() - 1).layout()
            self.save = QtWidgets.QPushButton("Save Report")
            self.save.clicked.connect(self.save_report)
            row.insertWidget(2, self.save)
            self.ranges = []

        def compute(self):
            old = thickness.SAMPLES
            thickness.SAMPLES = RESOLUTION[self.resolution.currentText()]
            try:
                self.walls = {}
                for obj in _thickness_targets():
                    rows = thickness.analyse(obj.Shape, self.corners.isChecked())
                    if self.corners.isChecked():
                        zero = _concave_faces(obj.Shape)
                        rows = [(i, 0.0 if i in zero else t, a) for i, t, a in rows]
                    self.walls[obj.Name] = (obj, rows)
            finally:
                thickness.SAMPLES = old
            self._paint()

        def _colour(self, t, target, low, high, thin):
            if t is None:
                return thickness.GREY
            if not thin:
                high = min(high, evaluate.mm_of(self.limit))
            if self.full.isChecked():
                lo, hi = low, high
                frac = (t - lo) / (hi - lo) if hi > lo else 0.0
            else:
                if thin and t >= target or not thin and t <= target:
                    return thickness.GREY
                lo, hi = (low, target) if thin else (target, high)
                frac = (t - lo) / (hi - lo) if hi > lo else 0.0
            frac = max(0.0, min(1.0, frac))
            if self.discrete.isChecked():
                n = self.ncolours.value()
                frac = min(n - 1, int(frac * n)) / float(n - 1)
            if thin or self.full.isChecked():
                return thickness._blend((1.0, 0.0, 0.0), (0.0, 0.3, 1.0), frac) if self.full.isChecked() else \
                    thickness._blend((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), frac)
            return thickness._blend((1.0, 1.0, 0.0), (0.0, 0.3, 1.0), frac)

        def _paint(self, *args):
            super()._paint()
            if not self.walls:
                return
            target = evaluate.mm_of(self.target)
            found = [t for _o, rows in self.walls.values() for _i, t, _a in rows if t is not None]
            if not found:
                return
            low, high = min(found), max(found)
            thin = self.thin.isChecked()
            self.colours.restore()
            for _name, (obj, rows) in self.walls.items():
                self.colours.paint(obj, [self._colour(t, target, low, high, thin) for _i, t, _a in rows])

            n = self.ncolours.value() if high - low > 1e-9 else 1     # one wall thickness: one band, not n equal rows
            total = sum(a for _o, rows in self.walls.values() for _i, _t, a in rows) or 1.0
            edges = [low + (high - low) * k / n for k in range(n + 1)]
            self.ranges = []
            for k in range(n):
                a = sum(ar for _o, rows in self.walls.values() for _i, t, ar in rows
                        if t is not None and (edges[k] <= t < edges[k + 1] or k == n - 1 and t == edges[-1]))
                self.ranges.append(("%s - %s" % (("%.4f" if evaluate.doc_unit()[1] > 1 else "%.3f") % evaluate.in_doc(edges[k]),
                                                 evaluate.len_text(edges[k + 1])), 100.0 * a / total))
            rows = [((r, "%.1f %%" % s), []) for r, s in self.ranges]
            base = [((self.table.topLevelItem(i).text(0), self.table.topLevelItem(i).text(1)), self.rows[i] if i < len(self.rows) else [])
                    for i in range(self.table.topLevelItemCount())]
            self.set_rows(base + rows)

        def save_report(self):
            path = _save_report("Thickness Analysis", [["Result", "Value"]] + _table_rows(self), self.summary.text())
            self.summary.setText("Report saved: " + path)
            return path
    return ThicknessWin


# --------------------------------------------------------------------------- Deviation Analysis
def _deviation_window():
    from . import evaluate2

    class DeviationWin(evaluate2.DeviationWindow):
        def __init__(self):
            super().__init__()
            self.setObjectName("SWDeviationAnalysis")
            self.recalc.setText("Check")
            self.overlay_nodes = []
            self.info = QtWidgets.QLabel("")
            self.info.setObjectName("SWDeviationInfo")
            self.layout_.insertWidget(self.layout_.count() - 2, self.info)

        def compute(self):
            super().compute()
            self._draw()

        def _draw(self):
            from pivy import coin
            self.cleanup()
            view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
            if view is None:
                return
            vals = []
            sep = coin.SoAnnotation()
            for obj, sub in self.picks:
                for p, a in evaluate2.edge_deviation(obj.Shape, obj.Shape.getElement(sub), self.samples.value()):
                    vals.append(a)
                    s = coin.SoSeparator()
                    col = coin.SoBaseColor()
                    # green: tangent (under 0.1 deg), yellow under 1 deg, red above
                    col.rgb = (0.0, 0.7, 0.0) if a < 0.1 else (1.0, 0.8, 0.0) if a < 1.0 else (0.9, 0.0, 0.0)
                    t = coin.SoTranslation()
                    t.translation = (p.x, p.y, p.z)
                    st = coin.SoDrawStyle()
                    st.pointSize = 7
                    pt = coin.SoCoordinate3()
                    pt.point.setValue(0, 0, 0)
                    s.addChild(col)
                    s.addChild(t)
                    s.addChild(st)
                    s.addChild(pt)
                    s.addChild(coin.SoPointSet())
                    sep.addChild(s)
            view.getSceneGraph().addChild(sep)
            self.overlay_nodes.append((view, sep))
            if vals:
                self.info.setText("Maximum deviation: %.4f deg   Minimum deviation: %.4f deg   Average deviation: %.4f deg"
                                  % (max(vals), min(vals), sum(vals) / len(vals)))
            self.values = vals

        def cleanup(self):
            for view, sep in self.overlay_nodes:
                try:
                    view.getSceneGraph().removeChild(sep)
                except Exception as _fw_err:
                    _fw_log("evalpm.py:920", _fw_err)
            self.overlay_nodes = []
    return DeviationWin


# --------------------------------------------------------------------------- Symmetry Check
SYM_CLASSES = ("symmetric", "asymmetric", "unique")
SYM_LABELS = {"symmetric": "Symmetric faces", "asymmetric": "Asymmetric faces", "unique": "Unique faces"}
SYM_COLOURS = {"symmetric": evaluate.SYMMETRIC, "asymmetric": evaluate.ASYMMETRIC, "unique": (0.25, 0.4, 1.0)}


def symmetry_classes(shape, base, normal, tol=1e-3):
    """Each face: symmetric (its mirror image is a face of the part), asymmetric (a face of the same kind
    and size sits near its mirror place, but not on it) or unique (nothing like it on the other side)."""
    mirrored = shape.mirror(base, normal)
    exact = evaluate.symmetric_faces(shape, base, normal, tol)
    diag = shape.BoundBox.DiagonalLength
    keys = [(type(f.Surface).__name__, f.Area, f.CenterOfMass) for f in mirrored.Faces]
    out = []
    for f, ok in zip(shape.Faces, exact):
        if ok:
            out.append("symmetric")
            continue
        kind, c = type(f.Surface).__name__, f.CenterOfMass
        near = any(k == kind and (c - kc).Length < 0.25 * diag and abs(a - f.Area) < 0.5 * max(a, f.Area)
                   for k, a, kc in keys)
        out.append("asymmetric" if near else "unique")
    return out


class SymmetryWin(evaluate.SymmetryWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("SWSymmetryCheck")
        self.bodies = QtWidgets.QLabel("Bodies: all visible")
        self.layout_.insertWidget(1, self.bodies)
        self.rows_box = ClassRows("Symmetry", SYM_CLASSES, SYM_LABELS, SYM_COLOURS, "Results")
        self.rows_box.changed.connect(self.repaint_faces)
        self.layout_.insertWidget(2, self.rows_box)
        self.kinds = {}

    def compute(self):
        self.colours.restore()
        pick = evaluate._plane_from_selection()
        if pick is not None:
            self.plane.blockSignals(True)
            self.plane.setCurrentIndex(3)
            self.plane.blockSignals(False)
        i = self.plane.currentIndex()
        if i == 3 and pick is None:
            self.summary.setText("Select a plane or a planar face, then press Check.")
            return
        base, normal, name = pick if i == 3 else (V(), [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)][i], self.plane.currentText())
        objs = [o for o in evaluate.picked_or_visible()]
        self.bodies.setText("Bodies: " + ", ".join(o.Label for o in objs))
        counts = dict.fromkeys(SYM_CLASSES, 0)
        self.kinds = {}
        for obj in objs:
            kinds = symmetry_classes(obj.Shape, base, normal)
            self.kinds[obj.Name] = kinds
            for k in kinds:
                counts[k] += 1
        self.counts = counts
        self.set_rows([((SYM_LABELS[k], counts[k]), []) for k in SYM_CLASSES])
        self.summary.setText("About %s." % name)
        self.repaint_faces()

    def repaint_faces(self):
        self.colours.restore()
        for n, kinds in self.kinds.items():
            obj = App.ActiveDocument.getObject(n) if App.ActiveDocument else None
            if obj is not None:
                self.colours.paint(obj, [self.rows_box.face_colour(k) for k in kinds])
        self.rows_box.set_counts(getattr(self, "counts", {}))


# --------------------------------------------------------------------------- Zebra Stripes
ZEBRA_DEFAULTS = {"stripes": 8, "width": 50, "precision": 3, "vertical": False, "spherical": False,
                  "stripe": "#000000", "background": "#ffffff"}


def zebra_settings():
    p = _p()
    return {"stripes": p.GetInt("ZebraStripes", 8), "width": p.GetInt("ZebraWidth", 50),
            "precision": p.GetInt("ZebraPrecision", 3), "vertical": p.GetBool("ZebraVertical", False),
            "spherical": p.GetBool("ZebraSpherical", False),
            "stripe": p.GetString("ZebraStripeColor", "#000000") or "#000000",
            "background": p.GetString("ZebraBackground", "#ffffff") or "#ffffff"}


def _zebra_ray():
    from . import evaluate2
    return evaluate2._Zebra.RAY


ZEBRA_FRAG = """
varying vec3 N;
varying vec3 P;
uniform float stripes;
uniform float width;
uniform float vertical;
uniform float spherical;
uniform vec3 stripeColor;
uniform vec3 backColor;
""" + _zebra_ray() + """
void main() {
    vec3 n = normalize(N);
    if (!gl_FrontFacing) n = -n;
    vec3 r = zebra_ray(P, n);
    float c = (vertical > 0.5 ? atan(r.x, -r.z) : atan(r.y, -r.z)) / 3.14159265;
    if (spherical > 0.5) c = acos(clamp(r.z, -1.0, 1.0)) / 3.14159265;
    float t = fract(c * stripes * 0.5 + 0.5);
    float w = fwidth(t) * 1.5;
    float edge = clamp(width, 0.05, 0.95);
    float band = smoothstep(edge - w, edge + w, t) - smoothstep(1.0 - w, 1.0, t);
    gl_FragColor = vec4(mix(stripeColor, backColor, band), 1.0);
}
"""


def apply_zebra(z=None):
    """Use the settings in the zebra shader (evaluate2.ZEBRA) and redraw it when it is on."""
    from . import evaluate2
    z = z or evaluate2.ZEBRA
    s = zebra_settings()
    z.stripes = s["stripes"]
    z.settings = s

    def shader(self=z):
        from pivy import coin
        prog = coin.SoShaderProgram()
        vs = coin.SoVertexShader()
        vs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        vs.sourceProgram.setValue(evaluate2._Zebra._VERT)
        fs = coin.SoFragmentShader()
        fs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        fs.sourceProgram.setValue(ZEBRA_FRAG)
        st = self.settings
        vals = (("stripes", float(st["stripes"])), ("width", st["width"] / 100.0),
                ("vertical", 1.0 if st["vertical"] else 0.0), ("spherical", 1.0 if st["spherical"] else 0.0))
        k = 0
        for name, v in vals:
            par = coin.SoShaderParameter1f()
            par.name.setValue(name)
            par.value.setValue(v)
            fs.parameter.set1Value(k, par)
            k += 1
        for par in self.ray_parameters():
            fs.parameter.set1Value(k, par)
            k += 1
        for name, hexc in (("stripeColor", st["stripe"]), ("backColor", st["background"])):
            c = QtGui.QColor(hexc)
            par = coin.SoShaderParameter3f()
            par.name.setValue(name)
            par.value.setValue(c.redF(), c.greenF(), c.blueF())
            fs.parameter.set1Value(k, par)
            k += 1
        prog.shaderObject.set1Value(0, vs)
        prog.shaderObject.set1Value(1, fs)
        return prog
    z._shader = shader
    if z.on:
        z.show()
    return s


class ZebraPM(QtWidgets.QDialog):
    ""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("SWZebraStripes")
        self.setWindowTitle("Zebra Stripes")
        s = zebra_settings()
        lay = QtWidgets.QFormLayout(self)

        def slider(lo, hi, v):
            w = QtWidgets.QSlider(Qt.Horizontal)
            w.setRange(lo, hi)
            w.setValue(v)
            w.valueChanged.connect(self.apply)
            return w
        self.stripes = slider(2, 40, s["stripes"])
        self.width = slider(10, 90, s["width"])
        self.precision = slider(1, 5, s["precision"])
        lay.addRow("Number of stripes:", self.stripes)
        lay.addRow("Stripe width:", self.width)
        lay.addRow("Precision:", self.precision)
        self.horizontal = QtWidgets.QRadioButton("Horizontal stripes")
        self.vertical = QtWidgets.QRadioButton("Vertical stripes")
        (self.vertical if s["vertical"] else self.horizontal).setChecked(True)
        self.vertical.toggled.connect(self.apply)
        lay.addRow(self.horizontal)
        lay.addRow(self.vertical)
        self.spherical = QtWidgets.QCheckBox("Spherical map")
        self.spherical.setChecked(s["spherical"])
        self.spherical.toggled.connect(self.apply)
        lay.addRow(self.spherical)
        self.colors = {}
        for key, label in (("stripe", "Stripe color"), ("background", "Background color")):
            b = QtWidgets.QPushButton("Edit Color...")
            b.setStyleSheet("background:%s" % s[key])
            b.clicked.connect(lambda _c=False, k=key: self.edit(k))
            self.colors[key] = (b, s[key])
            lay.addRow(label + ":", b)
        ok = QtWidgets.QPushButton("OK")
        ok.clicked.connect(self.close)
        lay.addRow(ok)

    def edit(self, key, colour=None):
        b, cur = self.colors[key]
        if colour is None:
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor(cur), self, "Edit Color")
            if not c.isValid():
                return
            colour = c.name()
        b.setStyleSheet("background:%s" % colour)
        self.colors[key] = (b, colour)
        self.apply()

    def apply(self, *args):
        p = _p()
        p.SetInt("ZebraStripes", self.stripes.value())
        p.SetInt("ZebraWidth", self.width.value())
        p.SetInt("ZebraPrecision", self.precision.value())
        p.SetBool("ZebraVertical", self.vertical.isChecked())
        p.SetBool("ZebraSpherical", self.spherical.isChecked())
        p.SetString("ZebraStripeColor", self.colors["stripe"][1])
        p.SetString("ZebraBackground", self.colors["background"][1])
        return apply_zebra()


_ZEBRA_PM = []


def zebra_stripes():
    """The command: stripes on with their PropertyManager, or off."""
    from . import evaluate2
    z = evaluate2.ZEBRA
    if z.on:
        z.hide()
        for pm in _ZEBRA_PM:
            try:
                pm.close()
            except Exception as _fw_err:
                _fw_log("evalpm.py:1156", _fw_err)
        _ZEBRA_PM[:] = []
        return None
    apply_zebra(z)
    _tessellation(z)
    z.show()
    if not getattr(evaluate2._ZebraRedraw, "added", False):
        App.addDocumentObserver(evaluate2._ZebraRedraw())
        evaluate2._ZebraRedraw.added = True
    pm = ZebraPM()
    _ZEBRA_PM[:] = [pm]
    pm.show()
    return pm


def _tessellation(z):
    """Precision: finer tessellation for the stripes (1 coarse .. 5 fine)."""
    prec = zebra_settings()["precision"]
    z.deflection = {1: 0.4, 2: 0.2, 3: 0.1, 4: 0.05, 5: 0.02}.get(prec, 0.1)


# --------------------------------------------------------------------------- install
def install():
    """Give the tools these boxes (their commands are evaluate's and evaluate2's)."""
    from . import evaluate2, undercut, thickness  # noqa: F401  (their commands are made on import)
    evaluate.COMMANDS["SWStyle_Check"] = (evaluate.COMMANDS["SWStyle_Check"][0], evaluate.COMMANDS["SWStyle_Check"][1],
                                          lambda: evaluate._show(CheckEntityWindow))
    for name, cls in (("SWStyle_SectionProperties", SectionWindow), ("SWStyle_GeometryAnalysis", GeometryWindow),
                      ("SWStyle_DraftAnalysis", DraftWindow), ("SWStyle_SymmetryCheck", SymmetryWin)):
        if name in evaluate.COMMANDS:
            m, t, _f = evaluate.COMMANDS[name]
            evaluate.COMMANDS[name] = (m, t, lambda cls=cls: evaluate._show(cls))
    for name, make in (("SWStyle_UndercutAnalysis", _undercut_window), ("SWStyle_ThicknessAnalysis", _thickness_window)):
        if name in evaluate.COMMANDS:
            m, t, _f = evaluate.COMMANDS[name]
            evaluate.COMMANDS[name] = (m, t, lambda make=make: evaluate._show(make()))
    try:
        from . import partingline  # noqa: F401  (adds its command to evaluate.COMMANDS)
        if "SWStyle_PartingLineAnalysis" in evaluate.COMMANDS:
            m, t, _f = evaluate.COMMANDS["SWStyle_PartingLineAnalysis"]
            evaluate.COMMANDS["SWStyle_PartingLineAnalysis"] = (m, t, lambda: evaluate._show(_parting_window()))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Parting Line box: %s\n" % error)
    if "SWStyle_DeviationAnalysis" in evaluate2.COMMANDS:
        e = evaluate2.COMMANDS["SWStyle_DeviationAnalysis"]
        evaluate2.COMMANDS["SWStyle_DeviationAnalysis"] = (e[0], e[1], lambda: evaluate._show(_deviation_window())) + tuple(e[3:])
    if "SWStyle_ZebraStripes" in evaluate2.COMMANDS:
        e = evaluate2.COMMANDS["SWStyle_ZebraStripes"]
        evaluate2.COMMANDS["SWStyle_ZebraStripes"] = (e[0], e[1], zebra_stripes) + tuple(e[3:])
    try:
        from . import evalpanel     # the task-pane PropertyManagers over these windows (PM thread)
        evalpanel.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Evaluate PropertyManagers: %s\n" % error)
