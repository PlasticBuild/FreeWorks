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

import math
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets, QtGui

INTERVAL = 250          # ms, while a page is open
DONE = "fw_length_unit"     # the unit factor a box was given (1.0: the part is in mm, nothing done)
KEEP = "fw_keep_mm"
# the suffix a box is made with -> the power of the length it holds
POWERS = {"mm": 1, "mm²": 2, "mm^2": 2, "mm2": 2, "mm³": 3, "mm^3": 3, "mm3": 3}
MARKS = {1: "", 2: "²", 3: "³"}
_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "\"": 25.4, "ft": 304.8, "'": 304.8, "um": 0.001,
          "µm": 0.001, "mil": 0.0254, "thou": 0.0254}
_NUM = re.compile(r"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-zµ\"']*)\s*([²³23]?)\s*$")
_state = {"timer": None}


def _python_made(w):
    """A box made from Python: only its overrides reach Qt (a box made by FreeCAD's C++ is left alone)."""
    try:
        try:
            from shiboken6 import createdByPython
        except ImportError:
            from shiboken2 import createdByPython
        return bool(createdByPython(w))
    except Exception:
        return False


def unit(doc=None):
    """(symbol, mm) of the part's length unit."""
    try:
        from . import unitspage
        sym, mm = unitspage.length_unit(doc or App.ActiveDocument)
        return sym, float(mm)
    except Exception as _fw_err:
        _fw_log("pmlength:unit", _fw_err)
        return "mm", 1.0


def _power(suffix):
    return POWERS.get((suffix or "").strip())


def parse(text, sym, k, power=1):
    """A typed length in mm (mm², mm³): a bare number is in the part's unit, a unit typed after it is kept
    (25mm, 1in). None when it is no number."""
    t = (text or "").strip()
    shown = " " + sym + MARKS[power]
    if t.endswith(shown.strip()):
        t = t[:-len(shown.strip())]
    m = _NUM.match(t)
    if m is None:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    u = m.group(2)
    if u == "":
        f = k
    elif u.lower() in _UNITS or u in _UNITS:
        f = _UNITS.get(u, _UNITS.get(u.lower()))
    else:
        return None
    return v * f ** power if math.isfinite(v) else None


_TERM = re.compile(r"(\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)(\s*[A-Za-zµ\"'°]+)?")


def bare_terms(text, sym):
    ""

    out, last = [], 0
    for m in _TERM.finditer(text):
        out.append(text[last:m.end()])
        last = m.end()
        if m.group(2):
            continue
        before = text[:m.start()].rstrip()
        after = text[m.end():].lstrip()
        if (before[-1:] in ("", "+", "-", "(")) and (after[:1] in ("", "+", "-", ")")) \
                and before[-2:-1] not in ("*", "/"):
            out.append(sym)
    out.append(text[last:])
    return "".join(out)


def _skip(w):
    if w.property(KEEP):
        return True
    p = w
    while p is not None:
        try:
            if "slicer" in p.objectName().lower() or p.property(KEEP):
                return True
        except Exception:
            return True
        p = p.parentWidget()
    return False


def convert(box, doc=None):
    """Give one millimetre box the part's unit (once). True when it shows another unit now."""
    if box.property(DONE) is not None:
        return float(box.property(DONE)) != 1.0
    power = _power(box.suffix())
    if power is None or not _python_made(box) or _skip(box):
        return False
    sym, k = unit(doc)
    box.setProperty(DONE, k)
    state = {"on": True, "power": power, "step": box.singleStep(), "dec": box.decimals()}
    real_set_suffix = box.setSuffix
    real_suffix = box.suffix

    def factor():
        return k ** state["power"]

    def mark():
        # pmvalues and pmunits read these: the box holds mm and shows the part's unit
        box.setProperty("fw_length_factor", factor() if state["on"] else 1.0)
        box.setProperty("fw_length_power", state["power"] if state["on"] else 0)

    def shown_decimals():

        return length_decimals()

    def text_from_value(v):
        if not state["on"]:
            if real_suffix() in ANGLE_SUFFIXES:
                return "%.*f" % (angle_decimals(doc), v)
            return _shown(v, state["dec"])
        return _shown(v / factor(), shown_decimals())

    def value_from_text(text):
        if _unchanged(box, text, text_from_value):
            return box.value()          # the rounded text read back keeps the finer value (12.125 shown 12.13mm)
        if not state["on"]:
            t = text.strip()
            s = real_suffix().strip()
            if s and t.endswith(s):
                t = t[:-len(s)]
            try:
                return float(t.strip().replace(",", "."))
            except ValueError:
                return box.value()
        v = parse(text, sym, k, state["power"])
        return box.value() if v is None else v

    def validate(text, pos):
        t = text
        s = real_suffix()
        if state["on"]:
            v = parse(t, sym, k, state["power"])
        else:
            u = t.strip()
            if s.strip() and u.endswith(s.strip()):
                u = u[:-len(s.strip())]
            try:
                v = float(u.strip().replace(",", "."))
            except ValueError:
                v = None
        if v is None:
            return (QtGui.QValidator.Intermediate, text, pos)
        if v < box.minimum() - 1e-9 or v > box.maximum() + 1e-9:
            return (QtGui.QValidator.Intermediate, text, pos)
        return (QtGui.QValidator.Acceptable, text, pos)

    def set_suffix(s):
        p = _power(s)
        if p is None:                   # " %", "°": the box holds no length now
            if state["on"]:
                state["on"] = False
                box.setSingleStep(state["step"])
            mark()
            real_set_suffix(s)
            return
        shown = " " + sym + MARKS[p]
        if state["on"] and state["power"] == p and real_suffix() == shown:
            return                      # a page setting " mm" again on each refresh: the text typed stays
        state["power"] = p
        if not state["on"]:
            state["on"] = True
            state["step"] = box.singleStep()
            box.setSingleStep(state["step"] * 0.1 * factor() if p == 1 and k != 1.0 else state["step"])
        mark()
        real_set_suffix(shown)

    box.blockSignals(True)
    try:
        v = box.value()
        if box.decimals() < state["dec"] + 2:
            box.setDecimals(state["dec"] + 2)       # mm kept finer than the unit shown: 0.0625 in stays
        box.textFromValue = text_from_value
        box.valueFromText = value_from_text
        box.validate = validate
        box.setSuffix = set_suffix
        mark()
        if power == 1 and k != 1.0:
            box.setSingleStep(state["step"] * 0.1 * k)    # 0.1 in a step, as 1 mm was
        real_set_suffix(" " + sym + MARKS[power])
        box.setValue(v)
    finally:
        box.blockSignals(False)
    try:
        tip = box.toolTip()
        box.setProperty("fw_length_symbol", sym)
        if tip and "mm" in tip and sym not in tip:
            box.setToolTip(tip.replace(" mm", " " + sym))
    except Exception as _fw_err:
        _fw_log("pmlength:tip", _fw_err)
    return True


ANGLE_SUFFIXES = ("°", " °", "deg", " deg")
ANGLE_DONE = "fw_angle_decimals"


def length_decimals():
    try:
        from . import unitspage
        return max(0, int(unitspage.length_decimals()))
    except Exception:
        return 2


def angle_decimals(doc=None):
    try:
        from . import unitspage
        return max(0, int(unitspage.angle_decimals(doc)))
    except Exception:
        return 2


def _shown(v, dec):
    ""

    from decimal import Decimal, ROUND_HALF_UP
    try:
        d = Decimal(repr(float(v))).quantize(Decimal(1).scaleb(-int(dec)), rounding=ROUND_HALF_UP)
    except Exception:
        return "%.*f" % (dec, v)
    text = "%.*f" % (int(dec), d)
    return "0." + "0" * int(dec) if dec and text.strip("-0.") == "" else text      # never "-0.00"


def _unchanged(box, text, text_from_value):
    """True when text is what the box shows for its own value: nothing was typed, so the value stays as it is."""
    try:
        shown = text_from_value(box.value()).strip()
        t = text.strip()
        return t == shown or t.startswith(shown) and not t[len(shown):].strip(" 0123456789.,-+")
    except Exception:
        return False


# boxes a page already shows in the part's unit (evaluate.unit_spin, Plane offset...): only their decimals
SHOWN_UNITS = (" in", " cm", " m", " ft", " in²", " in³", " cm²", " cm³", " m²", " m³")


def convert_angle(box, doc=None):
    """An angle box shows Document Properties > Units > Angle decimals (90.00°), its value as it is; a box a page
    already shows in the part's unit shows the Length decimals (it keeps its own finer value)."""
    if box.property(ANGLE_DONE) is not None or box.property(DONE) is not None:
        return False
    suffix = box.suffix()
    if suffix not in ANGLE_SUFFIXES + SHOWN_UNITS or not _python_made(box) or _skip(box):
        return False
    n = angle_decimals(doc) if suffix in ANGLE_SUFFIXES else length_decimals()
    box.setProperty(ANGLE_DONE, n)
    real_suffix = box.suffix

    def text_from_value(v):
        now = real_suffix()
        if now in ANGLE_SUFFIXES:
            return "%.*f" % (angle_decimals(doc), v)
        if now in SHOWN_UNITS:
            return _shown(v, length_decimals())
        return QtCore.QLocale().toString(float(v), "f", box.decimals())   # the page turned it to another kind

    def number(text):
        t = text.strip()
        for cut in (real_suffix().strip(), "°", "deg"):
            if cut and t.endswith(cut):
                t = t[:-len(cut)].strip()
        try:
            return float(t.replace(",", "."))
        except ValueError:
            return None

    def value_from_text(text):
        if _unchanged(box, text, text_from_value):
            return box.value()
        v = number(text)
        return box.value() if v is None else v

    def validate(text, pos):
        v = number(text)
        if v is None or v < box.minimum() - 1e-9 or v > box.maximum() + 1e-9:
            return (QtGui.QValidator.Intermediate, text, pos)
        return (QtGui.QValidator.Acceptable, text, pos)

    box.blockSignals(True)
    try:
        v = box.value()
        if box.decimals() < n:
            box.setDecimals(n)
        box.textFromValue = text_from_value
        box.valueFromText = value_from_text
        box.validate = validate
        box.setValue(v)
        box.setSuffix(real_suffix())        # the text again, with the decimals
    finally:
        box.blockSignals(False)
    return True


# a length written in a page's text: "12.50 mm", "0.5mm", "3 mm²" (not "mm" inside a word, not "(mm)")
_TEXT_LEN = re.compile(r"(?<![\w.])(-?\d+(?:[.,]\d+)?)(\s?)mm(²|³|\^2|\^3)?(?![\w(])")
_TEXT_CHAIN = re.compile(r"(?<![\w.])((?:-?\d+(?:\.\d+)?\s*[x×]\s*)+-?\d+(?:\.\d+)?|"
                         r"-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?)(\s?)mm(?![\w(²³^/])")
_NUMBER_IN = re.compile(r"-?\d+(?:\.\d+)?")
SHOWN = "fw_length_text"        # the text a label shows after its lengths were put in the part's unit
_TEXT_POWERS = {None: 1, "": 1, "²": 2, "^2": 2, "³": 3, "^3": 3}


def convert_text(text, sym, k):
    """The lengths in a text in the part's unit: "Belt length: 254.00 mm" -> "Belt length: 10.000 in"."""
    if not text or "mm" not in text or k == 1.0:
        return text

    def one(m):
        try:
            v = float(m.group(1).replace(",", "."))
        except ValueError:
            return m.group(0)
        power = _TEXT_POWERS.get(m.group(3), 1)
        places = length_decimals()             # Document Properties > Units > Length decimals
        return "%.*f%s%s%s" % (places, v / k ** power, m.group(2) or " ", sym, MARKS[power])
    def chain(m):
        # "20 x 30 x 5 mm", "1.000, 2.000, 3.000 mm": each number of the list is a length
        nums = _NUMBER_IN.findall(m.group(1))
        out = m.group(1)
        parts = _NUMBER_IN.split(m.group(1))
        res = []
        for i, piece in enumerate(parts):
            res.append(piece)
            if i < len(nums):
                res.append(one(_TEXT_LEN.match(nums[i] + " mm")).rsplit(" ", 1)[0])
        return "".join(res) + m.group(2) + sym
    text = _TEXT_CHAIN.sub(chain, text)
    return _TEXT_LEN.sub(one, text)


def _label_row_box(label):
    """The box a form row puts beside a "Margin (mm)" label, when it is a plain number box with no unit."""
    p = label.parentWidget()
    lay = p.layout() if p is not None else None
    if not isinstance(lay, QtWidgets.QFormLayout):
        return None
    for r in range(lay.rowCount()):
        it = lay.itemAt(r, QtWidgets.QFormLayout.LabelRole)
        if it is not None and it.widget() is label:
            f = lay.itemAt(r, QtWidgets.QFormLayout.FieldRole)
            w = f.widget() if f is not None else None
            if isinstance(w, QtWidgets.QDoubleSpinBox) and not w.suffix().strip() and _python_made(w):
                return w
    return None


def sweep_text(root, doc=None):
    """The page's own labels in the part's unit: lengths written in them, and a "(mm)" row label whose box has no
    unit (the box takes the unit after it, the label drops it). The number of labels changed."""
    sym, k = unit(doc)
    if root is None or k == 1.0:
        return 0
    n = 0
    for label in root.findChildren(QtWidgets.QLabel):
        try:
            text = label.text()
            if not text or "mm" not in text or label.property(KEEP) or text == label.property(SHOWN):
                continue
            if not _python_made(label) or _skip(label):
                continue
            new = text
            for tag in (" (mm)", "(mm)", " [mm]"):
                if tag in new:
                    box = _label_row_box(label)
                    if box is not None and box.property(DONE) is None:
                        box.setSuffix(" mm")
                        convert(box, doc)
                        new = new.replace(tag, "")
                    break
            new = convert_text(new, sym, k)
            label.setProperty(SHOWN, new)
            if new != text:
                label.setText(new)
                n += 1
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmlength:text", _fw_err)
    return n


_ITEM_SHOWN = int(QtCore.Qt.UserRole) + 0x6d6d      # an item's text after its lengths were put in the part's unit


def _item_text(item, col, sym, k):
    """One read-only cell or tree row: its lengths in the part's unit (a cell one types in is left to its page)."""
    text = item.text(col) if col is not None else item.text()
    if not text or "mm" not in text:
        return 0
    shown = item.data(col, _ITEM_SHOWN) if col is not None else item.data(_ITEM_SHOWN)
    if text == shown:
        return 0
    if item.flags() & QtCore.Qt.ItemIsEditable:
        return 0
    new = convert_text(text, sym, k)
    if col is not None:
        item.setData(col, _ITEM_SHOWN, new)
        if new != text:
            item.setText(col, new)
    else:
        item.setData(_ITEM_SHOWN, new)
        if new != text:
            item.setText(new)
    return int(new != text)


def sweep_items(root, doc=None):
    """Read-only result tables and lists on the page (Clearance, DFMXpress, Costing...) in the part's unit."""
    sym, k = unit(doc)
    if root is None or k == 1.0:
        return 0
    n = 0
    for view in root.findChildren(QtWidgets.QAbstractItemView):
        try:
            if not _python_made(view) or _skip(view) or not view.isVisible():
                continue
            if isinstance(view, QtWidgets.QTableWidget):
                for r in range(view.rowCount()):
                    for c in range(view.columnCount()):
                        it = view.item(r, c)
                        if it is not None:
                            n += _item_text(it, None, sym, k)
            elif isinstance(view, QtWidgets.QTreeWidget):
                it = QtWidgets.QTreeWidgetItemIterator(view)
                while it.value() is not None:
                    item = it.value()
                    for c in range(view.columnCount()):
                        n += _item_text(item, c, sym, k)
                    it += 1
            elif isinstance(view, QtWidgets.QListWidget):
                for r in range(view.count()):
                    n += _item_text(view.item(r), None, sym, k)
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmlength:items", _fw_err)
    return n


def sweep(root, doc=None):
    """Every millimetre box under root in the part's unit, and the lengths its labels write. The number of boxes and
    labels changed."""
    if root is None:
        return 0
    n = 0
    for box in root.findChildren(QtWidgets.QDoubleSpinBox):
        try:
            if box.property(DONE) is None and convert(box, doc):
                n += 1
            elif box.property(ANGLE_DONE) is None and convert_angle(box, doc):
                n += 1
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmlength:sweep", _fw_err)
    return n + sweep_text(root, doc) + sweep_items(root, doc)


def _roots():
    out = []
    try:
        from . import pmnogrey
        if Gui.Control.activeDialog():
            out.append(pmnogrey.task_view())
        out.append(pmnogrey.tool_page())
    except Exception as _fw_err:
        _fw_log("pmlength:roots", _fw_err)
    try:
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QDialog) and w.isVisible() and _python_made(w):
                out.append(w)       # the add-on's own dialogs (Curve File, Modify...)
    except Exception as _fw_err:
        _fw_log("pmlength:dialogs", _fw_err)
    return [r for r in out if r is not None]


def _tick():
    doc = App.ActiveDocument
    if doc is None:
        return
    try:
        for r in _roots():
            sweep(r, doc)
    except Exception as _fw_err:
        _fw_log("pmlength:tick", _fw_err)


def install():
    if _state["timer"] is not None:
        return
    t = QtCore.QTimer(Gui.getMainWindow())
    t.setInterval(INTERVAL)
    t.timeout.connect(_tick)
    t.start()
    _state["timer"] = t
