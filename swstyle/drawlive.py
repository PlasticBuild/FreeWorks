""


from PySide import QtWidgets


def _fw_log(site, err):
    try:
        __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        pass


def _label_in(lay, w):
    if isinstance(lay, QtWidgets.QFormLayout):
        lab = lay.labelForField(w)
        if lab is not None:
            return lab
    if isinstance(lay, QtWidgets.QGridLayout):
        i = lay.indexOf(w)
        if i >= 0:
            r, c, _rs, _cs = lay.getItemPosition(i)
            if c > 0:
                it = lay.itemAtPosition(r, 0)
                lab = it.widget() if it is not None else None
                return lab if isinstance(lab, QtWidgets.QLabel) else None
            return None
    for n in range(lay.count()):
        sub = lay.itemAt(n).layout()
        if sub is not None:
            lab = _label_in(sub, w)
            if lab is not None:
                return lab
    return None


def label_of(w):
    """The label of w's form or grid row, if it has one."""
    try:
        par = w.parentWidget()
        lay = par.layout() if par is not None else None
        return _label_in(lay, w) if lay is not None else None
    except Exception as _fw_err:
        _fw_log("drawlive.py:label_of", _fw_err)
        return None


def row(w, on):
    """Shows or hides w with its row label (and makes sure it is never greyed)."""
    if w is None:
        return
    w.setEnabled(True)
    w.setVisible(bool(on))
    lab = label_of(w)
    if lab is not None:
        lab.setVisible(bool(on))


def used(w, fn):
    """fn() when the user uses w (not when the PM fills it): a pick, a click, typing."""
    if isinstance(w, QtWidgets.QComboBox):
        w.activated.connect(lambda *_: fn())
        if w.isEditable() and w.lineEdit() is not None:
            w.lineEdit().textEdited.connect(lambda *_: fn())
    elif isinstance(w, QtWidgets.QLineEdit):
        w.textEdited.connect(lambda *_: fn())
    elif isinstance(w, QtWidgets.QAbstractButton):
        w.clicked.connect(lambda *_: fn())
    elif isinstance(w, QtWidgets.QAbstractSpinBox):
        w.lineEdit().textEdited.connect(lambda *_: fn())
        w.valueChanged.connect(lambda *_: fn() if w.hasFocus() else None)     # the arrows or the wheel


def sets(check, on, *widgets):
    """Using any of widgets sets check to on."""
    for w in widgets:
        used(w, lambda: check.setChecked(on) if check.isChecked() != on else None)


def fold(group):
    """A checkable group box shows its boxes while ticked and hides them (instead of greying them) while not."""
    def kids():
        return [k for k in group.findChildren(QtWidgets.QWidget) if k.parentWidget() is group]

    def show(on):
        if not on:
            group._fw_shown = [k for k in kids() if not k.isHidden()]
            for k in group._fw_shown:
                k.hide()
        else:
            for k in getattr(group, "_fw_shown", None) or []:
                k.show()
            group._fw_shown = None
        for k in kids():
            k.setEnabled(True)
    group.toggled.connect(show)
    show(group.isChecked())
