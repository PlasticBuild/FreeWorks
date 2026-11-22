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
from PySide import QtCore, QtWidgets

from .widgets import alive

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchTools"


def _params():
    return App.ParamGet(PARAMS)


def _edit_api():
    from .fwsketch import splineedit
    return splineedit


def is_fw_spline(sketch, geo):
    ""
    try:
        return geo is not None and geo >= 0 and _edit_api().is_spline(sketch, geo)
    except Exception:
        return False


class Box:
    """Rows inside a group that show and hide together (the spline part of the entity page)."""

    def __init__(self, group):
        self.body = QtWidgets.QWidget(group.body)
        self.content = QtWidgets.QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.content.setSpacing(4)
        group.content.addWidget(self.body)

    def setVisible(self, on):
        self.body.setVisible(on)


class SplineFields(QtCore.QObject):
    """Options and Parameters rows put into two groups of a page (Group objects of relationspm).

    host: the page; it gives .sketch and show_note(text, warning). placing: a callable giving
    the points of the spline being placed ([] when none)."""

    def __init__(self, host, options, parameters, style=False, placing=None):
        super().__init__(host)
        self.host = host
        self.style = style
        self.placing = placing or (lambda: [])
        self.geo = None
        self._filling = False
        api = None
        try:
            api = _edit_api()
        except Exception as _fw_err:
            _fw_log("splinepm.py:85", _fw_err)
        p = _params()
        body = options.body
        self.curvature = QtWidgets.QCheckBox("Show Curvature", body)
        self.curvature.setObjectName("SWSplineShowCurvature")
        self.curvature.setChecked(p.GetBool("SplineShowCurvature", False))
        options.content.addWidget(self.curvature)
        self.continuity = QtWidgets.QCheckBox("Maintain Internal Continuity", body)
        self.continuity.setObjectName("SWSplineContinuity")
        self.continuity.setChecked(True)
        options.content.addWidget(self.continuity)

        self.proportional = QtWidgets.QCheckBox("Proportional", parameters.body)
        self.proportional.setObjectName("SWSplineProportional")
        self.proportional.setChecked(p.GetBool("SplineProportional", False))
        try:
            from .fwsketch import splineshow     # noqa: F401
        except Exception:
            self.curvature.hide()
        if api is None or not hasattr(api, "set_continuity") or style:
            self.continuity.hide()
        if api is None or not hasattr(api, "set_proportional") or style:
            self.proportional.hide()

        g = parameters
        self.labels = {}

        def row(label, widget):
            line = QtWidgets.QHBoxLayout()
            text = QtWidgets.QLabel(label, g.body)
            line.addWidget(text)
            line.addWidget(widget, 1)
            g.content.addLayout(line)
            self.labels[widget] = text
            return widget

        def number(name, low, high, suffix, decimals=2):
            f = QtWidgets.QDoubleSpinBox(g.body)
            f.setObjectName(name)
            f.setRange(low, high)
            f.setDecimals(decimals)
            f.setSuffix(suffix)
            f.setKeyboardTracking(False)
            return f
        self.index = row("Control vertex" if style else "Spline point", QtWidgets.QSpinBox(g.body))
        self.index.setObjectName("SWSplinePoint")
        self.index.setRange(1, 1)
        self.x = row("X", number("SWSplineX", -1e6, 1e6, " mm"))
        self.y = row("Y", number("SWSplineY", -1e6, 1e6, " mm"))
        self.weight1 = row("Tangent Weighting 1", number("SWSplineWeight1", 1, 10000, " %", 0))
        self.weight2 = row("Tangent Weighting 2", number("SWSplineWeight2", 1, 10000, " %", 0))
        self.angle = row("Tangent radial direction", number("SWSplineAngle", -360, 360, "°"))
        self.driving = QtWidgets.QCheckBox("Tangent Driving", g.body)
        self.driving.setObjectName("SWSplineTangentDriving")
        g.content.addWidget(self.driving)
        self.reset_one = QtWidgets.QPushButton("Reset This Handle", g.body)
        self.reset_one.setObjectName("SWSplineResetHandle")
        g.content.addWidget(self.reset_one)
        self.reset_all = QtWidgets.QPushButton("Reset All Handles", g.body)
        self.reset_all.setObjectName("SWSplineResetAll")
        g.content.addWidget(self.reset_all)
        self.relax_button = QtWidgets.QPushButton("Relax Spline", g.body)
        self.relax_button.setObjectName("SWSplineRelax")
        g.content.addWidget(self.relax_button)
        g.content.addWidget(self.proportional)
        self.tangent_rows = (self.weight1, self.weight2, self.angle)
        if style:
            for w in self.tangent_rows:
                w.hide()
                self.labels[w].hide()
            for w in (self.driving, self.reset_one, self.reset_all, self.relax_button):
                w.hide()
        self.index.valueChanged.connect(lambda *a: self.fill())
        self.x.valueChanged.connect(self._point)
        self.y.valueChanged.connect(self._point)
        for w in self.tangent_rows:
            w.valueChanged.connect(self._tangent)
        self.relax_button.clicked.connect(self._relax)
        self.driving.toggled.connect(self._driving)
        self.reset_one.clicked.connect(self._reset_one)
        self.reset_all.clicked.connect(self._reset_all)
        self.curvature.toggled.connect(self._show_curvature)
        self.continuity.toggled.connect(self._set_continuity)
        self.proportional.toggled.connect(self._set_proportional)

    # ---------------------------------------------------------------- state
    @property
    def sketch(self):
        return self.host.sketch

    def note(self, text):
        try:
            self.host.show_note(text, warning=True)
        except TypeError:
            self.host.show_note(text)       # the sketch entity page's note has no warning flag
        except Exception as _fw_err:
            _fw_log("splinepm.py:181", _fw_err)

    def info(self):
        if self.geo is None:
            return None
        api = _edit_api()
        try:
            if self.style:
                points = [pos for _circle, pos in api.control_vertices(self.sketch, self.geo)]
                return {"points": points, "tangents": [], "sides": [], "driven": [], "closed": False}
            return api.info(self.sketch, self.geo)
        except Exception:
            return None

    def set_spline(self, geo, new=False):
        """Edit this spline; new: just made, so the remembered options go on it."""
        self.geo = geo
        if new and geo is not None:
            if self.curvature.isVisible() and self.curvature.isChecked():
                self._show_curvature(True)
            if self.continuity.isVisible() and not self.continuity.isChecked():
                self._set_continuity(False)
            if self.proportional.isVisible() and self.proportional.isChecked():
                self._set_proportional(True)
        self.fill(last=new)

    def _options_from_spline(self):
        api = _edit_api()
        try:
            from .fwsketch import splineshow
            self.curvature.setChecked(splineshow.COMB in (splineshow.shown(self.sketch, self.geo) or ()))
        except Exception as _fw_err:
            _fw_log("splinepm.py:213", _fw_err)
        for box, ask in ((self.continuity, "maintains_continuity"), (self.proportional, "is_proportional")):
            if box.isVisible() and hasattr(api, ask):
                try:
                    box.setChecked(bool(getattr(api, ask)(self.sketch, self.geo)))
                except Exception as _fw_err:
                    _fw_log("splinepm.py:219", _fw_err)

    def fill(self, last=False):
        """Show the point the number picks: of the spline being placed, else of the one edited."""
        if not alive(self.index):
            return
        self._filling = True
        try:
            placing = self.placing()
            info = None if placing else self.info()
            points = placing or (info["points"] if info else [])
            editable = bool(info) and not placing
            if editable:
                self._options_from_spline()
            n = max(1, len(points))
            self.index.setRange(1, n)
            if placing or last:
                self.index.setValue(n)
            i = self.index.value() - 1
            if points:
                self.x.setValue(points[i][0])
                self.y.setValue(points[i][1])
            sides = info.get("sides") if editable else None
            tangent = info["tangents"][i] if editable and i < len(info.get("tangents", [])) else None
            if sides and i < len(sides):
                angle, w1, w2 = sides[i]
                self.angle.setValue(angle)
                self.weight1.setValue(w1 * 100.0)
                self.weight2.setValue(w2 * 100.0)
            elif tangent is not None:
                self.angle.setValue(tangent[0])
                self.weight1.setValue(tangent[1] * 100.0)
                self.weight2.setValue(tangent[1] * 100.0)
            for w in (self.x, self.y):
                w.setReadOnly(not editable)
            # no dead (greyed) controls: what cannot act yet is not shown. While the spline is

            # offers it only then
            has_handle = editable and tangent is not None
            if not self.style:
                for w in self.tangent_rows:
                    w.setEnabled(True)
                    w.setVisible(has_handle)
                    self.labels[w].setVisible(has_handle)
            driven = set(info.get("driven", ())) if editable else set()
            self.driving.setChecked(i in driven)
            self.driving.setEnabled(True)
            if not self.style:
                self.driving.setVisible(has_handle)
                self.reset_one.setVisible(i in driven)
                self.reset_all.setVisible(bool(driven))
                self.relax_button.setVisible(editable)
            for w in (self.reset_one, self.reset_all, self.relax_button):
                w.setEnabled(True)
        finally:
            self._filling = False

    # ---------------------------------------------------------------- edits
    def _edit(self, label, call):
        doc = self.sketch.Document
        doc.openTransaction(label)
        try:
            call()
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            self.note(str(error))
        doc.recompute()
        self._refresh_handles()
        self.fill()

    def _refresh_handles(self):
        try:
            from .fwsketch import splinehandles
            h = splinehandles.current()
            if h is not None and getattr(h, "geo", None) == self.geo:
                h.refresh()
        except Exception as _fw_err:
            _fw_log("splinepm.py:286", _fw_err)

    def _busy(self):
        return self._filling or self.geo is None or bool(self.placing())

    def _point(self, *args):
        if self._busy():
            return
        api = _edit_api()
        i = self.index.value() - 1
        info = self.info()
        x, y = self.x.value(), self.y.value()
        if info and i < len(info["points"]):
            # the box shows 2 decimals: the field not typed in keeps its exact value
            ox, oy = info["points"][i]
            x = ox if abs(x - ox) < 0.006 else x
            y = oy if abs(y - oy) < 0.006 else y
        if self.style:
            self._edit("Move control vertex", lambda: api.move_vertex(self.sketch, self.geo, i, x, y))
        else:
            self._edit("Spline point", lambda: api.set_point(self.sketch, self.geo, i, x, y))

    def _tangent(self, *args):
        if self._busy() or self.style:
            return
        api = _edit_api()
        i = self.index.value() - 1
        angle, w1, w2 = self.angle.value(), self.weight1.value() / 100.0, self.weight2.value() / 100.0
        try:
            from .fwsketch import splinehandles
            h = splinehandles.current()
        except Exception:
            h = None
        try:
            if h is not None and getattr(h, "geo", None) == self.geo:
                if abs(w1 - w2) > 1e-9 and hasattr(h, "apply_sides"):
                    h.apply_sides(i, angle, w1, w2)
                else:
                    h.apply(i, angle, w1)
                self.fill()
                return
        except Exception as error:
            self.note(str(error))
            return
        if abs(w1 - w2) > 1e-9:
            self._edit("Spline handle", lambda: api.set_tangent(self.sketch, self.geo, i, angle, weight1=w1, weight2=w2))
        else:
            self._edit("Spline handle", lambda: api.set_tangent(self.sketch, self.geo, i, angle, w1))

    def _undrive(self, indexes, label):
        api = _edit_api()
        if self.geo is None or not hasattr(api, "undrive"):
            return

        def go():
            for i in indexes:
                api.undrive(self.sketch, self.geo, i)
        self._edit(label, go)

    def _driving(self, on):

        # present direction and weight drive the spline there
        if self._filling:
            return
        if on:
            self._tangent()
            return
        self._undrive([self.index.value() - 1], "Reset This Handle")

    def _reset_one(self):
        self._undrive([self.index.value() - 1], "Reset This Handle")

    def _reset_all(self):
        info = self.info()
        if info:
            self._undrive(sorted(info.get("driven", ())), "Reset All Handles")

    def _relax(self):
        if self.geo is not None:
            api = _edit_api()
            self._edit("Relax Spline", lambda: api.relax(self.sketch, self.geo))

    def _show_curvature(self, on):
        _params().SetBool("SplineShowCurvature", bool(on))
        if self._filling or self.geo is None:
            return
        try:
            from .fwsketch import splineshow
            splineshow.set_shown(self.sketch, self.geo, splineshow.COMB, bool(on))
            splineshow.refresh()
        except Exception as error:
            self.note(str(error))

    def _set_continuity(self, on):
        if self._filling or self.geo is None or self.style:
            return
        api = _edit_api()
        try:
            if api.maintains_continuity(self.sketch, self.geo) == bool(on):
                return
        except Exception as _fw_err:
            _fw_log("splinepm.py:383", _fw_err)
        self._edit("Maintain Internal Continuity", lambda: api.set_continuity(self.sketch, self.geo, bool(on)))

    def _set_proportional(self, on):
        _params().SetBool("SplineProportional", bool(on))
        if self._filling or self.geo is None or self.style:
            return
        api = _edit_api()
        try:
            if api.is_proportional(self.sketch, self.geo) == bool(on):
                return
        except Exception as _fw_err:
            _fw_log("splinepm.py:395", _fw_err)
        self._edit("Proportional spline", lambda: api.set_proportional(self.sketch, self.geo, bool(on)))
