# SPDX-License-Identifier: LGPL-2.1-or-later
""











import FreeCAD as App

PROPS = ("Length", "Length2", "Offset", "TaperAngle", "TaperAngle2", "Angle", "Angle2", "Occurrences",
         "Occurrences1", "Occurrences2", "Length1", "Offset1", "Offset2")
_installed = []
_busy = set()


def _log(site, err):
    App.Console.PrintLog("FreeCAD: configedits %s: %r\n" % (site, err))


def _page_open():
    try:
        import FreeCADGui as Gui
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


def follow(obj, prop):
    """obj.prop was just set: when it follows a configuration cell and differs from it, the shown
    configuration's cell takes the value. True when a cell was written."""
    if prop not in PROPS or not _page_open():
        return False
    key = (obj.Document.Name, obj.Name, prop)
    if key in _busy:
        return False
    try:
        if not any(p == prop for p, _e in obj.ExpressionEngine):
            return False
        from . import configs, configmanager as cm
        if not configs.configured(obj, prop):
            return False
        t = cm.table(obj.Document)
        alias = configs._alias_for(obj, prop)
        new = configs._number(getattr(obj, prop))
        try:
            cell = configs._number(obj.evalExpression(dict(obj.ExpressionEngine)[prop]))
        except Exception:
            cell = None
        if not isinstance(new, float) or (isinstance(cell, float) and abs(new - cell) < 1e-9):
            return False              # the rebuild reading the cell, or nothing new
        _busy.add(key)
        doc_name, name = obj.Document.Name, obj.Name

        def write():                  # after the page's own set: a cell write rebuilds the part
            try:
                o = App.getDocument(doc_name).getObject(name)
                if o is not None and configs._number(getattr(o, prop)) == new:
                    # a live change from the page (the value is taken as it is typed): Cancel or Esc
                    # must put the cell back too, as for a field left (PC ce370: Esc kept 170)
                    _remember(t, alias, t.active(), o)
                    _watch_close(None)
                    configs.set_cell(t, alias, new, [t.active()])
            except Exception as err:
                _log("write", err)
            finally:
                _busy.discard(key)
        try:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, write)
        except Exception:
            write()
        return True
    except Exception as err:
        _log("follow", err)
        return False


class _Watch:
    def slotChangedObject(self, obj, prop):
        if prop in PROPS:
            try:
                follow(obj, prop)
            except Exception as err:
                _log("slot", err)


def install():
    """Idempotent: the observer that sends typed values to the configuration's cell."""
    if _installed:
        return
    w = _Watch()
    App.addDocumentObserver(w)
    _installed.append(w)


# FreeCAD's own pages: a field whose property follows an expression is read-only (it shows the f(x)

FIELDS = {
    "PartDesign::Pad": {"lengthEdit": "Length", "lengthEdit2": "Length2", "offsetEdit": "Offset",
                        "taperEdit": "TaperAngle", "taperEdit2": "TaperAngle2"},
    "PartDesign::Revolution": {"revolveAngle": "Angle", "revolveAngle2": "Angle2"},
}
FIELDS["PartDesign::Pocket"] = FIELDS["PartDesign::Pad"]
FIELDS["PartDesign::Groove"] = FIELDS["PartDesign::Revolution"]
ARMED = "freeworks_configedit"


def _value(spin):
    """The number in a quantity field, in the property's own unit (mm, deg)."""
    try:
        return float(App.Units.Quantity(spin.text().replace(",", ".")).Value)
    except Exception:
        try:
            return float(spin.value().Value)
        except Exception:
            return None


def _open_up(spin):
    from PySide import QtWidgets
    spin.setReadOnly(False)
    edit = spin.findChild(QtWidgets.QLineEdit)
    if edit is not None and edit.isReadOnly():
        edit.setReadOnly(False)


def _filter_class():
    from PySide import QtCore

    class OpenUp(QtCore.QObject):
        """Takes the field out of read-only as the pointer or a key reaches it."""

        def __init__(self, spin):
            super().__init__(spin)
            self.spin = spin

        def eventFilter(self, watched, event):
            if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress,
                                QtCore.QEvent.MouseButtonDblClick):
                try:
                    _open_up(self.spin)
                except RuntimeError:
                    pass
            return False
    return OpenUp


def _OpenUp(spin):
    global _OPEN_UP
    try:
        _OPEN_UP
    except NameError:
        _OPEN_UP = _filter_class()
    return _OPEN_UP(spin)


def arm(view, feat):
    """Fields of the page bound to a property set per configuration take typing again: the value
    typed goes into the shown configuration's cell when the field is left."""
    if feat is None:
        return
    names = FIELDS.get(feat.TypeId, {})
    if not names:
        return
    try:
        from . import configs, configmanager as cm
    except Exception as err:
        _log("arm", err)
        return
    from PySide import QtWidgets
    for widget_name, prop in names.items():
        spin = view.findChild(QtWidgets.QAbstractSpinBox, widget_name)
        if spin is None or spin.property(ARMED) or prop not in feat.PropertiesList:
            continue
        try:
            if not (any(p == prop for p, _e in feat.ExpressionEngine) and configs.configured(feat, prop)):
                continue
        except Exception:
            continue
        spin.setProperty(ARMED, True)
        _open_up(spin)
        keep = _OpenUp(spin)                # FreeCAD sets the field read-only again on every rebuild
        spin.installEventFilter(keep)
        edit = spin.findChild(QtWidgets.QLineEdit)
        if edit is not None:
            edit.installEventFilter(keep)
        doc_name, name = feat.Document.Name, feat.Name

        def finished(spin=spin, prop=prop):
            try:
                o = App.getDocument(doc_name).getObject(name)
                new = _value(spin)
                if o is None or new is None or abs(configs._number(getattr(o, prop)) - new) < 1e-9:
                    return
                t = cm.table(o.Document)
                alias = configs._alias_for(o, prop)
                _remember(t, alias, t.active(), o)
                _watch_close(None)
                configs.set_cell(t, alias, new, [t.active()])
            except Exception as err:
                _log("typed", err)
        spin.editingFinished.connect(finished)
        _page_is(spin)
    _watch_close(view)


# Cancel: the cells this page wrote go back. FreeCAD's Cancel on an edit undoes no spreadsheet change,
# and Esc closes the page without its Cancel button, so the page is watched until it closes; unless OK
# was pressed, the cells are put back.
_was = {}          # (sheet doc, alias, configuration) -> (table, cell text before the page wrote it)
_ok = []


def _remember(t, alias, name, obj):
    key = (obj.Document.Name, alias, name)
    if key in _was:
        return
    try:
        from . import configs
        c = configs.column_of(t, alias)
        row = t.row_of(name)
        _was[key] = (t, str(t.sheet.getContents("%s%d" % (c, row))).lstrip("'="))
    except Exception as err:
        _log("remember", err)


def _alive(widget):
    try:
        from . import teardown
        return widget is not None and teardown.alive(widget)
    except Exception:
        return False


def _page_is(spin):
    """spin is a field of the page now open. A field of the last page that is gone means that page
    closed and the next one opened before the close was seen (a fast reopen: PC ce370, where the
    last page's OK was taken for this page's and its Esc kept the typed value): settle it first."""
    last = getattr(_watch_close, "spin", None)
    if last is not None and last is not spin and not _alive(last):
        _settle()
    _watch_close.spin = spin


def _settle():
    """The watched page closed: unless OK was pressed, the cells it wrote go back."""
    timer = getattr(_watch_close, "timer", None)
    if timer is not None:
        timer.stop()
    _watch_close.timer = None
    _watch_close.spin = None
    accepted = bool(_ok) and _ok[-1]
    del _ok[:]
    was = dict(_was)
    _was.clear()
    if accepted or not was:
        return
    from . import configs
    for (doc_name, alias, name), (t, text) in was.items():
        try:
            configs.set_cell(t, alias, text, [name])
        except Exception as err:
            _log("cancel", err)


def _hook_ok():
    """The page's OK marks the page accepted: the box's OK and any accept-role button, hooked again
    while the page is open (on the PC the button box comes after the fields are armed, so a hook
    made only then missed it and OK put the cell back: ce383 snapped 30 back to 25)."""
    from PySide import QtWidgets
    import FreeCADGui as Gui
    roles = QtWidgets.QDialogButtonBox
    for bb in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        for b in bb.buttons():
            role = bb.buttonRole(b)
            if b.property(ARMED + "_ok") or role not in (roles.AcceptRole, roles.YesRole, roles.ApplyRole,
                                                         roles.RejectRole, roles.NoRole):
                continue
            b.setProperty(ARMED + "_ok", True)
            # the last button pressed decides: an OK left over from the last page (its close not
            # seen before this page opened: PC ce370, where Cancel then kept 40) is outvoted by Cancel
            yes = role in (roles.AcceptRole, roles.YesRole, roles.ApplyRole)
            b.pressed.connect(lambda *a, yes=yes: _ok.append(yes))


def _watch_close(view):
    from PySide import QtCore
    import FreeCADGui as Gui
    try:
        _hook_ok()
    except Exception as err:
        _log("hook ok", err)
    if getattr(_watch_close, "timer", None) is not None:
        return
    timer = QtCore.QTimer()
    timer.setInterval(200)

    def tick():
        last = getattr(_watch_close, "spin", None)
        if Gui.Control.activeDialog() and (last is None or _alive(last)):
            try:
                _hook_ok()
            except Exception as err:
                _log("hook ok", err)
            return
        _settle()
    timer.timeout.connect(tick)
    timer.start()
    _watch_close.timer = timer
