# SPDX-License-Identifier: LGPL-2.1-or-later
""












import time

try:
    import FreeCADGui as Gui
    from PySide import QtWidgets
except ImportError:
    Gui = None

LIVE_S = 4.0        # a line FreeCAD writes outside a hover stays this long before a prompt may replace it
_state = {"label": None, "text": "", "since": 0.0, "hooked": None}


def _bar():
    mw = Gui.getMainWindow() if Gui is not None else None
    return mw.statusBar() if mw is not None else None


def action_label():
    """FreeCAD's own message label: the unnamed label at the far left of the status bar."""
    lab = _state["label"]
    if lab is not None:
        try:
            lab.objectName()
            return lab
        except RuntimeError:
            _state["label"] = None
    sb = _bar()
    if sb is None:
        return None
    found = None
    for w in sb.findChildren(QtWidgets.QLabel):
        if w.parentWidget() is not sb or w.objectName():
            continue
        if "StatusBarLabel" in w.metaObject().className():
            found = w
            break
        if found is None or w.x() < found.x():
            found = w
    _state["label"] = found
    _hook(sb)
    return found


def _hook(sb):
    if _state["hooked"] is sb:
        return
    try:
        sb.messageChanged.connect(_message_changed)
        _state["hooked"] = sb
    except Exception:
        pass


def _message_changed(text):
    if text:
        lab = action_label()
        if lab is not None and lab.text():
            lab.clear()
            _state["text"] = ""


def _hovering():
    try:
        return bool(Gui.Selection.getPreselection().ObjectName)
    except Exception:
        return False


def busy():
    """True while FreeCAD's own line holds live text; stale text is cleared here."""
    lab = action_label()
    text = lab.text() if lab is not None else ""
    if not text:
        _state["text"] = ""
        return False
    now = time.monotonic()
    if text != _state["text"]:
        _state["text"], _state["since"] = text, now
    if _hovering():
        _state["since"] = now
        return True
    if now - _state["since"] < (0.5 if _was_preselection(text) else LIVE_S):
        return True
    lab.clear()
    _state["text"] = ""
    return False


def _was_preselection(text):
    # FreeCAD's line for the item under the pointer ends with its picked point "(x, y, z)"
    return text.rstrip().endswith(")") and text.count(",") >= 2
