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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

_STATE = {}
_TAG = re.compile(r"<[^>]+>")


def description(tip, title=""):
    """The description part of a tooltip: the lines after the bold title, as plain text."""
    if not tip:
        return ""
    text = tip.replace("<br/>", "\n").replace("<br>", "\n").replace("<BR>", "\n")
    lines = [_TAG.sub("", ln).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()
             for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    plain_title = (title or "").replace("&", "").strip()
    if len(lines) > 1 and ("<b>" in tip or lines[0].replace("&", "") == plain_title):
        lines = lines[1:]
    out = " ".join(lines)
    return "" if out.replace("&", "") == plain_title else out


def _catalog_tip(name):
    if not name.startswith("SWToolMenu_"):
        return ""
    try:
        from . import catalog
        c = catalog.BY_KEY.get(name[len("SWToolMenu_"):])
        return (c.tip or "") if c is not None else ""
    except Exception:
        return ""


def action_hint(action):
    if action is None or action.isSeparator() or action.statusTip():
        return ""
    text = action.text().split("\t")[0]
    tip = action.toolTip()
    hint = description(tip, text) if tip and tip.replace("&", "") != text.replace("&", "") else ""
    return hint or description(_catalog_tip(action.objectName()), text)


def widget_hint(widget):
    """A CommandManager button (widgets.CommandButton: its catalog command's tip, whatever the tooltip size
    option says), a FreeCAD action shown as a button (ribbon.NativeActionButton) or any Qt button."""
    b = getattr(widget, "binding", None)
    cmd = getattr(b, "cmd", None)
    if cmd is not None:
        return description(getattr(cmd, "tip", "") or "", getattr(cmd, "label", ""))
    act = getattr(widget, "action", None)
    if isinstance(act, QtGui.QAction):
        return act.statusTip() or action_hint(act)
    if isinstance(widget, QtWidgets.QAbstractButton):
        return button_hint(widget)
    return ""


def button_hint(button):
    if button.statusTip():
        return ""
    title = button.text() if hasattr(button, "text") else ""
    hint = description(button.toolTip(), title)
    if not hint:
        act = button.defaultAction() if isinstance(button, QtWidgets.QToolButton) else None
        hint = action_hint(act) if act is not None else ""
    return hint


def _bar():
    mw = Gui.getMainWindow()
    return mw.statusBar() if mw is not None else None


def show(text):
    bar = _bar()
    if bar is not None and text:
        bar.showMessage(text)
        _STATE["shown"] = text


def clear():
    bar = _bar()
    if bar is not None and _STATE.get("shown") and bar.currentMessage() == _STATE["shown"]:
        bar.clearMessage()
    _STATE["shown"] = ""


class Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper instead of the event
        try:
            t = event.type()
            if t == QtCore.QEvent.Enter and isinstance(obj, QtWidgets.QWidget):
                hint = widget_hint(obj)
                if hint:
                    QtCore.QTimer.singleShot(0, lambda h=hint: show(h))
            elif t == QtCore.QEvent.Leave and isinstance(obj, QtWidgets.QWidget):
                if _STATE.get("shown"):
                    clear()
            elif t == QtCore.QEvent.StatusTip and not event.tip():
                menu = QtWidgets.QApplication.activePopupWidget()
                if not isinstance(menu, QtWidgets.QMenu):
                    return False
                hint = action_hint(menu.activeAction())
                if hint:
                    QtCore.QTimer.singleShot(0, lambda h=hint: show(h))
        except Exception as _fw_err:
            _fw_log("statustips.py:137", _fw_err)
        return False


READOUT_WIDTH = 380       # px for FreeCAD's own line (Preselected ...) once it sits on the right


_PRESEL = re.compile(r"^\s*Preselected:\s.*\(([^()]*)\)\s*$", re.S)
_NUM_UNIT = re.compile(r"(-?[0-9][0-9.,eE+-]*)\s+([^\s,;()]+)")


def readout_text(text):
    ""


    m = _PRESEL.match(text or "")
    if m is None:
        return text
    parts = [p.strip() for p in m.group(1).split(",") if p.strip()] if ";" not in m.group(1) else []
    if len(parts) != 3:                  # a decimal comma: the three values are split by "; " or spaces
        parts = ["%s %s" % pair for pair in _NUM_UNIT.findall(m.group(1))] or m.group(1).split()
    return " ".join(_NUM_UNIT.sub(r"\1\2", p) for p in parts)


def _fix_readout(label):
    try:
        text = label.text()
        if text.lstrip().startswith("Preselected:"):
            new = readout_text(text)
            if new != text:
                label.setText(new)
    except Exception as _fw_err:
        _fw_log("statustips.py:_fix_readout", _fw_err)


class _Readout(QtCore.QObject):
    """Rewrites FreeCAD's preselection line before it is drawn (a QLabel has no text-changed signal)."""

    def eventFilter(self, label, event):
        try:
            if event.type() == QtCore.QEvent.Paint:
                text = label.text()
                new = readout_text(text)
                if new != text:
                    label.setText(new)
        except Exception as _fw_err:
            _fw_log("statustips.py:readout_text", _fw_err)
        return False


def _move_readout(bar):
    ""




    labels = [w for w in bar.findChildren(QtWidgets.QLabel, "", QtCore.Qt.FindDirectChildrenOnly)
              if not w.objectName()]      # FreeCAD's own line is the one label it leaves unnamed
    for label in labels[:1]:
        bar.removeWidget(label)
        label.setObjectName("SWFreeCADReadout")
        label.setMinimumWidth(120)
        label.setMaximumWidth(READOUT_WIDTH)
        label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, label.sizePolicy().verticalPolicy())
        label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        _STATE["readout"] = _Readout(label)
        label.installEventFilter(_STATE["readout"])
        timer = QtCore.QTimer(label)        # FreeCAD writes the line on every pointer move, painted or not
        timer.setInterval(100)
        timer.timeout.connect(lambda lab=label: _fix_readout(lab))
        timer.start()
        _STATE["readout_timer"] = timer
        # the status bar's widgets in its own order (the index insertPermanentWidget counts in)
        order = []
        stack = [bar.layout()]
        while stack:
            lay = stack.pop(0)
            for i in range(lay.count()):
                item = lay.itemAt(i)
                if item.widget() is not None:
                    order.append(item.widget())
                elif item.layout() is not None:
                    stack.insert(0, item.layout())
        order = [w for w in order if not isinstance(w, QtWidgets.QSizeGrip)]
        info = bar.findChild(QtWidgets.QWidget, "SWStatusInfo")
        index = order.index(info) if info in order else -1
        bar.insertPermanentWidget(index, label, 0)
        label.show()
        return True
    return False


def _hook_bar():
    try:
        bar = _bar()
        if bar is not None and _STATE.get("hooked") is not bar and _move_readout(bar):
            _STATE["hooked"] = bar
    except Exception as _fw_err:
        _fw_log("statustips.py:readout", _fw_err)


def install():
    if "filter" in _STATE:
        return
    for ms in (0, 3000, 15000):         # FreeCAD may set up its status bar after the add-on starts
        QtCore.QTimer.singleShot(ms, _hook_bar)
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    _STATE["filter"] = Filter()
    try:
        # extapps/72: through the add-on's one dispatcher, for the three event types it reads (an application
        # filter of its own was called for every event Qt sends: ~10,000 when a sketch is closed)
        from . import events
        events.register("statustips", (QtCore.QEvent.Enter, QtCore.QEvent.Leave, QtCore.QEvent.StatusTip),
                        _STATE["filter"].eventFilter)
        return
    except Exception as _fw_err:
        _fw_log("statustips.py:events", _fw_err)
    app.installEventFilter(_STATE["filter"])
