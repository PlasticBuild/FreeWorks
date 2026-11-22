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
import FreeCADGui as Gui
from PySide import QtWidgets

from . import drawings as D
from . import drawviews as DV
from . import drawannot as DA

V = App.Vector
PICK = 2.0          # mm on the sheet


def _ct():
    from . import cosmeticthread
    return cosmeticthread


def model_edge(view, centre, radius):
    """The part edge behind a circle of the view (geometry centre, radius): (object, "EdgeN") of the circle seen
    end on, the one nearest the viewer when a hole has two; None if there is none."""
    d, x, y = D.view_frame(view)
    best = None
    for o in DV.source_shapes(view):
        holder = o
        try:
            if o.TypeId == "PartDesign::Body" and o.Tip is not None:
                holder = o.Tip
            sh = holder.Shape
        except Exception:
            continue
        for n, e in enumerate(sh.Edges):
            c = getattr(e, "Curve", None)
            if type(c).__name__ != "Circle" or abs(c.Radius - radius) > 1e-4:
                continue
            ax = V(c.Axis)
            if abs(abs(ax.dot(d)) - 1) > 1e-6:
                continue
            g = DA._project(view, V(c.Center))
            if math.hypot(g.x - centre[0], g.y - centre[1]) > 1e-3:
                continue
            depth = V(c.Center).dot(d)
            if best is None or depth > best[0]:
                best = (depth, holder, "Edge%d" % (n + 1))
    return best[1:] if best else None


def body_of(obj):
    for o in obj.InList:
        if o.TypeId == "PartDesign::Body":
            return o
    return obj if obj.TypeId == "PartDesign::Body" else None


def _views_of_part(page, part_doc):
    out = []
    for v in D.views_of(page):
        if any(o.Document is part_doc for o in DV.source_shapes(v)):
            out.append(v)
    return out


class CosmeticThreadPanel(D._Panel):
    TITLE = "Cosmetic Thread"
    PIXMAP = "TechDraw_ExtensionThreadHoleSide"
    LAYER = True
    HINT = "Select a circular edge of a shaft or hole in a view."

    def build(self):
        ct = _ct()
        self.say(self.HINT)
        self.edge = None              # (view, part object, "EdgeN", geometry centre, radius)
        self.marks = []
        box, lay = D._group("Thread Settings", self.form)
        self.edge_box = QtWidgets.QListWidget(box)
        self.edge_box.setObjectName("SWThreadEdge")
        self.edge_box.setMaximumHeight(40)
        lay.addWidget(self.edge_box)
        self.reverse = QtWidgets.QCheckBox("Reverse direction", box)
        self.reverse.setObjectName("SWThreadReverse")
        lay.addWidget(self.reverse)
        self.lay.addWidget(box)
        box, lay = D._group("Specification", self.form)
        grid = QtWidgets.QFormLayout()
        self.standard = QtWidgets.QComboBox(box)
        self.standard.setObjectName("SWThreadStandard")
        self.standard.addItems(list(ct.STANDARDS))
        self.standard.setCurrentText("ISO" if "ISO" in ct.STANDARDS else ct.STANDARDS[0])
        grid.addRow("Standard:", self.standard)
        self.size = QtWidgets.QComboBox(box)
        self.size.setObjectName("SWThreadSize")
        grid.addRow("Size:", self.size)
        self.diameter = QtWidgets.QDoubleSpinBox(box)
        self.diameter.setObjectName("SWThreadDiameter")
        self.diameter.setRange(0.01, 10000)
        self.diameter.setDecimals(2)
        self.diameter.setSuffix(" mm")
        self.diameter.setValue(5.0)
        grid.addRow("Thread diameter:", self.diameter)
        self.end = QtWidgets.QComboBox(box)
        self.end.setObjectName("SWThreadEnd")
        self.end.addItems(list(ct.ENDS))
        grid.addRow("End condition:", self.end)
        self.depth = QtWidgets.QDoubleSpinBox(box)
        self.depth.setObjectName("SWThreadDepth")
        self.depth.setRange(0.01, 10000)
        self.depth.setDecimals(2)
        self.depth.setSuffix(" mm")
        self.depth.setValue(10.0)
        grid.addRow("Depth:", self.depth)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        box, lay = D._group("Thread Callout", self.form)
        self.callout = QtWidgets.QLineEdit(box)
        self.callout.setObjectName("SWThreadCallout")
        self.callout.setReadOnly(True)
        lay.addWidget(self.callout)
        self.lay.addWidget(box)
        self.standard.currentTextChanged.connect(self._standard_changed)
        for w in (self.size, self.end):
            w.currentTextChanged.connect(self._refresh)
        for w in (self.diameter, self.depth):
            w.valueChanged.connect(self._refresh)
        self.reverse.toggled.connect(self._refresh)
        self._standard_changed(self.standard.currentText())
        self._preselected()

    # ---- fields
    def _internal(self):
        if self.edge is None:
            return False
        try:
            return bool(self._geometry().get("internal"))
        except Exception:
            return False

    def _geometry(self):
        """The thread's geometry from the part's edge, as the part feature works it out."""
        ct = _ct()
        _view, obj, sub, _c, _r = self.edge

        class _Probe:
            pass
        probe = _Probe()
        probe.Edge = [(obj, [sub])]
        probe.Reverse = self.reverse.isChecked()
        probe.EndCondition = self.end.currentText()

        class _Q:
            def __init__(self, v):
                self.Value = v
        probe.Depth = _Q(self.depth.value())
        return ct.geometry(probe, obj.Shape)

    def _standard_changed(self, standard):
        ct = _ct()
        self.size.blockSignals(True)
        self.size.clear()
        names = [r[0] for r in ct.SIZES.get(standard, ())]
        self.size.addItems(names)
        if self.edge is not None and names:
            pick = ct.nearest(standard, 2 * self.edge[4], self._internal())
            if pick:
                self.size.setCurrentText(pick)
        self.size.blockSignals(False)
        none = standard == "None"
        self.size.setVisible(not none)
        self.diameter.setVisible(none)
        self._label(self.size).setVisible(not none)
        self._label(self.diameter).setVisible(none)
        self._refresh()

    def _label(self, w):
        lay = w.parentWidget().layout()
        for i in range(lay.count()):
            it = lay.itemAt(i)
            if isinstance(it, QtWidgets.QFormLayout):
                lab = it.labelForField(w)
                if lab is not None:
                    return lab
        return QtWidgets.QWidget()

    def _refresh(self, *_):
        self.depth.setEnabled(self.end.currentText() == "Blind")
        self._label(self.depth).setEnabled(self.depth.isEnabled())
        if self.edge is None:
            self.callout.setText("")
            return
        ct = _ct()
        try:
            g = self._geometry()
        except Exception as error:
            self.callout.setText("")
            self.say(str(error))
            return
        std = self.standard.currentText()
        if std == "None":
            other = self.diameter.value()
        else:
            found = ct.size(std, self.size.currentText())
            other = (found[0] if g["internal"] else found[0] - 1.0825318 * found[1]) if found else 0.0
        self.callout.setText(ct.callout(std, self.size.currentText(), g["internal"], self.end.currentText(),
                                        g["length"], other))
        self.say("OK adds the thread to %s." % self.edge[1].Document.Label)

    # ---- picking
    def _preselected(self):
        ""
        try:
            for sel in Gui.Selection.getSelectionEx():
                v = sel.Object
                if not v.isDerivedFrom("TechDraw::DrawViewPart"):
                    continue
                for sub in sel.SubElementNames:
                    if not sub.startswith("Edge"):
                        continue
                    e = v.getEdgeByIndex(int(sub[4:]))
                    c = e.Curve
                    if type(c).__name__ == "Circle" and self.pick(v, (c.Center.x, c.Center.y), c.Radius):
                        return
        except Exception as _fw_err:
            _fw_log("drawthread.py:245", _fw_err)

    def pick(self, view, centre, radius):
        hit = model_edge(view, centre, radius)
        if hit is None:
            self.say("That circle is not a round edge of the part seen end on.")
            return False
        obj, sub = hit
        self.edge = (view, obj, sub, centre, radius)
        self.edge_box.clear()
        self.edge_box.addItem("%s <%s>" % (sub, view.Label))
        if self.standard.currentText() == "None":
            internal = self._internal()
            self.diameter.setValue(round(2 * radius * (1.1 if internal else 0.85), 2))
        else:
            self._standard_changed(self.standard.currentText())
        if abs(self.depth.value() - 10.0) < 1e-9:
            self.depth.setValue(round(1.5 * 2 * radius, 2))
        self._refresh()
        return True

    def sheet_click(self, p):
        v = DV.view_at(self.page, p, PICK)
        if v is None or not v.isDerivedFrom("TechDraw::DrawViewPart"):
            self.say(self.HINT)
            return True
        hit = DA.circle_at(v, DV.to_geometry(v, p), PICK / DV.view_scale(v))
        if hit is None:
            self.say(self.HINT)
            return True
        _i, c, r = hit
        self.pick(v, (c.x, c.y), r)
        return True

    # ---- OK
    def make(self):
        """The part's Cosmetic Thread feature for the picked edge, drawn in the drawing's views of that part."""
        if self.edge is None:
            return None
        ct = _ct()
        from . import simplefeature as sf
        view, obj, sub, _c, _r = self.edge
        part = obj.Document
        values = {"Reverse": self.reverse.isChecked(), "Standard": self.standard.currentText(),
                  "EndCondition": self.end.currentText(), "Depth": self.depth.value()}
        if values["Standard"] == "None":
            values["Diameter"] = self.diameter.value()
        else:
            values["Size"] = self.size.currentText()
        body = body_of(obj)
        if body is None:
            raise RuntimeError("the part has no body to keep the thread in")
        before = body.Tip
        feat = sf.make(ct.SPEC, doc=part, picks={"Edge": [(obj, sub)]}, edit=False, **values)
        if feat is None:
            return None
        try:
            feat.SizeFor = 2 * self.edge[4]
        except Exception as _fw_err:
            _fw_log("drawthread.py:304", _fw_err)
        part.recompute()
        if before is not None and body.Tip is feat and feat.Shape.isNull():
            body.Tip = before
        self.doc.recompute()
        views = _views_of_part(self.page, part)
        DA.cosmetic_threads(self.page, views, only=[feat])
        self.doc.recompute()
        return feat

    def finish(self):
        feat = self.make()
        if feat is not None:
            self.made.append(feat)


def cosmetic_thread():
    page = D.active_page()
    if page is None:
        return None
    return D._show(CosmeticThreadPanel(page))


class _Command:
    def GetResources(self):
        return {"MenuText": "Cosmetic Thread...", "Pixmap": D.pixmap("TechDraw_ExtensionThreadHoleSide"),
                "ToolTip": "Adds a cosmetic thread to a round edge picked in a view; the part keeps it too."}

    def IsActive(self):
        page = D.active_page()
        if page is None or not D.sheet_shown(page) or D.busy():
            return False
        return any(DV.source_shapes(v) for v in D.views_of(page))

    def Activated(self):
        cosmetic_thread()


def register():
    if "FreeWorks_DrawCosmeticThread" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_DrawCosmeticThread", _Command())
