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
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
OK_KEY, CANCEL_KEY = "PM_OK", "PM_Cancel"
MODS = Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier
TEXT_WIDGETS = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                QtWidgets.QComboBox, QtWidgets.QAbstractItemView)


def open():
    """A PropertyManager is open in the task panel (not a sketch being edited)."""
    try:
        if not Gui.Control.activeDialog():
            return False
    except Exception:
        return False
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = getattr(edit, "Object", None) if edit is not None else None
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            return False
    except Exception as _fw_err:
        _fw_log("pmconfirm.py:51", _fw_err)
    try:
        from . import sketch3d
        if sketch3d.editing():
            return False
    except Exception as _fw_err:
        _fw_log("pmconfirm.py:57", _fw_err)
    return True


def _box():
    from . import propertymanager as pm
    for dock in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
        view = pm._view(dock)
        if view is None:
            continue
        control = pm._edit_control(view)
        box = control.findChild(QtWidgets.QDialogButtonBox) if control is not None else None
        if box is not None:
            return box
    return None


def _button(role):
    box = _box()
    if box is None:
        return None
    roles = QtWidgets.QDialogButtonBox
    wanted = (roles.AcceptRole, roles.YesRole, roles.ApplyRole) if role == "ok" else (roles.RejectRole, roles.NoRole)
    for button in box.buttons():
        if not button.isHidden() and box.buttonRole(button) in wanted:
            return button
    return None


def can_ok():
    """The page has an OK. It is never greyed (NO DEAD CONTROLS): one pressed too early says in red
    what is still missing (pmkeys.accept)."""
    return _button("ok") is not None


def ok():
    """Press the page's OK (or hear what it still needs). False when there is none."""
    button = _button("ok")
    if button is None:
        return False
    from . import pmkeys
    pmkeys.accept(button)
    return True


def cancel():
    """Press the page's Cancel (FreeCAD's reject of the page)."""
    button = _button("cancel")
    if button is not None and button.isEnabled():
        button.click()
        return True
    try:
        Gui.Control.closeDialog()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- Esc / Enter
def _in_view(widget):
    try:
        from .pmtakeover import view_widget
        if widget is None:
            return False
        view = view_widget()          # the viewport; the keys land on its QGraphicsView (pkg99)
        if view is None:
            return False
        return widget is view or widget is view.parentWidget() or view.isAncestorOf(widget)
    except Exception:
        return False


def _in_page(widget):
    ""

    if widget is None:
        return False
    if isinstance(widget, QtWidgets.QComboBox):
        if widget.isEditable() or (widget.view() is not None and widget.view().isVisible()):
            return False
    elif isinstance(widget, QtWidgets.QAbstractItemView):
        try:
            if widget.state() == QtWidgets.QAbstractItemView.EditingState:
                return False
        except Exception as _fw_err:
            _fw_log("pmconfirm.py:141", _fw_err)
    elif isinstance(widget, QtWidgets.QLineEdit) and not isinstance(widget.parentWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)) \
            and not widget.isModified():
        pass
    elif isinstance(widget, TEXT_WIDGETS):
        return False
    w = widget
    while w is not None:
        if w.metaObject().className() == "Gui::TaskView::TaskView":
            return True
        w = w.parentWidget()
    # the keyboard on the PropertyManager's pane itself (after a click on its empty part): Enter is OK too
    w = widget
    while w is not None and not isinstance(w, QtWidgets.QDockWidget):
        w = w.parentWidget()
    if w is not None and (widget is w or widget is w.widget()):
        try:
            from . import propertymanager
            return propertymanager._view(w) is not None
        except Exception:
            return False
    return False


def _esc_in_field(widget):
    ""


    if widget is None:
        return False
    # any control of the page (a list, a check box, a button Tab reached), not only a value field:
    # Esc there closed the page FreeCAD's way and kept the feature (Full Round Fillet)
    if isinstance(widget, QtWidgets.QComboBox) and widget.view() is not None and widget.view().isVisible():
        return False
    if isinstance(widget, QtWidgets.QAbstractItemView):
        try:
            if widget.state() == QtWidgets.QAbstractItemView.EditingState:
                return False
        except Exception as _fw_err:
            _fw_log("pmconfirm.py:180", _fw_err)
    w = widget
    while w is not None:
        if w.metaObject().className() == "Gui::TaskView::TaskView":
            return True
        w = w.parentWidget()
    return False


class Keys(QtCore.QObject):
    """Application-wide: Enter = OK, Esc = Cancel while a PropertyManager is open."""

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if event.type() == QtCore.QEvent.KeyRelease:
            # the release of a key whose press we took: FreeCAD's 3D view rejects the task
            # dialog on the release of Esc (pkg102), so it must not see it
            self._last = None           # the next press is a new keystroke
            if event.key() == getattr(self, "_swallow", None):
                self._swallow = None
                return True
            return False
        if event.type() != QtCore.QEvent.KeyPress:
            return False
        key = event.key()
        if key not in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter) or (event.modifiers() & MODS):
            return False
        if key == Qt.Key_Escape:
            try:
                from . import pmhandles
                if pmhandles.esc_cancels_drag(event):
                    # features-426: Esc while a page's handle is dragged (Shell thickness, pattern spacing) put the

                    self._swallow = key
                    return True
            except Exception as _fw_err:
                _fw_log("pmconfirm.py:handle-esc", _fw_err)
        if _busy():
            return False                # a drag on the view: its Esc puts the value back, the page stays
        if QtWidgets.QApplication.activePopupWidget() is not None or QtWidgets.QApplication.activeModalWidget() is not None:
            return False
        focus = QtWidgets.QApplication.focusWidget()
        if not (_in_view(focus) or _in_view(watched) or _in_page(focus)
                or (key == Qt.Key_Escape and _esc_in_field(focus))) or not open():
            return False
        stamp = (event.timestamp(), key)
        if stamp == getattr(self, "_last", None):
            return True                 # the same keystroke, delivered again to the view's child
        self._last = stamp
        if key == Qt.Key_Escape:
            self._swallow = key
            try:
                from . import selman
                if selman.is_open():            # Esc closes the SelectionManager first
                    QtCore.QTimer.singleShot(0, selman.close)
                    return True
            except Exception as error:
                App.Console.PrintLog("FreeCAD pmconfirm: SelectionManager check: %r\n" % error)
            QtCore.QTimer.singleShot(0, cancel)
            return True
        if can_ok():
            self._swallow = key
            QtCore.QTimer.singleShot(0, ok)
            return True
        return False


_keys = None

BUSY = []       # callables: True while a handle drag of a page wants Esc for itself (bodytriad)


def _busy():
    for test in list(BUSY):
        try:
            if test():
                return True
        except Exception as _fw_err:
            _fw_log("pmconfirm.py:busy", _fw_err)
    return False


def install():
    global _keys
    if _keys is None:
        _keys = Keys()
        from . import pmevents
        pmevents.hook("pm.confirm", (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease), _keys.eventFilter)      # pkg98, release pkg102


# --------------------------------------------------------------------------- right-click menu
def _icon(family, tint=None):
    from . import icons
    icon = icons.family(family)
    if icon.isNull():
        try:
            from .propertymanager import _drawn
            icon = _drawn(family)
        except Exception as _fw_err:
            _fw_log("pmconfirm.py:256", _fw_err)
    if tint and not icon.isNull():
        try:
            from .propertymanager import _tinted
            icon = _tinted(icon, tint)
        except Exception as _fw_err:
            _fw_log("pmconfirm.py:262", _fw_err)
    return icon


def _selection_manager():
    ""
    try:
        from . import selman
        return selman.menu_action()
    except Exception:
        return None


def view_menu(pos):
    """The graphics-area menu while a page is open: OK, Cancel, then the selection and view items."""
    from . import rcmenus
    from .propertymanager import OK_GREEN
    items = [rcmenus.action(OK_KEY, "OK", ok, icon=_icon("CHECK_MARK", OK_GREEN)),
             rcmenus.action(CANCEL_KEY, "Cancel", cancel, icon=_icon("STANDARD_CANCEL")),
             rcmenus.separator(),
             rcmenus.action("ClearSelections", "Clear Selections", rcmenus.clear_selections),
             _selection_manager(),
             rcmenus.separator(),
             rcmenus.entry("ZoomFit", "Zoom to Fit"), rcmenus.entry("ZoomArea", "Zoom to Area"),
             rcmenus.entry("ZoomInOut", "Zoom In/Out"), rcmenus.entry("RotateView", "Rotate View"),
             rcmenus.entry("Pan", "Pan"), rcmenus.entry("NormalTo", "Normal To")]
    items = [i for i in items if i is not None]
    if not can_ok():
        items = items[1:]       # no greyed OK (NO DEAD CONTROLS): the page cannot finish yet, so the menu starts at Cancel
    return rcmenus.show(rcmenus.Builder("PMView", items, chevron=True), pos)


# --------------------------------------------------------------------------- mouse gesture
def gesture_items(items):
    """The ring's items with OK at the top and Cancel at the bottom while a page is open."""
    from .gestures import Item
    from .propertymanager import OK_GREEN
    out = []
    for item in items:
        if abs(item.angle - 90.0) < 1e-6:
            # no greyed OK on the ring: while the page cannot finish, the view command stays on top
            out.append(Item(OK_KEY, "OK", _icon("CHECK_MARK", OK_GREEN), True, 90.0) if can_ok() else item)
        elif abs(item.angle - 270.0) < 1e-6:
            out.append(Item(CANCEL_KEY, "Cancel", _icon("STANDARD_CANCEL"), True, 270.0))
        else:
            out.append(item)
    return out


def run_key(key):
    """True when key is OK / Cancel (and it was pressed)."""
    if key == OK_KEY:
        ok()
        return True
    if key == CANCEL_KEY:
        cancel()
        return True
    return False
