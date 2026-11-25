# SPDX-License-Identifier: LGPL-2.1-or-later
""



import FreeCAD as App
from PySide import QtCore, QtWidgets

TITLES = ("Insert Component", "Insert Components", "Linear Pattern", "Circular Pattern", "Mirror Components",
          "Move Component", "Rotate Component", "Explode", "Exploded View", "Interference Detection",
          "Hole Series", "Weld Bead", "Smart Fasteners", "Mate", "Mate Reference", "Pattern Driven",
          "Sketch Driven Pattern", "Curve Driven Pattern", "Chain Pattern", "Belt/Chain", "Copy with Mates",
          "Motor", "Spring", "Damper", "Force/Torque", "Contact", "Gravity")
TEXT_ROOM = 250         # px a check box's text may take beside its box in a 300 px pane
DONE = "fw_asmlook_fit"


def _assembly_open():
    try:
        from . import asmcore as ac
        return ac.assembly_of(App.ActiveDocument) is not None
    except Exception:
        return False


def _k():
    ""
    try:
        from . import style
        return max(1.0, float(style.ui_scale()))
    except Exception:
        return 1.0


def _split(text, w, room):
    """The text broken onto as few lines as fit room (two, else three)."""
    words = text.split(" ")
    n = len(words)
    for k in range(n - 1, 0, -1):          # two lines: the longest first line that fits
        w.setText(" ".join(words[:k]) + "\n" + " ".join(words[k:]))
        if w.sizeHint().width() <= room:
            return True
    for i in range(n - 2, 0, -1):          # three lines
        for j in range(n - 1, i, -1):
            w.setText(" ".join(words[:i]) + "\n" + " ".join(words[i:j]) + "\n" + " ".join(words[j:]))
            if w.sizeHint().width() <= room:
                return True
    return False


def fit(view, room=None):
    """Each wide part of the page made to fit the pane."""
    k = _k()
    room = int(round((room or TEXT_ROOM) * k))
    for w in view.findChildren(QtWidgets.QAbstractButton):
        if not isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)) or w.property(DONE):
            continue
        text = w.text()
        w.ensurePolished()
        if not w.toolTip() and text and "\n" not in text:
            w.setToolTip(text)      # the whole text, however it ends up broken (or a wider pane)
        if "\n" in text or w.sizeHint().width() <= room:
            continue
        if not _split(text, w, room):       # style sheet fonts count: sizeHint, not the font's advance
            w.setText(text)
            continue
        w.setProperty(DONE, True)
        if not w.toolTip():
            w.setToolTip(text)
    for w in view.findChildren(QtWidgets.QLabel):
        if w.property(DONE) or w.wordWrap() or not w.text() or w.pixmap() is not None and not w.pixmap().isNull():
            continue
        if w.objectName().startswith("SWStyle_"):
            continue        # the page's own title row
        w.ensurePolished()
        if w.sizeHint().width() > room:
            w.setProperty(DONE, True)
            w.setWordWrap(True)
    for w in view.findChildren(QtWidgets.QComboBox):
        if w.property(DONE):
            continue
        w.setProperty(DONE, True)
        if w.sizeAdjustPolicy() != QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon:
            w.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
            w.setMinimumContentsLength(min(w.minimumContentsLength() or 8, 8))
        if w.minimumWidth() == 0 and w.minimumSizeHint().width() > int(120 * k):
            w.setMinimumWidth(int(120 * k))     # Qt keeps the old minimum hint: the layout reads this instead
    for w in view.findChildren(QtWidgets.QAbstractSpinBox):
        if w.minimumWidth() == 0 and w.minimumSizeHint().width() > int(160 * k):
            w.setMinimumWidth(int(100 * k))
    for form in view.findChildren(QtWidgets.QFormLayout):
        if form.rowWrapPolicy() != QtWidgets.QFormLayout.DontWrapRows:
            continue
        labels = [form.itemAt(i, QtWidgets.QFormLayout.LabelRole) for i in range(form.rowCount())]
        fields = [form.itemAt(i, QtWidgets.QFormLayout.FieldRole) for i in range(form.rowCount())]
        wide = 0
        for a, b in zip(labels, fields):
            wa = a.sizeHint().width() if a is not None else 0
            wb = b.minimumSize().width() if b is not None else 0
            wide = max(wide, wa + wb + form.horizontalSpacing())
        if wide > room - 20:
            form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)    # long labels go above their fields
    for w in view.findChildren(QtWidgets.QTabWidget):
        if w.property(DONE):
            continue
        w.setProperty(DONE, True)
        bar = w.tabBar()
        # no scroll arrows (the left one shows greyed: a dead control); the tabs share the width,
        # a long name shortened with its whole name as the tooltip
        bar.setUsesScrollButtons(False)
        bar.setElideMode(QtCore.Qt.ElideRight)
        for i in range(bar.count()):
            if not bar.tabToolTip(i):
                bar.setTabToolTip(i, bar.tabText(i))
        w.setMinimumWidth(0)
        pol = w.sizePolicy()
        pol.setHorizontalPolicy(QtWidgets.QSizePolicy.Ignored)
        w.setSizePolicy(pol)


def _install_after(view):
    try:
        from . import pmlayout
        title = pmlayout._title(view)
    except Exception:
        title = ""
    if title not in TITLES or not _assembly_open():
        return
    try:
        fit(view)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly PM width: %s\n" % error)
        return
    for wait in (0, 200, 600):      # Qt widened the pane before the page fitted: back to the pane's width
        QtCore.QTimer.singleShot(wait, _shrink)


def _shrink():
    try:
        from . import shell
        pane = shell.shell().left_pane
        dock = pane._dock()
        base = pane._base_width
        if dock is None or not base or dock.width() <= base:
            return
        page = pane.pages.get("Tasks")
        for v in ([page] + page.findChildren(QtWidgets.QWidget)) if page is not None else []:
            if v.metaObject().className().endswith("TaskView"):
                v.setMinimumWidth(min(v.minimumSizeHint().width(), base))
        pane._shrink_to_need()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: assembly PM width: %s\n" % error)


def install():
    """pmlayout.install gets one more step for assembly pages (wrapped at run time: pmlayout is
    the PM thread's file and is not edited)."""
    try:
        from . import pmlayout
    except Exception:
        return
    if getattr(pmlayout, "_fw_asmlook", False):
        return
    install0 = pmlayout.install

    def install_(view):
        install0(view)
        _install_after(view)
    install_.__wrapped__ = install0
    pmlayout.install = install_
    pmlayout._fw_asmlook = True


def type_buttons(combo, layout, names=None):
    ""

    row = QtWidgets.QHBoxLayout()
    row.setSpacing(4)
    group = QtWidgets.QButtonGroup(combo)
    group.setExclusive(True)
    buttons = []
    for i in range(combo.count()):
        b = QtWidgets.QToolButton()
        b.setObjectName("%s_%d" % (combo.objectName(), i))
        b.setText((names or {}).get(combo.itemText(i), combo.itemText(i)))
        b.setToolTip(combo.itemText(i))
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon if not b.icon().isNull() else QtCore.Qt.ToolButtonTextOnly)
        b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        group.addButton(b, i)
        row.addWidget(b)
        buttons.append(b)
    def sync(index):
        if 0 <= index < len(buttons):
            buttons[index].setChecked(True)
    group.idClicked.connect(combo.setCurrentIndex)
    combo.currentIndexChanged.connect(sync)
    sync(combo.currentIndex())
    layout.addLayout(row)
    combo.hide()
    return buttons
