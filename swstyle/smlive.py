""


from PySide import QtWidgets


def _fw_log(site, err):
    try:
        __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        pass


def row(w, on):
    """Shows or hides w with its form row label."""
    if w is None:
        return
    try:
        lay = w.parentWidget().layout() if w.parentWidget() is not None else None
        if isinstance(lay, QtWidgets.QFormLayout) and hasattr(lay, "setRowVisible") and lay.indexOf(w) >= 0:
            lay.setRowVisible(w, bool(on))
            return
    except Exception as _fw_err:
        _fw_log("smlive.py:row", _fw_err)
    w.setVisible(bool(on))


def turn(panel, check, on=True):
    """check set to on, unless the panel is filling its boxes itself."""
    if check is None or getattr(panel, "busy", False):
        return
    if check.isChecked() != on:
        check.setChecked(on)


def _value(w, fn):
    if isinstance(w, QtWidgets.QComboBox):
        w.activated.connect(lambda *_: fn())
    elif isinstance(w, QtWidgets.QAbstractButton):
        w.clicked.connect(lambda *_: fn())
    elif w is not None and hasattr(w, "valueChanged"):
        w.valueChanged.connect(lambda *_: fn())


def live(p):
    """Wires the common bend boxes of a sheet metal PM (whichever it has). Call before connecting its _changed."""
    g = lambda n: getattr(p, n, None)
    radius, default = g("radius"), g("default_radius")
    if radius is not None and default is not None:
        def typed():
            root = g("root_radius")
            if root is None or abs(radius.value() - root) > 1e-9:
                turn(p, default, False)
        radius.valueChanged.connect(lambda *_: typed())
    custom_k = g("custom_k")
    if custom_k is not None:
        for w in (g("allowance"), g("kfactor")):
            _value(w, lambda: turn(p, custom_k))
        c = g("custom")
        for n in ("combo", "kspin", "ba", "bd"):
            _value(getattr(c, n, None) if c is not None else None, lambda: turn(p, custom_k))
    custom_r = g("custom_relief")
    if custom_r is not None:
        _value(g("relief"), lambda: turn(p, custom_r))
        t = g("tear")
        for b in (getattr(t, "buttons", []) if t is not None else []):
            _value(b, lambda: turn(p, custom_r))
        ratio_on = g("ratio_on")
        _value(ratio_on, lambda: turn(p, custom_r))
        _value(g("ratio"), lambda: (turn(p, custom_r), turn(p, ratio_on)))
        for w in (g("relief_w"), g("relief_d")):
            _value(w, lambda: (turn(p, custom_r), turn(p, ratio_on, False)))


def show(p):
    """The common bend boxes' rows for the current choices (in the PM's _show): nothing greyed."""
    g = lambda n: getattr(p, n, None)
    for n in ("radius", "allowance", "kfactor", "relief", "ratio_on", "ratio", "relief_w", "relief_d"):
        w = g(n)
        if w is not None:
            w.setEnabled(True)
    c = g("custom")
    if c is not None:
        c.show(True)
    t = g("tear")
    tear = bool(t is not None and t.on())
    if t is not None:
        t.show(True)
    ratio_on = g("ratio_on")
    if ratio_on is not None:
        ratio_on.setVisible(not tear)
        ratio = ratio_on.isChecked()
        row(g("ratio"), ratio and not tear)
        row(g("relief_w"), not ratio and not tear)
        row(g("relief_d"), not ratio and not tear)
