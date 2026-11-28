# SPDX-License-Identifier: LGPL-2.1-or-later
""

















from . import editobj

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

from . import equations, icons, pmmessage

Qt = QtCore.Qt
DONE = "swstyle_values"
EQ = "sweq"                     # the field shows an equation's result ("Σ" in front)
MARK = "Σ "

FUNCTIONS = ["sin()", "cos()", "tan()", "asin()", "acos()", "atan()", "atan2(;)", "sqrt()", "abs()",
             "exp()", "ln()", "log()", "pow(;)", "min(;)", "max(;)", "round()", "floor()", "ceil()", "mod(;)"]
CONSTANTS = ["pi", "e"]

# FreeCAD's task panel fields and the property each one drives (for the equation link)
NATIVE = {"lengthEdit": "Length", "lengthEdit2": "Length2", "offsetEdit": "Offset",
          "taperEdit": "TaperAngle", "taperEdit2": "TaperAngle2",
          "revolveAngle": "Angle", "revolveAngle2": "Angle2",
          "Value": "Thickness", "thicknessEdit": "Thickness",
          "Diameter": "Diameter", "Depth": "Depth", "ThreadDepth": "ThreadDepth",
          "spinboxValue": "Value"}


def _alive(widget):
    try:
        widget.objectName()
        return True
    except RuntimeError:
        return False


def _whole(widget):
    """False while a field is being taken down (its panel closing): Qt has already run the line edit's and
    the spin box's own destructors and only the QWidget part is left, so reading its text would crash."""
    try:
        return widget is not None and widget.metaObject().className() not in ("QWidget", "QObject")
    except RuntimeError:
        return False


def _is_quantity(box):
    return box.inherits("Gui::QuantitySpinBox")


def _value(box):
    if _is_quantity(box):
        return float(box.property("rawValue") or 0.0)
    return float(box.value())


def _set_value(box, v):
    if _is_quantity(box):
        box.setProperty("rawValue", float(v))
    else:
        box.setValue(float(v))


def _step(box):
    if _is_quantity(box):
        return float(box.property("singleStep") or 1.0)
    return float(box.singleStep())


def _factor(box):
    """mm per unit shown: a millimetre box shown in the part's unit (pmlength) holds mm, shows inches."""
    try:
        return float(box.property("fw_length_factor") or 1.0)
    except Exception:
        return 1.0


def _terms(box, text):
    ""

    if _factor(box) == 1.0 or box.property("fw_length_power") != 1:
        return text
    try:
        from . import pmlength
        return pmlength.bare_terms(text, str(box.property("fw_length_symbol") or "mm"))
    except Exception as _fw_err:
        _fw_log("pmvalues.py:terms", _fw_err)
        return text


def _evaluate_in(box, text):
    """evaluate() for a box: a sum's bare terms in the unit the box shows; a sum of numbers only ("10/2+1") in it."""
    t = _terms(box, text)
    if t == text:
        return evaluate(text, _unit(box))
    try:
        return evaluate(t, _unit(box))
    except ValueError:
        if any(c.isalpha() for c in text.replace("e", "").replace("E", "")):
            raise
        return evaluate(text, _unit(box)) * _factor(box)       # numbers only: the result is in the unit shown


def _unit(box):
    """The unit a plain field shows ("mm", "deg", "%", ""), from its suffix."""
    if _factor(box) != 1.0 and box.property("fw_length_power") == 1:
        return "mm"         # it shows the part's unit but holds mm: a typed "1in" becomes 25.4
    suffix = box.suffix().strip() if hasattr(box, "suffix") else ""
    return {"°": "deg"}.get(suffix, suffix)


def evaluate(text, unit):
    """A typed value, with units or arithmetic, as a number in unit ("10in" -> 254 for mm);
    raises ValueError when the text is no quantity."""
    q = _quantity(text)
    if unit in ("mm", "deg", "in", "m", "cm", "ft"):
        if q.Unit == App.Units.Unit():   # a plain number: already in the field's unit
            return float(q.Value)
        try:
            return float(q.getValueAs(unit))
        except Exception as error:
            raise ValueError(str(error))
    return float(q.Value)


def value_for(box, text):
    """The box's value for a typed text. A length field in the document's units (filletpm's,
    value in mm) reads a bare number in the document's unit, as its own parse does."""
    if hasattr(box, "text_of") and hasattr(box, "parse"):
        q = _quantity(text)
        if q.Unit == App.Units.Unit():
            return float(q.Value) * box._unit()[0]
        try:
            return float(q.getValueAs("mm"))
        except Exception as error:
            raise ValueError(str(error))
    return _evaluate_in(box, text)


def _quantity(text):
    """The typed text as a FreeCAD quantity (units and arithmetic); ValueError when it is none."""
    text = text.strip()
    if not text:
        raise ValueError("empty")
    q = None
    try:
        q = App.Units.Quantity(text.replace("°", " deg"))
    except Exception:
        # arithmetic ("10+5", "2*5mm+1in"): FreeCAD's expression parser, through any object
        doc = App.ActiveDocument
        host = (doc.Objects[0] if doc is not None and doc.Objects else None)
        if host is None:
            raise ValueError("no document")
        try:
            got = host.evalExpression(text.replace("°", " deg"))
        except Exception as error:
            raise ValueError(str(error))
        q = got if hasattr(got, "Unit") else App.Units.Quantity(float(got))
    return q


def _why(text, error):
    """The banner's line for a text that cannot be read."""
    shown = text.strip()
    if not shown:
        return "The field is empty: type a value."
    return "\"%s\" is not a value this field can read." % shown


def _num(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


def _range_text(box, value):
    ""
    try:
        low, high = float(box.minimum()), float(box.maximum())
    except Exception:
        return None
    if value is None or low - 1e-12 <= value <= high + 1e-12:
        return None
    k = _factor(box)        # the limits in the unit shown
    return "Please enter a number greater than or equal to %s and less than or equal to %s." % (_num(low / k), _num(high / k))


def _out_of_range(box, value):
    text = _range_text(box, value)
    if text is None:
        return False
    pmmessage.invalid(box, text)
    try:
        QtWidgets.QToolTip.showText(box.mapToGlobal(QtCore.QPoint(0, box.height())), text, box)
    except Exception as _fw_err:
        _fw_log("pmvalues.py:155", _fw_err)
    return True


def _plain_number(text):
    try:
        float(text.strip().replace(",", "."))
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------ the equation link
def _edited_object():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        return editobj.of(edit) if edit is not None else None
    except Exception:
        return None


def binding(box):
    ""

    name = box.objectName()
    dialog = Gui.Control.activeDialog()
    panel = dialog if dialog else None
    obj = getattr(panel, "obj", None) if panel is not None else None
    widgets = getattr(panel, "widgets", None) if panel is not None else None
    if obj is not None and isinstance(widgets, dict):
        for field, widget in widgets.items():
            if widget is box and field in obj.PropertiesList:
                return obj, field
    obj = _edited_object()
    if obj is None:
        return None
    prop = NATIVE.get(name)
    if prop is None:
        for p in obj.PropertiesList:
            if p.lower() == name.lower():
                prop = p
                break
    if prop is None or prop not in obj.PropertiesList:
        return None
    return obj, prop


def link(box, text):
    """Links the field's property to the equation text ("Width" * 2, after "=")."""
    bound = binding(box)
    if bound is None:
        raise ValueError("This field cannot take an equation")
    obj, prop = bound
    expr = equations.to_freecad(obj.Document, text, target=(obj, prop))
    if not expr:
        obj.setExpression(prop, None)
        box.setProperty(EQ, "")
        box.setToolTip(box.property("swTipBefore") or "")
        return None
    equations.accept_expression(obj.Document, obj, prop, expr, prop)    # refused when it cannot be solved
    obj.Document.recompute()
    value = getattr(obj, prop)
    value = float(value.Value) if hasattr(value, "Value") else float(value)
    if box.property("swTipBefore") is None:
        box.setProperty("swTipBefore", box.toolTip())
    box.setProperty(EQ, text)
    box.setToolTip("= " + equations.to_sw(obj.Document, expr, owner=obj))
    return value


PENDING = "sweqpending"          # an equation typed in a field with no property behind it yet ("R1")
PENDING_VALUE = "sweqpendingvalue"


def _names_something(text):
    ""

    return '"' in text


def _equation_value(box, text):
    ""

    if not _names_something(text):
        return value_for(box, text)
    doc = App.ActiveDocument
    host = (doc.Objects[0] if doc is not None and doc.Objects else None)
    if host is None:
        raise ValueError("no document")
    try:
        got = host.evalExpression(equations.to_freecad(doc, text))
    except Exception as error:
        raise ValueError(str(error))
    if not hasattr(got, "Unit"):
        got = App.Units.Quantity(float(got))
    if got.Unit == App.Units.Unit():
        if hasattr(box, "text_of"):
            return float(got.Value) * box._unit()[0]
        return float(got.Value)
    try:
        return float(got.getValueAs("mm")) if hasattr(box, "text_of") else float(got.Value)
    except Exception as error:
        raise ValueError(str(error))


def set_pending(box, text, value=None):
    """Keeps (or, with "", drops) the equation a page links its feature to on OK."""
    box.setProperty(PENDING, text or "")
    box.setProperty(PENDING_VALUE, float(value) if (text and value is not None) else None)
    if text:
        if box.property("swTipBefore") is None:
            box.setProperty("swTipBefore", box.toolTip())
        box.setToolTip("= " + text)
    elif box.property("swTipBefore") is not None:
        box.setToolTip(box.property("swTipBefore") or "")


def pending(box):
    """The equation typed in the field, while the field still shows its result; "" once a value
    was typed over it."""
    text = box.property(PENDING) or ""
    if not text:
        return ""
    try:
        if abs(float(box.value()) - float(box.property(PENDING_VALUE))) > 1e-9:
            return ""
    except Exception:
        return ""
    return text


def link_pending(box, obj, prop):
    ""

    text = pending(box)
    if text:
        expr = equations.to_freecad(obj.Document, text, target=(obj, prop))
        equations.accept_expression(obj.Document, obj, prop, expr, prop)
        return True
    if box.property(PENDING) and any(p.lstrip(".") == prop for p, _e in (obj.ExpressionEngine or [])):
        try:
            from . import configs
            if configs.configured(obj, prop):
                return False
        except Exception as _fw_err:
            _fw_log("pmvalues.py:link-pending configured", _fw_err)
        obj.setExpression(prop, None)
    return False


def show_pending_of(box, obj, prop):
    ""
    for path, expr in (obj.ExpressionEngine or []):
        if path.lstrip(".") == prop:
            try:
                set_pending(box, equations.to_sw(obj.Document, expr, owner=obj), box.value())
                edit = box.lineEdit() if hasattr(box, "lineEdit") else None
                if edit is not None and not edit.text().startswith(MARK.strip()):
                    edit.setText(MARK + edit.text())
            except Exception as _fw_err:
                _fw_log("pmvalues.py:show-pending", _fw_err)
            return


def equation_of(box):
    ""
    bound = binding(box)
    if bound is None:
        return ""
    obj, prop = bound
    for path, expr in (obj.ExpressionEngine or []):
        if path == prop:
            return equations.to_sw(obj.Document, expr, owner=obj)
    return ""


def _beside(box, popup):
    """Where the unit list goes: at the field's right end, level with it, on the screen; never over another field."""
    point = box.mapToGlobal(QtCore.QPoint(box.width() + 2, 0))
    try:
        screen = box.screen().availableGeometry()
        if point.x() + popup.width() > screen.right():
            point.setX(box.mapToGlobal(QtCore.QPoint(0, 0)).x() - popup.width() - 2)
        if point.y() + popup.height() > screen.bottom():
            point.setY(screen.bottom() - popup.height())
    except Exception as _fw_err:
        _fw_log("pmvalues.py:beside", _fw_err)
    return point


class _OutsideClick(QtCore.QObject):
    """A press anywhere but on the list takes the list down without picking from it; the press goes on to where it
    was made (the field below, the graphics area, OK)."""

    def __init__(self, choices):
        super().__init__(choices)
        self.choices = choices

    def eventFilter(self, watched, event):
        try:
            if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.MouseButtonPress \
                    and self.choices.isVisible() and isinstance(watched, QtWidgets.QWidget) \
                    and watched is not self.choices and not self.choices.isAncestorOf(watched) \
                    and watched.window() is not self.choices:
                field = self.choices.field
                if not (watched is field.box or field.box.isAncestorOf(watched)):
                    QtCore.QTimer.singleShot(0, field.hide_list)
        except RuntimeError:
            pass
        except Exception as _fw_err:
            _fw_log("pmvalues.py:outside_click", _fw_err)
        return False


class _Choices(QtWidgets.QListWidget):
    """The list under the field while an equation is typed: Global Variables, functions, constants."""

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_outside", None) is None:
            self._outside = _OutsideClick(self)
            QtWidgets.QApplication.instance().installEventFilter(self._outside)

    def hideEvent(self, event):
        super().hideEvent(event)
        outside, self._outside = getattr(self, "_outside", None), None
        if outside is not None:
            try:
                QtWidgets.QApplication.instance().removeEventFilter(outside)
            except RuntimeError:
                pass

    def __init__(self, field):
        super().__init__(field.box.window())
        self.field = field
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: field.pick(item))
        self.setMouseTracking(True)
        self.itemEntered.connect(lambda item: field.pick(item) if item.data(Qt.UserRole) == "\x01" else None)
        # the list lives on the main window: it goes with its field, or it stayed up over the next
        # page after OK closed this one with a number still being typed (and ate the next click)
        field.box.destroyed.connect(self.deleteLater)


def hide_lists():
    """Takes down every value list still up (the green check takes no keyboard focus, so a click on
    it does not end the typing: a page that stays open, a refused OK, kept the list over its fields)."""
    try:
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, _Choices) and w.isVisible():
                try:
                    w.field.hide_list()
                except Exception:
                    w.hide()
    except Exception as _fw_err:
        _fw_log("pmvalues.py:hide_lists", _fw_err)


class Field(QtCore.QObject):
    """One field: Alt steps, typed units and arithmetic, and the "=" equation."""

    def __init__(self, box):
        super().__init__(box)
        self.box = box
        self.edit = box.lineEdit() if hasattr(box, "lineEdit") else None
        self.quantity = _is_quantity(box)
        self.popup = None
        self.equation = False
        self.suggesting = False     # the unit suggestions list under a number being typed
        self.tick = None            # the grey check mark at the right end while typing
        self._buttons = None
        if self.edit is not None:
            self.edit.installEventFilter(self)
            if not self.quantity:
                self.edit.setValidator(None)        # "10in" and "10+5" may be typed
                self.edit.textEdited.connect(self._typed)
            self.edit.textEdited.connect(self._check_text)
        box.installEventFilter(self)

    # ---- Alt: a tenth of the increment
    def _alt_step(self, direction):
        step = _step(self.box) / 10.0
        _set_value(self.box, _value(self.box) + direction * step)
        if self.quantity:
            self.box.editingFinished.emit()

    # ---- typed text
    def _typed(self, text):
        self.box.setProperty("swTyped", text)

    def _take_text(self):
        """A plain field: the typed text with units or arithmetic becomes its value."""
        if self.quantity or self.edit is None or not (_whole(self.box) and _whole(self.edit)):
            return False
        text = self.edit.text()
        try:
            if text == self.box.prefix() + self.box.textFromValue(self.box.value()) + self.box.suffix():
                pmmessage.valid(self.box)       # the box's own text (10.00mm): nothing was typed
                return False                    # (pkg106: Enter on it is OK, not a value taken)
        except Exception as _fw_err:
            _fw_log("pmvalues.py:293", _fw_err)
        suffix = self.box.suffix()
        if suffix and text.endswith(suffix):
            text = text[:-len(suffix)]
        prefix = self.box.prefix()
        if prefix and text.startswith(prefix):
            text = text[len(prefix):]
        if _plain_number(text):
            pmmessage.valid(self.box)
            return False
        try:
            value = value_for(self.box, text)
        except ValueError as error:
            pmmessage.invalid(self.box, _why(text, error))
            return False
        pmmessage.valid(self.box)
        self.box.setValue(value)
        return True

    def _check_text(self, text):
        """While typing: a text that cannot be read turns the field pink (and OK grey)."""
        try:
            self._typing(text)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: unit suggestions: %s\n" % error)
        if self.equation or text.lstrip().startswith("=") or text.lstrip().startswith(MARK.strip()):
            pmmessage.valid(self.box)
            return
        raw = text
        if self.quantity:
            raw = text.strip()
        else:
            suffix = self.box.suffix()
            if suffix and raw.endswith(suffix):
                raw = raw[:-len(suffix)]
            prefix = self.box.prefix()
            if prefix and raw.startswith(prefix):
                raw = raw[len(prefix):]
        if _plain_number(raw):
            if not _out_of_range(self.box, float(raw.strip().replace(",", ".")) * _factor(self.box)):
                pmmessage.valid(self.box)
            return
        try:
            value = _evaluate_in(self.box, raw)
        except ValueError as error:
            pmmessage.invalid(self.box, _why(text, error))
            return
        if not _out_of_range(self.box, value):
            pmmessage.valid(self.box)


    def _kind(self):
        unit = "mm" if self.quantity else _unit(self.box)
        if self.quantity:
            try:
                text = self.box.property("unit") or ""
                unit = "deg" if "deg" in str(text) or "°" in self.edit.text() else "mm"
            except Exception as _fw_err:
                _fw_log("pmvalues.py:351", _fw_err)
        return {"mm": "length", "deg": "angle"}.get(unit)

    def suggestions(self, text):
        """Values built from the digits typed: "1" -> 1mm, 1in, 1cm ... and the fraction 1/4in."""
        number = text.strip()
        if not _plain_number(number) or self.equation:
            return []
        kind = self._kind()
        if kind == "length":
            out = [number + u for u in ("mm", "in", "cm", "m", "ft")]
            if "." not in number and "," not in number and len(number) == 1 and number != "0":
                out.insert(2, number + "/4in")
            return out
        if kind == "angle":
            return [number + "deg", number + "rad"]
        return []

    def _typing(self, text):
        if self.edit is None or self.equation or text.lstrip().startswith("="):
            return
        self._show_tick(True)
        raw = text
        if not self.quantity:
            for cut in (self.box.suffix(), ):
                if cut and raw.endswith(cut):
                    raw = raw[:-len(cut)]
        items = self.suggestions(raw)
        if not items:
            if self.suggesting:
                self.hide_list()
            return
        if self.popup is None:
            self.popup = _Choices(self)
        self.popup.clear()

        more = QtWidgets.QListWidgetItem("Units  \u25b8")
        more.setData(Qt.UserRole, "\x01")
        self.popup.addItem(more)
        row = self.popup.sizeHintForRow(0) or 18
        self.popup.setFixedSize(max(self.box.width(), 120), row * self.popup.count() + 2 * self.popup.frameWidth() + 2)
        # beside the field, not under it: under it the list covered the next field (Draft angle under Depth) and the
        # click meant for that field picked a unit (30mm became 30in). Its own rows still take a click.
        self.popup.move(_beside(self.box, self.popup))
        self.popup.setCurrentRow(-1)
        self.suggesting = True
        try:
            from . import pmunits
            pmunits._hide_popup()       # the older Units chooser: this list has its Units row
        except Exception as _fw_err:
            _fw_log("pmvalues.py:402", _fw_err)
        self.popup.show()
        self.popup.raise_()

    def _units_menu(self):
        from . import pmunits
        old = getattr(self, "_menu", None)
        if old is not None and _alive(old) and old.isVisible():
            return old
        menu = QtWidgets.QMenu(self.box)
        menu.setObjectName("SWValueUnits")
        units = [u for u, _f in pmunits.UNITS] if self._kind() == "length" else ["deg", "rad"]
        for unit in units:
            menu.addAction(unit, lambda u=unit: self._replace(self._bare() + u))
        self._menu = menu
        popup = self.popup
        if popup is not None and _alive(popup) and popup.isVisible() and popup.count():

            rect = popup.visualItemRect(popup.item(popup.count() - 1))
            popup.setCurrentRow(popup.count() - 1)
            menu.popup(popup.viewport().mapToGlobal(QtCore.QPoint(rect.right() + 2, rect.top())))
        else:
            menu.popup(self.box.mapToGlobal(QtCore.QPoint(self.box.width(), self.box.height())))
        return menu

    def _bare(self):
        text = self.edit.text().strip()
        m = re.match(r"\s*([+-]?[\d.,]+)", text)
        return m.group(1) if m else text

    def _replace(self, value):
        menu = getattr(self, "_menu", None)
        if menu is not None and _alive(menu) and menu.isVisible():
            menu.close()
        self.edit.setText(value)
        self.edit.setCursorPosition(len(value))
        self.edit.setFocus()
        self.hide_list()
        self._check_text(value)
        self.hide_list()

    def _show_tick(self, on):
        if self.edit is None:
            return
        if self.tick is None:
            pix = QtGui.QPixmap(14, 14)
            pix.fill(Qt.transparent)
            p = QtGui.QPainter(pix)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(QtGui.QColor(128, 128, 128), 2)
            p.setPen(pen)
            p.drawPolyline([QtCore.QPointF(2, 7), QtCore.QPointF(6, 11), QtCore.QPointF(12, 3)])
            p.end()
            self.tick = self.edit.addAction(QtGui.QIcon(pix), QtWidgets.QLineEdit.TrailingPosition)
            self.tick.setObjectName("SWValueTick")
            self.tick.setToolTip("Take the value")
            self.tick.triggered.connect(self.commit)
        self.tick.setVisible(on)
        # FreeCAD's fx label sits over the right end of a quantity box: the check mark takes its place
        for label in self.edit.findChildren(QtWidgets.QLabel):
            if on and label.isVisible():
                label.setProperty("swHiddenForTick", True)
                label.hide()
            elif not on and label.property("swHiddenForTick"):
                label.setProperty("swHiddenForTick", False)
                label.show()
        if hasattr(self.box, "setButtonSymbols"):
            if on and self._buttons is None:
                self._buttons = self.box.buttonSymbols()
                self.box.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            elif not on and self._buttons is not None:
                self.box.setButtonSymbols(self._buttons)
                self._buttons = None

    def done_typing(self):
        self.suggesting = False
        self.hide_list()
        self._show_tick(False)

    def commit(self):
        """The check mark: the value is taken, as Enter does."""
        self.done_typing()
        if not self.quantity and self._take_text():
            self.box.editingFinished.emit()
            return
        ev = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
        QtWidgets.QApplication.sendEvent(self.edit, ev)
        self.box.editingFinished.emit()

    # ---- the equation
    def start_equation(self):
        self.equation = True
        self.hide_list()
        if self.edit is not None:
            self.edit.setText("=")
            self.edit.setCursorPosition(1)
        self.show_list()

    def end_equation(self):
        self.equation = False
        self.hide_list()

    def choices(self):
        obj = _edited_object()
        dialog = Gui.Control.activeDialog()
        panel_obj = getattr(dialog, "obj", None) if dialog else None
        doc = (panel_obj or obj).Document if (panel_obj or obj) is not None else App.ActiveDocument
        out = []
        if doc is not None:
            for name, raw, got in equations.variables(doc):
                shown = got if got is not None else raw
                out.append(('"%s"' % name, "%s = %s" % (name, shown), "Global Variables"))
        for f in FUNCTIONS:
            out.append((f, f, "Functions"))
        for c in CONSTANTS:
            out.append((c, c, "Constants"))
        return out

    def show_list(self):
        if self.popup is None:
            self.popup = _Choices(self)
        self.popup.clear()
        group = None
        for insert, shown, kind in self.choices():
            if kind != group:
                group = kind
                head = QtWidgets.QListWidgetItem(kind)
                head.setFlags(Qt.NoItemFlags)
                font = head.font()
                font.setBold(True)
                head.setFont(font)
                self.popup.addItem(head)
            item = QtWidgets.QListWidgetItem("    " + shown)
            item.setData(Qt.UserRole, insert)
            self.popup.addItem(item)
        rows = min(self.popup.count(), 12)
        row = self.popup.sizeHintForRow(0) if self.popup.count() else 18
        self.popup.setFixedSize(max(self.box.width(), 180), row * rows + 2 * self.popup.frameWidth() + 2)
        self.popup.move(self.box.mapToGlobal(QtCore.QPoint(0, self.box.height())))
        self.popup.setCurrentRow(-1)
        self.popup.show()
        self.popup.raise_()

    def hide_list(self):
        self.suggesting = False
        if self.popup is not None:
            self.popup.hide()

    def shown(self):
        return self.popup is not None and self.popup.isVisible()

    def pick(self, item):
        insert = item.data(Qt.UserRole)
        if not insert or self.edit is None:
            return
        if insert == "\x01":
            self._units_menu()
            return
        if insert.startswith("\x00"):
            self._replace(insert[1:])
            return
        text = self.edit.text()
        pos = self.edit.cursorPosition()
        self.edit.setText(text[:pos] + insert + text[pos:])
        at = pos + len(insert)
        if insert.endswith(")"):
            at = pos + insert.index("(") + 1       # inside the brackets
        self.edit.setCursorPosition(at)
        self.edit.setFocus()
        self.hide_list()

    def _move(self, down):
        rows = [i for i in range(self.popup.count()) if self.popup.item(i).flags() & Qt.ItemIsSelectable]
        if not rows:
            return
        cur = self.popup.currentRow()
        if cur not in rows:
            self.popup.setCurrentRow(rows[0] if down else rows[-1])
            return
        i = rows.index(cur) + (1 if down else -1)
        self.popup.setCurrentRow(rows[max(0, min(len(rows) - 1, i))])

    def _link(self, tab=False):
        ""
        text = self.edit.text().strip()
        if text.startswith(MARK.strip()):
            text = text[1:].strip()
        if not text.startswith("="):
            self.end_equation()
            return False
        if binding(self.box) is None:
            # a field with no property behind it yet (the page makes its feature on OK): the equation's

            # Variable ("R1") is kept for the page, which links its feature to it on OK (Σ)
            try:
                value = _equation_value(self.box, text[1:])
            except ValueError as error:
                pmmessage.invalid(self.box, "The equation \"%s\" could not be worked out." % text)
                _fw_log("pmvalues.py:link-plain", error)
                self.edit.selectAll()
                return True
            pmmessage.valid(self.box)
            self.end_equation()
            linked = _names_something(text[1:])
            set_pending(self.box, text[1:].strip() if linked else "", value)    # before the value: the page rebuilds on it
            _set_value(self.box, value)
            if linked and self.edit is not None:
                self.edit.setText(MARK + self.edit.text())
            self.box.editingFinished.emit()
            return not tab
        try:
            value = link(self.box, text[1:].strip())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: equation not taken: %s\n" % error)
            pmmessage.invalid(self.box, "The equation \"%s\" could not be worked out." % text)
            self.edit.selectAll()
            return True
        pmmessage.valid(self.box)
        self.end_equation()
        if value is not None:
            self.show_result(value)
        return not tab

    def show_result(self, value):
        ""
        _set_value(self.box, value)
        if self.edit is not None:
            self.edit.setText(MARK + self.edit.text())

    def _show_linked(self):
        """After the focus leaves a field linked to an equation: its result again, with Σ."""
        if not (_whole(self.box) and _whole(self.edit)) or self.edit.hasFocus():
            return
        bound = binding(self.box)
        if bound is None:
            return
        obj, prop = bound
        if self.edit.text().startswith(MARK.strip()) and self.edit.text().rstrip()[-1:].isalpha():
            return
        blocked = self.box.blockSignals(True)
        try:
            value = getattr(obj, prop)
            if hasattr(value, "Unit"):
                self.box.setProperty("value", value)    # the unit too: the re-read lost it
            else:
                _set_value(self.box, float(value))
            self.edit.setText(MARK + self.edit.text().lstrip(MARK.strip()).strip())
        except Exception as _fw_err:
            _fw_log("pmvalues.py:show_linked", _fw_err)
        finally:
            self.box.blockSignals(blocked)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        kind = event.type()
        if kind in (QtCore.QEvent.FocusOut, QtCore.QEvent.Hide, QtCore.QEvent.KeyPress) and not (_whole(self.box) and _whole(self.edit)):
            return False        # the panel is closing: nothing to take
        if kind == QtCore.QEvent.Wheel and watched is self.box:
            if event.modifiers() & Qt.AltModifier:
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    self._alt_step(1 if delta > 0 else -1)
                return True
            return False
        if kind == QtCore.QEvent.KeyPress:
            key, mods = event.key(), event.modifiers()
            if key in (Qt.Key_Up, Qt.Key_Down) and (mods & Qt.AltModifier) and not self.shown():
                self._alt_step(1 if key == Qt.Key_Up else -1)
                return True
            if self.edit is not None and (watched is self.edit or watched is self.box):
                text = self.edit.text()
                all_selected = self.edit.hasSelectedText() and self.edit.selectedText() == text
                if event.text() == "=" and (all_selected or not text or self.edit.cursorPosition() == 0
                                            or text.startswith(MARK.strip())):
                    self.start_equation()
                    return True
                if self.equation or text.lstrip().startswith("="):
                    if self.shown():
                        if key in (Qt.Key_Down, Qt.Key_Up):
                            self._move(key == Qt.Key_Down)
                            return True
                        if key in (Qt.Key_Return, Qt.Key_Enter) and self.popup.currentItem() is not None:
                            self.pick(self.popup.currentItem())
                            return True
                        if key == Qt.Key_Escape:
                            self.hide_list()
                            return True
                    if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                        return self._link(tab=key == Qt.Key_Tab)
                    if key == Qt.Key_Escape:
                        self.end_equation()
                        return False
                    return False
                if self.suggesting and self.shown():
                    if key in (Qt.Key_Down, Qt.Key_Up):
                        self._move(key == Qt.Key_Down)
                        return True
                    if key in (Qt.Key_Return, Qt.Key_Enter) and self.popup.currentItem() is not None:
                        self.pick(self.popup.currentItem())
                        return True
                    if key == Qt.Key_Escape:
                        self.hide_list()
                        return True
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Backtab, Qt.Key_Escape):
                    self.done_typing()
                if key in (Qt.Key_Return, Qt.Key_Enter) and not self.quantity and self._take_text():
                    self.box.editingFinished.emit()
                    return True
                if key in (Qt.Key_Tab, Qt.Key_Backtab) and not self.quantity and self._take_text():
                    self.box.editingFinished.emit()
                    return False                        # and the focus goes on
        if kind == QtCore.QEvent.FocusOut and watched is self.box and not self.quantity and not self.shown() \
                and not self.equation:
            if self._take_text():               # the box gets the focus-out (its line edit is a proxy):
                self.box.editingFinished.emit() # read "0.5in" before Qt puts the old value back
        if kind == QtCore.QEvent.Hide and watched is self.box and self.shown():
            self.hide_list()                    # the page closed (OK) with the list still up
        if kind == QtCore.QEvent.FocusOut and self.quantity and self.box.property(EQ) and not self.equation:
            QtCore.QTimer.singleShot(0, self._show_linked)  # FreeCAD's box re-reads "Σ 20.00 mm" as 0.00
        if kind == QtCore.QEvent.FocusOut and watched is self.edit and not self.shown():
            self._show_tick(False)
        if kind == QtCore.QEvent.FocusOut and watched is self.edit:
            if self.shown():
                QtCore.QTimer.singleShot(150, lambda: (not _alive(self.edit) or not self.edit.hasFocus()) and self.hide_list())
            elif not self.quantity:
                self._take_text()
        if kind == QtCore.QEvent.ShortcutOverride and watched is self.edit and self.equation:
            event.accept()      # the letters are ours, not the window's shortcuts
            return True
        return False


_reverse = {}


def reverse_icon():
    ""

    icon = _reverse.get("icon")
    if icon is not None:
        return icon
    icon = icons.family("PM_REVERSE_DIRECTION") if icons.available() else QtGui.QIcon()
    if not icons.paints(icon):
        icon = QtGui.QIcon()
        for size in (16, 20, 24, 32):
            pix = QtGui.QPixmap(size, size)
            pix.fill(Qt.transparent)
            painter = QtGui.QPainter(pix)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            pen = QtGui.QPen(QtGui.QColor("#2b6fd6"), max(1.5, size / 10.0), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor("#2b6fd6"))
            m, head = size * 0.15, size * 0.22
            xl, xr = size * 0.33, size * 0.67
            painter.drawLine(QtCore.QPointF(xl, size - m), QtCore.QPointF(xl, m + head * 0.6))
            painter.drawLine(QtCore.QPointF(xr, m), QtCore.QPointF(xr, size - m - head * 0.6))
            up = QtGui.QPolygonF([QtCore.QPointF(xl, m), QtCore.QPointF(xl - head * 0.7, m + head), QtCore.QPointF(xl + head * 0.7, m + head)])
            down = QtGui.QPolygonF([QtCore.QPointF(xr, size - m), QtCore.QPointF(xr - head * 0.7, size - m - head), QtCore.QPointF(xr + head * 0.7, size - m - head)])
            painter.drawPolygon(up)
            painter.drawPolygon(down)
            painter.end()
            icon.addPixmap(pix)
    _reverse["icon"] = icon
    return icon


def install(view):
    """Every spin box on the page gets its Field (once)."""
    for box in view.findChildren(QtWidgets.QAbstractSpinBox):
        if box.property(DONE):
            continue
        box.setProperty(DONE, True)
        if isinstance(box, QtWidgets.QSpinBox):
            _watch_count(box)
            continue
        Field(box)


def _watch_count(box):
    edit = box.lineEdit()

    def check(text, box=box):
        raw = text
        if box.suffix() and raw.endswith(box.suffix()):
            raw = raw[:-len(box.suffix())]
        if box.prefix() and raw.startswith(box.prefix()):
            raw = raw[len(box.prefix()):]
        try:
            value = int(raw.strip())
        except ValueError:
            pmmessage.valid(box)
            return
        if not _out_of_range(box, value):
            pmmessage.valid(box)
    if edit is not None:
        edit.textEdited.connect(check)
