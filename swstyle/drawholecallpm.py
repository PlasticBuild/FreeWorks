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

_installed = []


def _circle_of(dim):
    """(view, centre, radius) of the hole circle a callout dimensions, else None (a side callout)."""
    try:
        if getattr(dim, "SWSideCallout", False):
            return None
        view, subs = dim.References2D[0]
        sub = subs[0] if isinstance(subs, (list, tuple)) else subs
        cv = view.getEdgeByIndex(int(sub[4:])).Curve
        if type(cv).__name__ != "Circle":
            return None
        return view, App.Vector(cv.Center.x, cv.Center.y, 0), cv.Radius
    except Exception as _fw_err:
        _fw_log("drawholecallpm:_circle_of", _fw_err)
        return None


def _digits(dim):
    return int(getattr(dim, "SWCalloutDigits", 2) or 2)


def callout_values(dim):
    from . import drawannot as A
    hit = _circle_of(dim)
    if hit is None:
        return {}
    view, c, r = hit
    return A.callout_values(view, c, r, _digits(dim))


def follow_variables(dim):
    """A callout whose text holds callout variables: the text with them is kept (it follows the hole) and the
    dimension shows them worked out. True when the callout has variables."""
    from . import drawannot as A
    spec = dim.FormatSpec or ""
    if not getattr(dim, "SWHoleCallout", False) or not A.has_variables(spec):
        return False
    vals = callout_values(dim)
    if not vals:
        return False
    A.set_callout_format(dim, spec)
    out = A.expand_callout(spec, vals)
    A.set_text(dim, out)
    if "SWCalloutAuto" in dim.PropertiesList:
        dim.SWCalloutAuto = out
    return True


def hand_off(panel, dim):
    """The callout placed: the Hole Callout PM closes (keeping it) and the Dimension PM opens on it."""
    from . import drawdimpm
    try:
        if dim is None or dim.Document is None:
            return None
        panel.accept()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hole Callout: %s\n" % error)
        return None
    try:
        return drawdimpm.open_for(dim)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hole Callout Dimension PM: %s\n" % error)
        return None


def _add_variables_button(pm):
    from . import drawannot as A
    dim = pm.dim
    if not getattr(dim, "SWHoleCallout", False) or _circle_of(dim) is None:
        return
    box = None
    for g in pm.form.findChildren(QtWidgets.QGroupBox):
        if g.title() == "Dimension Text":
            box = g
            break
    if box is None or box.layout() is None:
        return
    b = QtWidgets.QPushButton("Callout variables...", box)
    b.setObjectName("SWDimCalloutVariables")
    b.setToolTip("Insert a variable (the hole's diameter, depth, count...) into the callout text: "
                 "text with variables follows the hole")

    def pick():
        v = A.CalloutVariablesDialog.pick(callout_values(pm.dim))
        if v:
            pm.text.insert(v)
            pm.text.setFocus()
            pm.revalue()
        return v
    b.clicked.connect(pick)
    pm.callout_variables = b
    box.layout().addWidget(b)


def install():
    if _installed:
        return
    try:
        from . import drawannot as A, drawdimpm as DP
    except Exception as error:
        App.Console.PrintLog("FreeCAD: hole callout PM not extended: %s\n" % error)
        return
    panel_cls, dim_cls = A.HoleCalloutPanel, DP.DimensionPanel
    if getattr(panel_cls, "_fw_holecall", False):
        return
    panel_cls._fw_holecall = True
    click0 = panel_cls.sheet_click
    init0, revalue0 = dim_cls.__init__, dim_cls.revalue

    def sheet_click(self, p):
        n = len(getattr(self, "dims", []))
        out = click0(self, p)
        dims = getattr(self, "dims", [])
        if len(dims) > n:
            dim = dims[-1]
            QtCore.QTimer.singleShot(0, lambda s=self, d=dim: hand_off(s, d))
        return out

    def __init__(self, dim, others=()):
        init0(self, dim, others)
        try:
            _add_variables_button(self)
        except Exception as _fw_err:
            _fw_log("drawholecallpm:init", _fw_err)

    def revalue(self, *args):
        revalue0(self, *args)
        if getattr(self, "loading", False):
            return
        changed = False
        for d in [self.dim] + list(getattr(self, "others", [])):
            try:
                changed = follow_variables(d) or changed
            except Exception as _fw_err:
                _fw_log("drawholecallpm:revalue", _fw_err)
        if changed:
            self.doc.recompute()

    panel_cls.sheet_click = sheet_click
    dim_cls.__init__, dim_cls.revalue = __init__, revalue
    _installed.append(True)
