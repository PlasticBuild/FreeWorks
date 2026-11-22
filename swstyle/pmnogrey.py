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


import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

MARK = "fw_nogrey"
ORPHAN = "fw_nogrey_orphan"     # a form label hidden because its field is hidden
KEEP = "fw_keep_grey"
HEADERS = ("SWStyle_PMHeader",)       # the PropertyManager header (its own OK / Cancel buttons)
INTERVAL = 250          # ms, while a page is open
_state = {"timer": None, "view": None}

CONTROLS = (QtWidgets.QAbstractButton, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit,
            QtWidgets.QAbstractItemView, QtWidgets.QAbstractSlider, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
            QtWidgets.QLabel)
# a greyed caption is dead too: the name beside a greyed mate type button, "Mate alignment:" over greyed
# alignment buttons, a heading under an unchecked group. It goes with its control (the button was hidden and
# its name stayed, greyed: Mate's Tangent, Concentric, Profile Center, the Mechanical mates)


def _alive(w):
    try:
        from shiboken6 import isValid
    except ImportError:
        try:
            from shiboken2 import isValid
        except ImportError:
            return w is not None
    return w is not None and isValid(w)


def task_view():
    v = _state["view"]
    if _alive(v):
        return v
    _state["view"] = None
    mw = Gui.getMainWindow()
    for w in mw.findChildren(QtWidgets.QWidget):
        if w.metaObject().className() == "Gui::TaskView::TaskView":
            _state["view"] = w
            return w
    return None


def _skipped(w, view):
    """OK / Cancel, scroll bars, tab arrows, inner editors and kept-grey controls stay as they are."""
    if isinstance(w, QtWidgets.QScrollBar) or w.objectName().startswith("qt_"):
        return True
    if isinstance(w, QtWidgets.QLabel) and not w.text().strip():
        pix = w.pixmap()
        if pix is None or pix.isNull():
            return True         # an empty label is spacing, not a control
    p = w.parentWidget()
    if isinstance(p, (QtWidgets.QTabBar, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
        return True
    while p is not None and p is not view:
        if isinstance(p, (QtWidgets.QDialogButtonBox, QtWidgets.QAbstractItemView, QtWidgets.QAbstractScrollArea)) \
                and not isinstance(p, QtWidgets.QScrollArea):
            return True
        if p.objectName() in HEADERS:
            return True
        if p.property(KEEP):
            return True
        p = p.parentWidget()
    return bool(w.property(KEEP))


def _label(w):
    """The row label a form layout puts beside w, else None."""
    p = w.parentWidget()
    lay = p.layout() if p is not None else None
    if isinstance(lay, QtWidgets.QFormLayout):
        try:
            return lay.labelForField(w)
        except Exception:
            return None
    if isinstance(lay, QtWidgets.QGridLayout):
        # FreeCAD's .ui panels: "Depth:" in the cell just left of its box, nothing else in the row
        try:
            i = lay.indexOf(w)
            if i < 0:
                return None
            r, c, rs, cs = lay.getItemPosition(i)
            left = lay.itemAtPosition(r, c - 1) if c > 0 else None
            lab = left.widget() if left is not None else None
            if not isinstance(lab, QtWidgets.QLabel) or not lab.text().strip().endswith(":"):
                return None
            for k in range(lay.columnCount()):
                it = lay.itemAtPosition(r, k)
                o = it.widget() if it is not None else None
                if o is not None and o is not w and o is not lab and not o.isHidden():
                    return None             # the row holds other controls: the label stays for them
            return lab
        except Exception:
            return None
    return None


def _hide(w):
    w.setProperty(MARK, True)
    w.hide()
    lab = _label(w)
    if lab is not None and not lab.isHidden():
        lab.setProperty(MARK, True)
        lab.hide()


def _show(w):
    w.setProperty(MARK, False)
    w.show()
    lab = _label(w)
    if lab is not None and lab.property(MARK):
        lab.setProperty(MARK, False)
        lab.show()


def _field_hidden(item):
    """True when a form row's field (a widget, or a layout of widgets) is hidden by the page."""
    w = item.widget()
    if w is not None:
        return w.isHidden()
    lay = item.layout()
    if lay is None:
        return False
    ws = [lay.itemAt(i).widget() for i in range(lay.count())]
    ws = [x for x in ws if x is not None]
    return bool(ws) and all(x.isHidden() for x in ws)


def _orphans(view):
    """Form labels follow their field: hidden while it is hidden, shown again with it."""
    n = 0
    for lay in view.findChildren(QtWidgets.QFormLayout):
        try:
            for r in range(lay.rowCount()):
                li = lay.itemAt(r, QtWidgets.QFormLayout.LabelRole)
                fi = lay.itemAt(r, QtWidgets.QFormLayout.FieldRole)
                lab = li.widget() if li is not None else None
                if lab is None or fi is None or not isinstance(lab, QtWidgets.QLabel) or lab.property(KEEP):
                    continue
                gone = _field_hidden(fi)
                if gone and not lab.isHidden():
                    lab.setProperty(ORPHAN, True)
                    lab.hide()
                    n += 1
                elif not gone and lab.isHidden() and lab.property(ORPHAN):
                    lab.setProperty(ORPHAN, False)
                    lab.show()
                    n += 1
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmnogrey:orphans", _fw_err)
    return n


def sweep(view=None):
    """One pass over the open page: greyed controls hidden, usable ones that were hidden for it shown again.
    The number of controls changed."""
    view = view or task_view()
    if view is None:
        return 0
    n = 0
    for w in view.findChildren(QtWidgets.QWidget):
        if not isinstance(w, CONTROLS):
            continue
        try:
            if w.property(MARK):
                if w.isEnabled() and w.isHidden():
                    _show(w)
                    n += 1
                elif not w.isHidden():
                    w.setProperty(MARK, False)          # the page showed it again itself: its own now
                continue
            if w.isEnabled() or w.isHidden() or not w.isVisibleTo(view) or _skipped(w, view):
                continue
            _hide(w)
            n += 1
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmnogrey:sweep", _fw_err)
    return n + _orphans(view)


def tool_page():
    """The sketch-tool PropertyManager in the left pane (Rectangle, Circle, Line...), else None."""
    try:
        from . import sketchtoolpm
        page = sketchtoolpm.current()
        return page if _alive(page) and page.isVisible() else None
    except Exception:
        return None


def _tick():
    try:
        if Gui.Control.activeDialog():
            sweep()
        page = tool_page()
        if page is not None:
            sweep(page)                 # sketch-tool pages sit in the left pane, not in the task view
    except Exception as _fw_err:
        _fw_log("pmnogrey:tick", _fw_err)


def install():
    if _state["timer"] is not None:
        return
    t = QtCore.QTimer(Gui.getMainWindow())
    t.setInterval(INTERVAL)
    t.timeout.connect(_tick)
    t.start()
    _state["timer"] = t
