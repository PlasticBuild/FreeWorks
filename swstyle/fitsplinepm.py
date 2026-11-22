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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from . import contextbar, relationspm, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/FitSpline"
LINKS = "FreeWorksFitLinks"


def _params():
    return App.ParamGet(PARAMS)


def chain_length(sketch, ids):
    return sum(sketch.Geometry[i].toShape().Length for i in ids)


def fit_curve(sketch, ids, closed=False, tolerance=0.0):
    """The spline that fits the chain of geometry ids (nothing added to the sketch)."""
    import Part
    edges = [sketch.Geometry[i].toShape() for i in ids]
    groups = Part.sortEdges(edges)
    if len(groups) != 1:
        raise ValueError("the picked entities must form one connected chain")
    wire = Part.Wire(groups[0])
    n = max(8, 12 * len(edges))
    pts = wire.discretize(Number=n)
    if wire.isClosed() or closed:
        if (pts[0] - pts[-1]).Length < 1e-9:
            pts = pts[:-1]
        curve = Part.BSplineCurve()
        if tolerance > 0:
            # fewer points the looser the fit, through them as a periodic curve
            step = max(1, int(round(tolerance / max(wire.Length / n, 1e-9))))
            pts = pts[::step] if len(pts[::step]) >= 4 else pts
        curve.interpolate(pts, PeriodicFlag=True)
        return curve
    curve = Part.BSplineCurve()
    if tolerance > 0:
        curve.approximate(Points=pts, Tolerance=tolerance)
    else:
        curve.interpolate(pts)
    return curve


# --- Constrained: the fit follows its source ---------------------------------------------------------
def _links(sketch):
    try:
        return json.loads(getattr(sketch, LINKS, "") or "[]")
    except Exception:
        return []


def _save_links(sketch, links):
    if LINKS not in sketch.PropertiesList:
        sketch.addProperty("App::PropertyString", LINKS, "FreeCAD", "Constrained fit splines (hidden)", 4)
        try:
            sketch.setEditorMode(LINKS, 2)
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:84", _fw_err)
    setattr(sketch, LINKS, json.dumps(links))


def link(sketch, spline, sources, closed, tolerance):
    geos = sketch.Geometry
    sid = sketch.getGeometryId(spline)
    links = [k for k in _links(sketch) if k["spline"] != geos[spline].Tag and k.get("spline_id") != sid]
    # Tags are new after save and reopen; the saved geometry ids are kept
    links.append({"spline": geos[spline].Tag, "sources": [geos[i].Tag for i in sources],
                  "spline_id": sid, "source_ids": [sketch.getGeometryId(i) for i in sources],
                  "closed": bool(closed), "tol": float(tolerance), "key": _shape_key(sketch, sources)})
    _save_links(sketch, links)


def _shape_key(sketch, ids):
    out = []
    for i in ids:
        g = sketch.Geometry[i]
        try:
            out.append([round(v, 9) for p in (g.StartPoint, g.EndPoint) for v in (p.x, p.y)])
        except Exception:
            out.append(repr(g))
    return out


_busy = False


def refit(sketch):
    """Fits every Constrained spline of sketch again whose source moved; how many changed."""
    global _busy
    if _busy:
        return 0
    links = _links(sketch)
    if not links:
        return 0
    _busy = True
    changed = 0
    try:
        by_tag = {g.Tag: i for i, g in enumerate(sketch.Geometry)}
        by_id = {sketch.getGeometryId(i): i for i in range(len(sketch.Geometry))}
        keep = []
        for k in links:
            if "spline_id" in k:
                spline = by_id.get(k["spline_id"])
                sources = [by_id.get(g) for g in k.get("source_ids", [])]
            else:
                spline = by_tag.get(k["spline"])
                sources = [by_tag.get(t) for t in k["sources"]]
            if spline is None or None in sources:
                continue                    # the spline or a source is gone: the link goes too
            keep.append(k)
            key = _shape_key(sketch, sources)
            if key == k.get("key"):
                continue
            try:
                curve = fit_curve(sketch, sources, k["closed"], k["tol"])
            except Exception:
                continue
            from .fwsketch import splineedit
            splineedit._replace(sketch, spline, curve)
            k["key"] = key
            changed += 1
        if keep != links or changed:
            _save_links(sketch, keep)
    finally:
        _busy = False
    return changed


class _Observer:
    def slotChangedObject(self, obj, prop):
        if prop != "Geometry" or _busy:
            return
        try:
            if obj.isDerivedFrom("Sketcher::SketchObject") and LINKS in obj.PropertiesList:
                # after the change, not inside its notification
                from PySide import QtCore
                QtCore.QTimer.singleShot(0, lambda o=obj: _refit_later(o))
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:157", _fw_err)


def _refit_later(obj):
    try:
        if refit(obj):
            obj.Document.recompute()
    except Exception as _fw_err:
        _fw_log("fitsplinepm.py:165", _fw_err)


_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)


# --- the page ---------------------------------------------------------------------------------------
class FitSplinePage(sketchtoolpm.ToolPage):
    TITLE = "Fit Spline"
    ICON = "SKETCH_FIT_SPLINE"
    PIXMAP = "Sketcher_BSpline"

    def build(self):
        p = _params()
        self._original = (len(self.sketch.Geometry), len(self.sketch.Constraints))
        self.entities = []
        self.spline = None
        self._filling = True
        g = self.group("Entities to fit")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWSelectedEntities")
        self.list.setFixedHeight(80)
        g.content.addWidget(self.list)
        g = self.group("Parameters")
        self.delete = QtWidgets.QCheckBox("Delete geometry", g.body)
        self.delete.setChecked(p.GetBool("Delete", False))
        self.closed = QtWidgets.QCheckBox("Closed spline", g.body)
        self.closed.setChecked(False)
        self.constrained = QtWidgets.QRadioButton("Constrained", g.body)
        self.unconstrained = QtWidgets.QRadioButton("Unconstrained", g.body)
        self.fix = QtWidgets.QRadioButton("Fix", g.body)
        {"Unconstrained": self.unconstrained, "Fix": self.fix}.get(p.GetString("Mode", "Constrained"),
                                                                  self.constrained).setChecked(True)
        for w in (self.delete, self.closed, self.constrained, self.unconstrained, self.fix):
            g.content.addWidget(w)
        form = QtWidgets.QFormLayout()
        self.tol = QtWidgets.QDoubleSpinBox(g.body)
        self.tol.setRange(0.0, 1e5)
        self.tol.setDecimals(3)
        self.tol.setSuffix(" mm")
        self.tol.setToolTip("Tolerance: how far the spline may leave the entities (0 = through them)")
        self.tol.setKeyboardTracking(False)
        form.addRow("Tolerance:", self.tol)
        g.content.addLayout(form)
        self._tol_set = False
        g = self.group("Preview Options")
        self.preview = QtWidgets.QCheckBox("Preview", g.body)
        self.preview.setChecked(True)
        self.comb = QtWidgets.QCheckBox("Curvature comb", g.body)
        self.comb.setChecked(p.GetBool("Comb", False))
        self.minrad = QtWidgets.QCheckBox("Minimum radius", g.body)
        self.minrad.setChecked(p.GetBool("MinimumRadius", False))
        for w in (self.preview, self.comb, self.minrad):
            g.content.addWidget(w)
        for w in (self.delete, self.closed, self.constrained, self.unconstrained, self.fix, self.preview,
                  self.comb, self.minrad):
            w.toggled.connect(self.changed)
        self.tol.valueChanged.connect(self._tol_typed)
        self._filling = False
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)

    def _tol_typed(self, *args):
        if not self._filling:
            self._tol_set = True
            self.changed()

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:246", _fw_err)
        if item is None or item.geo < 0 or item.geo >= self._original[0] or item.geo in self.entities:
            return
        if item.pos != relationspm.NONE:
            return
        self.entities.append(item.geo)
        self.list.addItem(relationspm._entity_names(self.sketch.Geometry)[item.geo])
        if not self._tol_set:

            self._filling = True
            self.tol.setValue(round(0.05 * chain_length(self.sketch, self.entities), 2))
            self._filling = False
        self.changed()

    def selection_changed(self):
        pass

    def _show(self, on_comb, on_min):
        if self.spline is None:
            return
        try:
            from .fwsketch import splineshow as SS
            SS.start()
            SS.set_shown(self.sketch, self.spline, SS.COMB, on_comb)
            SS.set_shown(self.sketch, self.spline, SS.MINRADIUS, on_min)
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:272", _fw_err)

    def undo_work(self):
        self._show(False, False)
        self.spline = None
        super().undo_work()
        orig = getattr(self, "_original", None)
        if orig is None:
            return
        sk = self.sketch
        try:
            extra = list(range(orig[0], len(sk.Geometry)))
            if extra:
                sk.delGeometries(extra)
            for i in range(len(sk.Constraints) - 1, orig[1] - 1, -1):
                sk.delConstraint(i)
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:289", _fw_err)

    def changed(self, *args):
        if self._filling:
            return
        if self.delete.isChecked() and self.constrained.isChecked():
            self._filling = True
            self.unconstrained.setChecked(True)     # nothing left to follow
            self._filling = False
        self.constrained.setEnabled(not self.delete.isChecked())
        self.undo_work()
        if not self.entities or not self.preview.isChecked():
            return
        self.begin()
        try:
            curve = fit_curve(self.sketch, self.entities, self.closed.isChecked(), self.tol.value())
        except Exception as error:
            self.show_note("Could not fit: %s" % error, True)
            return
        self.show_note("")
        self.spline = self.sketch.addGeometry(curve, False)
        self._show(self.comb.isChecked(), self.minrad.isChecked())
        sketchtoolpm._refresh(self.sketch)

    def finish(self):
        if not self.entities:
            return
        p = _params()
        p.SetBool("Delete", self.delete.isChecked())
        p.SetString("Mode", "Constrained" if self.constrained.isChecked() else
                    "Fix" if self.fix.isChecked() else "Unconstrained")
        p.SetBool("Comb", self.comb.isChecked())
        p.SetBool("MinimumRadius", self.minrad.isChecked())
        if self.spline is None:
            self.preview.setChecked(True)            # the check makes the fit even without a preview
            if self.spline is None:
                return
        self.begin()
        sk = self.sketch
        spline = self.spline
        self._show(False, False)
        if self.delete.isChecked():
            sk.delGeometries(sorted(self.entities))
            spline -= sum(1 for g in self.entities if g < spline)
        else:
            for g in self.entities:
                sk.setConstruction(g, True)
            if self.constrained.isChecked():
                install()
                link(sk, spline, self.entities, self.closed.isChecked(), self.tol.value())
        if self.fix.isChecked():
            try:
                sk.addConstraint(__import__("Sketcher").Constraint("Block", spline))
            except Exception as _fw_err:
                _fw_log("fitsplinepm.py:343", _fw_err)
        self.spline = None
        sk.solve()
        sketchtoolpm._refresh(sk)

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("fitsplinepm.py:352", _fw_err)
        self.observer.page = None


def open_page():
    sketch = contextbar.sketch_in_edit()
    if sketch is not None:
        install()
        sketchtoolpm.open_page(FitSplinePage(sketch))
