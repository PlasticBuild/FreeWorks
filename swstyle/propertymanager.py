# SPDX-License-Identifier: LGPL-2.1-or-later
""














from . import editobj

_FW_SEEN = set()



def _alive(obj):
    """False for None or an object deleted under its wrapper (teardown.alive, review 1119)."""
    from . import teardown
    return teardown.alive(obj)


def _doc_alive(doc):
    from . import teardown
    return teardown.doc_alive(doc)


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

import string

from . import contours, filletchamfer, icons, multibody, pmboxes, pmfields, pmhandles, pmkeys, pmmessage, pmpreview, pmvalues, selectionbox, pmlayout, pmundo

try:
    from . import style as theme   # the look's themes: Light, Dark, AMOLED
except Exception:
    theme = None

pmkeys.start()

# The Light theme's values, for when the look's style module is missing.
_LIGHT_TOKENS = {
    "pane": "#f7f7f7", "line_light": "#d5d5d5", "line_mid": "#a9a9a9", "text": "#000000",
    "text_disabled": "#9a9a9a", "base": "#ffffff", "selection": "#cce4f7", "accent": "#5a9bd5",
    "field_line": "#c3c3c3", "hover": "#f0f0f0", "menu_hover": "#e5f1fb", "hover_line": "#9cc8ee",
    "arrow": "#404040", "field": "#ffffff", "field_text": "#000000",
}


def _token(name):
    if theme is not None:
        try:
            return theme.T.hex(name)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:58", _fw_err)
    return _LIGHT_TOKENS[name]

Qt = QtCore.Qt
HEADER = "SWStyle_PMHeader"


TITLES = {
    "PartDesign::Pad": ("Boss-Extrude", "FEATURES_EXTRUDE_BOSS"),
    "PartDesign::Pocket": ("Cut-Extrude", "FEATURES_EXTRUDE_CUT"),
    "PartDesign::Revolution": ("Revolve", "FEATURES_REVOLVED_BOSS_BASE"),
    "PartDesign::Groove": ("Cut-Revolve", "FEATURES_REVOLVED_CUT"),
    "PartDesign::AdditivePipe": ("Sweep", "FEATURES_SWEPT_BOSS"),
    "PartDesign::SubtractivePipe": ("Cut-Sweep", "FEATURES_SWEPT_CUT"),
    "PartDesign::AdditiveLoft": ("Loft", "FEATURES_LOFTED_BOSS"),
    "PartDesign::SubtractiveLoft": ("Cut-Loft", "FEATURES_LOFTED_CUT"),
    "PartDesign::AdditiveHelix": ("Helix Boss", "FEATURES_SWEPT_BOSS"),
    "PartDesign::SubtractiveHelix": ("Helix Cut", "FEATURES_SWEPT_CUT"),
    "PartDesign::Hole": ("Hole Specification", "FEATURES_HOLE_WIZARD"),
    "PartDesign::Fillet": ("Fillet", "FEATURES_FILLET"),
    "PartDesign::Chamfer": ("Chamfer", "FEATURES_CHAMFER"),
    "PartDesign::Draft": ("Draft", "FEATURES_DRAFT"),
    "PartDesign::Thickness": ("Shell", "FEATURES_SHELL"),
    "PartDesign::Mirrored": ("Mirror", "FEATURES_MIRROR"),
    "PartDesign::LinearPattern": ("Linear Pattern", "FEATURES_LINEAR_PATTERN"),
    "PartDesign::PolarPattern": ("Circular Pattern", "FEATURES_CIRCULAR_PATTERN"),
    "PartDesign::MultiTransform": ("Pattern", "FEATURES_MIRROR_PATTERN"),
    "PartDesign::Scaled": ("Scale", "FEATURES_SCALE"),
    "PartDesign::Boolean": ("Combine", "FEATURES_COMBINE"),
    "PartDesign::Plane": ("Plane", "REFGEO_PLANE"),
    "PartDesign::Line": ("Axis", "REFGEO_AXIS"),
    "PartDesign::Point": ("Point", "REFGEO_POINT"),
    "PartDesign::CoordinateSystem": ("Coordinate System", "REFGEO_CSYS"),
    "Sketcher::SketchObject": ("Sketch", "SKETCH_SKETCH"),
}


# panel #f7f7f7, group separators #d5d5d5, fields white with a #a9a9a9 frame,
# bold group titles with the fold arrow on the right, no frames around groups.
_RULES = """
* { background: transparent; }
QWidget#PMRoot { background: ${pane}; }
QScrollArea, QScrollArea > QWidget > QWidget, QSint--ActionPanel, Gui--TaskView--TaskPanel,
QSint--ActionGroup, Gui--TaskView--TaskBox { background: ${pane}; border: none; }
QFrame[class="header"] {
    background: transparent;
    border: none;
    border-top: 1px solid ${line_light};
    min-height: 24px;
}
QSint--ActionLabel[class="header"], QToolButton[class="header"] {
    background: transparent;
    border: none;
    color: ${text};
    font-weight: bold;
    text-align: left;
    padding: 2px 2px;
}
QFrame[class="separator"] { border: none; background: transparent; max-height: 0px; }
QFrame[class="content"] { background: transparent; border: none; padding: 0px 8px 0px 0px; }
QListWidget, QListView, QTreeWidget, QTableWidget, QTableView {
    background: ${field};
    color: ${field_text};
    border: 1px solid ${line_mid};
    selection-background-color: ${selection};
    selection-color: ${text};
    alternate-background-color: ${field};   /* SolidWorks' PM tables have no stripes; the Dark look's
                                               dark stripe hid the black text (Draft Analysis Results) */
}
QTableWidget QHeaderView, QTableView QHeaderView { background: ${field}; }   /* the strip under the last row (Dark) */
QListWidget:focus, QListView:focus, QListWidget[swActive="true"] { background: #cce4f7; color: #000000; border: 1px solid #7eb4ea; }
QLabel[swMessage="info"], QFrame[swMessage="info"], QWidget[swMessage="info"] {
    background: #fafd88; color: #000000; border: 1px solid #fafd88; border-radius: 0px; padding: 4px 6px;
}
QFrame[swMessage="info"] QLabel[swMessage="info"], QWidget[swMessage="info"] QLabel[swMessage="info"] { border: none; background: transparent; padding: 0px; }
QFrame[swMessage="info"] QLabel, QWidget[swMessage="info"] QLabel { color: #000000; background: transparent; }
QFrame[swMessage="warn"] QLabel, QWidget[swMessage="warn"] QLabel { color: #a00000; background: transparent; }
QLabel[swMessage="warn"], QFrame[swMessage="warn"] {
    background: #ffd9d9; color: #a00000; border: 1px solid #e8a0a0; border-radius: 2px; padding: 4px 6px;
}
QLineEdit[swInvalid="true"], QAbstractSpinBox[swInvalid="true"] { background: #ffd9d9; color: #a00000; }
QAbstractSpinBox[swInvalid="true"] QLineEdit { background: #ffd9d9; color: #a00000; }
QListWidget[swstrip="1"], QLineEdit[swstrip="1"] { border-left: 14px solid #53a9ff; }
QListWidget[swstrip="2"], QLineEdit[swstrip="2"] { border-left: 14px solid #ff80c0; }
QListWidget[swstrip="3"], QLineEdit[swstrip="3"] { border-left: 14px solid #8000ff; }
QListWidget[swstrip="4"], QLineEdit[swstrip="4"] { border-left: 14px solid #5fbf5f; }
QListWidget[swstrip="5"], QLineEdit[swstrip="5"] { border-left: 14px solid #3fbfbf; }
QListWidget[swstrip="6"], QLineEdit[swstrip="6"] { border-left: 14px solid #e04fd0; }
QLineEdit, QAbstractSpinBox, QComboBox {
    background: ${field};
    color: ${field_text};
    border: 1px solid ${field_line};
    min-height: 20px;
    padding: 0px 3px;
    selection-background-color: #0078d7;
    selection-color: #ffffff;
}
QAbstractSpinBox:hover, QComboBox:hover { border: 1px solid #6fa8dc; }   /* statehover-1127 */
QLineEdit:focus, QAbstractSpinBox:focus, QComboBox:focus { border: 1px solid ${accent}; }
QLineEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled { background: ${hover}; color: ${text_disabled}; }
QComboBox QAbstractItemView { background: ${field}; color: ${field_text}; }
QPushButton {
    background: ${base};
    color: ${text};
    border: 1px solid ${field_line};
    border-radius: 2px;
    padding: 2px 10px;
    min-height: 20px;
}
QPushButton:hover { background: ${menu_hover}; border-color: #0078d7; }
QPushButton:checked, QPushButton:pressed { background: ${selection}; color: ${text}; border-color: #005499; }
QToolButton {
    background: ${base};
    color: ${text};
    border: 1px solid ${field_line};
    border-radius: 2px;
    padding: 2px 6px;
}
QToolButton:hover { background: ${menu_hover}; border-color: #0078d7; }
QToolButton:checked, QToolButton:pressed { background: ${selection}; color: ${text}; border-color: #005499; }
QCheckBox::indicator, QGroupBox::indicator {
    width: 13px; height: 13px;
    background: ${base};
    border: 1px solid ${arrow};
    border-radius: 2px;
}
QCheckBox::indicator:hover { border-color: #0078d7; }
QCheckBox::indicator:checked, QGroupBox::indicator:checked {
    background: #0078d7; border-color: #0078d7; image: url(@CHECK@);
}
QCheckBox::indicator:disabled { background: ${hover}; border-color: ${text_disabled}; }
QRadioButton::indicator {
    width: 13px; height: 13px;
    background: ${base};
    border: 1px solid ${arrow};
    border-radius: 7px;
}
QRadioButton::indicator:hover { border-color: #0078d7; }
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border-color: #0078d7; background: ${menu_hover}; }
QCheckBox::indicator:checked:focus { background: #005499; border-color: #005499; }
QRadioButton::indicator:checked { background: ${base}; border: 4px solid #0078d7; width: 7px; height: 7px; }
QRadioButton::indicator:checked:hover, QRadioButton::indicator:checked:focus { border-color: #005499; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    background: ${field}; border: none; width: 14px;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: ${menu_hover}; }
QAbstractSpinBox::up-arrow { image: url(@UP@); width: 7px; height: 4px; }
QAbstractSpinBox::down-arrow { image: url(@DOWN@); width: 7px; height: 4px; }
QComboBox::drop-down { border: none; width: 16px; background: ${field}; }
QComboBox::down-arrow { image: url(@CHEVRON@); width: 8px; height: 5px; }
QCheckBox, QRadioButton, QLabel, QGroupBox { background: transparent; color: ${text}; }
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled { color: ${text_disabled}; }
QWidget#SWStyle_PMHeader { background: ${pane}; }
QLabel#SWStyle_PMTitle { font-weight: bold; color: ${text}; }
QWidget#SWStyle_PMHeader QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 2px;
    padding: 0px;
}
QWidget#SWStyle_PMHeader QToolButton:hover { background: ${menu_hover}; border-color: ${hover_line}; }
QWidget#SWStyle_PMHeader QToolButton:pressed { background: ${selection}; border-color: ${accent}; }
QSint--ActionLabel[class="header"]:hover, QSint--ActionLabel[class="header"]:pressed,
QSint--ActionLabel[class="header"]:checked { background: transparent; border: none; }
"""


def _scoped(rules):
    """Prefix every selector with the task view so it outranks app-wide sheets."""
    out = []
    for block in rules.strip().split("}"):
        if "{" not in block:
            continue
        selectors, body = block.split("{", 1)
        scoped = []
        for sel in selectors.split(","):
            sel = sel.strip()
            if sel == "*":
                continue
            if sel.startswith("QWidget#PMRoot"):
                scoped.append("Gui--TaskView--TaskView")
            else:
                scoped.append("Gui--TaskView--TaskView " + sel)
        if scoped:
            out.append(",\n".join(scoped) + " {" + body + "}")
    return "\n".join(out)


def _field_arrow():
    """The combo chevron's colour: a quarter of the way from the field's text colour to the field (Light: #404040,
    the theme's arrow; Dark: the same dark grey on its white fields, not the pane's light arrow)."""
    try:
        if theme is not None:
            values = dict(theme.tokens())
            field = QtGui.QColor(values.get("field", values["base"]))
            text = QtGui.QColor(values.get("field_text", values["text"]))
        else:
            field, text = QtGui.QColor(_LIGHT_TOKENS["field"]), QtGui.QColor(_LIGHT_TOKENS["field_text"])
        mix = [round(a + (b - a) * 0.25) for a, b in ((text.red(), field.red()), (text.green(), field.green()),
                                                      (text.blue(), field.blue()))]
        return "#%02x%02x%02x" % tuple(mix)
    except Exception as _fw_err:
        _fw_log("propertymanager.py:field_arrow", _fw_err)
        return _token("arrow")


def _images():
    """Tiny check/arrow images for the light indicators (Qt needs files)."""
    import tempfile
    from pathlib import Path
    folder = Path(tempfile.gettempdir()) / "swstyle-pm"
    folder.mkdir(exist_ok=True)
    paths = {}
    specs = {
        "CHECK": (13, 13, "#ffffff", [(3, 6.5), (5.5, 9), (10, 3.5)], False),
        "UP": (7, 4, _token("field_text"), [(0, 4), (3.5, 0), (7, 4)], True),
        "DOWN": (7, 4, _token("field_text"), [(0, 0), (3.5, 4), (7, 0)], True),

        # drawn on the field's own colour: Dark keeps white fields, where the theme's light arrow vanished
        "CHEVRON": (8, 5, _field_arrow(), [(0.8, 0.9), (4, 4.1), (7.2, 0.9)], False),
    }
    for name, (w, h, color, points, fill) in specs.items():
        path = folder / ("%s-%s.png" % (name.lower(), color.strip("#")))
        image = QtGui.QImage(w * 2, h * 2, QtGui.QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.scale(2, 2)
        poly = QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points])
        if fill:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(color))
            painter.drawPolygon(poly)
        else:
            pen = QtGui.QPen(QtGui.QColor(color), 1.1 if name == "CHEVRON" else 1.8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(poly)
        painter.end()
        image.setDevicePixelRatio(2)
        image.save(str(path))
        paths[name] = path.as_posix()
    return paths


def _qss():
    # Fill the ${tokens} before scoping: _scoped splits the rules at "}".
    text = _RULES
    if theme is not None:
        values = dict(theme.tokens())
        values.setdefault("field", values["base"])
        values.setdefault("field_text", values["text"])
        text = theme.fill(text, **{k: values[k] for k in ("field", "field_text")})
    else:
        text = string.Template(text).safe_substitute(_LIGHT_TOKENS)
    for name, path in _images().items():
        text = text.replace("@%s@" % name, path)
    text = _strip_colours(text)
    return _scoped(text)


def _strip_colours(text):
    """optioncolors-1119: the 2nd..6th selection box strips in Options > Colors > Selected Item 2-6, as set."""
    try:
        from . import optionspages
    except Exception:
        return text
    for i in range(2, len(STRIPS) + 1):
        want = optionspages.kept_hex("Selected Item %d" % i)
        if want:
            old = 'QListWidget[swstrip="%d"], QLineEdit[swstrip="%d"] { border-left: 14px solid %s; }' % (i, i, STRIPS[i - 1])
            text = text.replace(old, old.replace(STRIPS[i - 1], want))
    return text


def error_css():
    ""
    try:
        if theme is not None and theme.dark():
            return "color: #ff8a8a;"
    except Exception as _fw_err:
        _fw_log("propertymanager.py:298", _fw_err)
    return "color: #c00000;"


def _theme_palette(base):
    """The look's theme colours (Light, Dark or AMOLED) whatever Windows' own mode is."""
    if theme is not None:
        try:
            return theme.theme_palette()
        except Exception as _fw_err:
            _fw_log("propertymanager.py:308", _fw_err)
    return _light_palette(base)


def _light_palette(base):
    """Light colours whatever Windows' own mode is (indicators, arrows, frames)."""
    pal = QtGui.QPalette(base)
    for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive):
        pal.setColor(group, QtGui.QPalette.Window, QtGui.QColor("#f7f7f7"))
        pal.setColor(group, QtGui.QPalette.WindowText, QtGui.QColor("#000000"))
        pal.setColor(group, QtGui.QPalette.Base, QtGui.QColor("#ffffff"))
        pal.setColor(group, QtGui.QPalette.AlternateBase, QtGui.QColor("#f3f3f3"))
        pal.setColor(group, QtGui.QPalette.Text, QtGui.QColor("#000000"))
        pal.setColor(group, QtGui.QPalette.Button, QtGui.QColor("#fdfdfd"))
        pal.setColor(group, QtGui.QPalette.ButtonText, QtGui.QColor("#000000"))
        pal.setColor(group, QtGui.QPalette.Highlight, QtGui.QColor("#0078d7"))
        pal.setColor(group, QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        pal.setColor(group, QtGui.QPalette.Light, QtGui.QColor("#ffffff"))
        pal.setColor(group, QtGui.QPalette.Midlight, QtGui.QColor("#e3e3e3"))
        pal.setColor(group, QtGui.QPalette.Mid, QtGui.QColor("#a0a0a0"))
        pal.setColor(group, QtGui.QPalette.Dark, QtGui.QColor("#a0a0a0"))
        pal.setColor(group, QtGui.QPalette.Shadow, QtGui.QColor("#696969"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, QtGui.QColor("#9a9a9a"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, QtGui.QColor("#9a9a9a"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, QtGui.QColor("#9a9a9a"))
    pal.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Base, QtGui.QColor("#f0f0f0"))
    return pal

OK_GREEN = "#74a257"

_saved = {}   # id(view) -> (stylesheet, palette) before style()
_header_icons = {}  # id(label) -> (label, icon) hidden from group titles


def _drawn(family):
    ""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pixmap = _hidpi.canvas(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(2, 2)
    def pen(color, width=2.2):
        line = QtGui.QPen(QtGui.QColor(color), width)
        line.setCapStyle(Qt.RoundCap)
        line.setJoinStyle(Qt.RoundJoin)
        painter.setPen(line)
    text = _token("text")
    if family == "CHECK_MARK":
        pen(OK_GREEN, 2.6)
        painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(3, 8.5), QtCore.QPointF(6.5, 12), QtCore.QPointF(13, 4)]))
    elif family == "STANDARD_CANCEL":
        pen("#d9433a", 2.4)
        painter.drawLine(QtCore.QPointF(4, 4), QtCore.QPointF(12, 12))
        painter.drawLine(QtCore.QPointF(12, 4), QtCore.QPointF(4, 12))
    elif family == "PM_HELP":

        pen(_token("arrow"), 1.2)
        painter.drawEllipse(QtCore.QRectF(1.5, 1.5, 13, 13))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(QtCore.QRectF(1.5, 1.5, 13, 13), Qt.AlignCenter, "?")
    elif family == "PM_DETAILED_PREVIEW":    # an eye
        pen(text, 1.3)
        path = QtGui.QPainterPath()
        path.moveTo(1.5, 8)
        path.quadTo(8, 1.5, 14.5, 8)
        path.quadTo(8, 14.5, 1.5, 8)
        painter.drawPath(path)
        painter.setBrush(QtGui.QColor("#3d7bc4"))
        painter.drawEllipse(QtCore.QRectF(5.5, 5.5, 5, 5))
    elif family.startswith("PIN_"):
        pen(text, 1.4)
        if family == "PIN_ACTIVE":   # pushed in: the pin stands upright
            painter.drawRect(QtCore.QRectF(5.5, 2, 5, 7))
            painter.drawLine(QtCore.QPointF(3.5, 9), QtCore.QPointF(12.5, 9))
            painter.drawLine(QtCore.QPointF(8, 9), QtCore.QPointF(8, 14.5))
        else:                        # loose: the pin lies on its side
            painter.drawRect(QtCore.QRectF(7, 5.5, 7, 5))
            painter.drawLine(QtCore.QPointF(7, 3.5), QtCore.QPointF(7, 12.5))
            painter.drawLine(QtCore.QPointF(1.5, 8), QtCore.QPointF(7, 8))
    else:
        painter.end()
        return QtGui.QIcon()
    painter.end()
    return QtGui.QIcon(pixmap)


def _tinted(icon, color):
    """The icon's shape filled with one colour (the pack's check mark is black)."""
    result = QtGui.QIcon()
    for size in icon.availableSizes() or [QtCore.QSize(16, 16)]:
        pixmap = icon.pixmap(size)
        painter = QtGui.QPainter(pixmap)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QtGui.QColor(color))
        painter.end()
        result.addPixmap(pixmap)
    return result


def _forget(wrapper):
    """A stale PySide wrapper: a layout item Qt deleted whose address a new widget now has.

    shiboken keeps one Python wrapper per C++ address. A QWidgetItem wrapper from layout.itemAt()
    is kept alive by its layout's wrapper; when Qt deletes the item (a widget removed from the
    layout) nobody tells shiboken, and a QWidget created later at the same address is handed back
    as that QWidgetItem (about 1 panel open in 5: "'QWidgetItem' object has no attribute
    'objectName'"). Dropping the stale wrapper from shiboken's map makes the next look-up right."""
    try:
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        shiboken.invalidate(wrapper)
    except Exception as _fw_err:
        _fw_log("propertymanager.py:424", _fw_err)


def _children(parent, kind=QtWidgets.QWidget):
    """parent.findChildren(kind) with every stale wrapper dropped and looked up again."""
    found = []
    for _attempt in range(2):
        try:
            found = parent.findChildren(kind)
        except Exception:
            return []
        stale = [w for w in found if not isinstance(w, kind)]
        if not stale:
            return found
        for w in stale:
            _forget(w)
    return [w for w in found if isinstance(w, kind)]


def _parent_widget(widget):
    for _attempt in range(2):
        try:
            parent = widget.parentWidget()
        except Exception:
            return None
        if parent is None or isinstance(parent, QtWidgets.QWidget):
            return parent
        _forget(parent)
    return None


def _class(widget):
    """The Qt class name, "" for a stale wrapper (metaObject() can hand back a QWidgetItem)."""
    try:
        return widget.metaObject().className()
    except (AttributeError, RuntimeError):
        return ""


def _view(dock):
    widget = dock.widget() if isinstance(dock, QtWidgets.QDockWidget) else dock
    if widget is None:
        return None
    if _class(widget) == "Gui::TaskView::TaskView":
        return widget
    for child in _children(widget):
        if _class(child) == "Gui::TaskView::TaskView":
            return child
    return None


def _edit_control(view):
    for child in _children(view):
        if _class(child) == "Gui::TaskView::TaskEditControl":
            return child
    return None


def _boxes(view):
    # Panels subclass TaskBox (e.g. PartDesignGui::TaskFilletParameters).
    return [w for w in _children(view) if w.inherits("QSint::ActionGroup")]


def _tab_order(view):
    ""

    chain = []
    home = view.window()
    for w in view.findChildren(QtWidgets.QWidget):
        if not w.isVisible() or not (w.focusPolicy() & QtCore.Qt.TabFocus):
            continue
        if w.window() is not home:
            continue        # a pop-up or floating part of the page: Qt warns "must be in the same window"
        if _inside_header(w):
            if isinstance(w, QtWidgets.QAbstractButton):
                w.setFocusPolicy(QtCore.Qt.NoFocus)     # OK, Cancel, the eye and the pin are no tab stops
            continue
        if w.objectName() == HEADER or isinstance(w, (QtWidgets.QScrollArea, QtWidgets.QAbstractScrollArea)) and not isinstance(w, (QtWidgets.QAbstractItemView, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            continue
        if w.focusProxy() is not None or isinstance(w, QtWidgets.QLineEdit) and isinstance(w.parentWidget(), QtWidgets.QAbstractSpinBox):
            continue        # a spin box's line edit: the box itself is in the chain
        p = w.mapTo(view, QtCore.QPoint(0, 0))
        chain.append((p.y(), p.x(), w))
    chain.sort(key=lambda t: (t[0], t[1]))
    widgets = [w for _y, _x, w in chain]
    # the places count too: a page that lays itself out again (pmlayout moves rows, a group opens)
    # gets its chain again, or Tab kept the order of the first layout (Chamfer types reached last)
    key = ",".join("%s@%d,%d" % (hash(w), y, x) for y, x, w in chain)
    if key == view.property("swTabChain"):
        return
    for a, b in zip(widgets, widgets[1:]):
        QtWidgets.QWidget.setTabOrder(a, b)
    view.setProperty("swTabChain", key)
    _TabCycle.on(view, widgets)


class _TabCycle(QtCore.QObject):
    ""



    def __init__(self, view):
        super().__init__(view)
        self.widgets = []

    @classmethod
    def on(cls, view, widgets):
        cycle = view.findChild(cls)
        if cycle is None:
            cycle = cls(view)
        for w in cycle.widgets:
            if not _alive(w):
                continue
            try:
                w.removeEventFilter(cycle)
                if isinstance(w, QtWidgets.QAbstractSpinBox) and w.lineEdit() is not None:
                    w.lineEdit().removeEventFilter(cycle)
            except RuntimeError as _fw_err:
                _fw_log("propertymanager.py:540", _fw_err)
        cycle.widgets = list(widgets)
        for w in widgets:
            w.installEventFilter(cycle)
            if isinstance(w, QtWidgets.QAbstractSpinBox) and w.lineEdit() is not None:
                w.lineEdit().installEventFilter(cycle)      # a Tab that reaches the number's text line itself
        if not getattr(cycle, "on_view", False):
            # the keyboard on the page itself (a click on its empty part): Tab goes to its first box,
            # not past the page to the status bar (Mirror Body)
            view.installEventFilter(cycle)
            cycle.on_view = True
        # pkg454: a click on the page's empty part gives the focus to its scroll area, not the view: Tab
        # from there went past the page too (to the status bar's buttons)
        cycle.areas = []
        for area in view.findChildren(QtWidgets.QAbstractScrollArea):
            if isinstance(area, (QtWidgets.QAbstractItemView, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
                continue
            area.installEventFilter(cycle)      # installing again moves it first, no second copy
            cycle.areas.append(area)

    def _ends(self):
        alive = []
        for w in self.widgets:
            try:
                if w.isVisible() and w.isEnabled():
                    alive.append(w)
            except RuntimeError as _fw_err:
                _fw_log("propertymanager.py:559", _fw_err)
        return (alive[0], alive[-1]) if alive else (None, None)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent) or event.type() != QtCore.QEvent.KeyPress:
            return False
        key = event.key()
        if key not in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            return False
        if key == QtCore.Qt.Key_Tab and event.modifiers() & QtCore.Qt.ControlModifier:
            return False
        first, last = self._ends()
        if first is None:
            return False
        if (obj is self.parent() or obj in getattr(self, "areas", ())) and obj not in self.widgets:
            if event.modifiers() & QtCore.Qt.ShiftModifier or key == QtCore.Qt.Key_Backtab:
                last.setFocus(QtCore.Qt.BacktabFocusReason)
            else:
                first.setFocus(QtCore.Qt.TabFocusReason)
            return True
        focus = QtWidgets.QApplication.focusWidget()
        def own(w):
            if w is obj or (w is not None and w.isAncestorOf(obj)):
                return True
            # an exclusive radio set is one tab stop (Qt): Tab from its checked button is Tab from the set,
            # so the page's last set ("Same surface | Linear" on Extend Surface) still wraps (pkg121)
            R = QtWidgets.QRadioButton
            if (isinstance(w, R) and isinstance(obj, R) and w.autoExclusive() and obj.autoExclusive()
                    and w.parentWidget() is obj.parentWidget() and w.group() is obj.group()):
                return True
            # an exclusive button group is one tab stop too (Axis types: Tab from One Line/Edge/Axis
            # left the page for the status bar, as it is the last stop before the wrap)
            B = QtWidgets.QAbstractButton
            try:
                g = w.group() if isinstance(w, B) else None
                return g is not None and g.exclusive() and isinstance(obj, B) and obj.group() is g
            except RuntimeError:
                return False
        if key == QtCore.Qt.Key_Tab and own(last) and not (event.modifiers() & QtCore.Qt.ShiftModifier):
            first.setFocus(QtCore.Qt.TabFocusReason)
            return True
        if (key == QtCore.Qt.Key_Backtab or event.modifiers() & QtCore.Qt.ShiftModifier) and own(first):
            last.setFocus(QtCore.Qt.BacktabFocusReason)
            return True
        return False


OPEN_FOCUS = "swOpenFocus"


def _open_focus(view, control, title):
    ""



    if control is None:
        view.setProperty(OPEN_FOCUS, None)
        return
    key = "%s|%x" % (title, id(control))
    if view.property(OPEN_FOCUS) == key:
        return
    view.setProperty(OPEN_FOCUS, key)
    if _keeps_keys(view):
        return                              # a picked drawing item's page: the keyboard stays on the sheet
    for box in view.findChildren(QtWidgets.QListWidget):
        try:
            # a43: an empty pink box (Edge Flange's edges, Hem, End Cap, Gusset with nothing picked first) also
            # waits for a pick, so the view keeps the keys (a typed "f" was going into Edge Flange's Angle field)
            waiting = box.property("swNeed") or (box.property("swActive") == "true" and box.count() == 0)
            if box.isVisible() and waiting:
                QtCore.QTimer.singleShot(0, _focus_view)      # pkg110: Enter/Esc work from the view
                return
        except RuntimeError:
            continue

    def go():
        try:
            if view.property(OPEN_FOCUS) != key or not view.isVisible():
                return
            if _keeps_keys(view):
                return
            focus = QtWidgets.QApplication.focusWidget()
            if focus is not None and view.isAncestorOf(focus) and not _inside_header(focus) \
                    and not isinstance(focus, QtWidgets.QAbstractScrollArea) and focus.focusPolicy() & QtCore.Qt.TabFocus:
                return                      # the page chose its own focus (FreeCAD's Pad: D1)
            fields = []
            for w in view.findChildren(QtWidgets.QWidget):
                if not isinstance(w, (QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit)):
                    continue
                if isinstance(w, QtWidgets.QLineEdit) and isinstance(w.parentWidget(), QtWidgets.QAbstractSpinBox):
                    continue
                if not w.isVisible() or not w.isEnabled() or w.isReadOnly() or _inside_header(w):
                    continue
                if not (w.focusPolicy() & QtCore.Qt.TabFocus):
                    continue
                p = w.mapTo(view, QtCore.QPoint(0, 0))
                fields.append((p.y(), p.x(), w))
            if not fields:
                _focus_view()
                return
            fields.sort(key=lambda t: (t[0], t[1]))
            w = fields[0][2]
            w.setFocus(QtCore.Qt.OtherFocusReason)
            w.selectAll()       # a spin box selects its number and keeps its unit
        except RuntimeError as _fw_err:
            _fw_log("propertymanager.py:660", _fw_err)
    QtCore.QTimer.singleShot(0, go)


def _keeps_keys(view):
    ""

    try:
        return any(bool(w.property("swKeepKeys")) for w in [view] + view.findChildren(QtWidgets.QWidget))
    except RuntimeError:
        return False


def _focus_view():
    ""


    try:
        from .pmtakeover import view_widget
        viewport = view_widget()
        if viewport is None:
            return
        target = viewport.parentWidget() if isinstance(viewport.parentWidget(), QtWidgets.QGraphicsView) else viewport
        focus = QtWidgets.QApplication.focusWidget()
        if focus is not None and (focus is target or target.isAncestorOf(focus)):
            return
        if focus is not None:
            w = focus
            while w is not None:
                if w.metaObject().className() == "Gui::TaskView::TaskView":
                    return                      # the page itself has the keyboard
                w = w.parentWidget()
        target.setFocus(QtCore.Qt.OtherFocusReason)
    except Exception as error:
        App.Console.PrintLog("FreeCAD propertymanager: view focus: %r\n" % error)


def _first_box_title(view):
    for box in _boxes(view):
        for label in _children(box):
            if label.property("class") == "header" and hasattr(label, "text"):
                text = label.text().strip()
                if text:
                    return text
    return ""


def _editing_existing(obj):
    """True when the in-edit object is an existing feature opened by Edit Feature (pkg444)."""
    try:
        tx = App.getActiveTransaction()
    except Exception:
        return False
    return bool(tx) and tx[0] == "Edit " + obj.Label


def _title(view):
    ""
    obj = None
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = editobj.of(edit) if edit is not None else None
    except Exception:
        obj = None
    box_title = _first_box_title(view)
    if obj is not None and obj.TypeId in TITLES:
        title, family = TITLES[obj.TypeId]
        if obj.TypeId == "Sketcher::SketchObject" and box_title:
            # A sketch tool's own panel: "Circle parameters" -> "Circle"
            title = box_title.replace(" parameters", "").replace(" Parameters", "")
        elif obj.TypeId != "Sketcher::SketchObject" and _editing_existing(obj):
            title = obj.Label        # pkg444: Edit Feature titles the page "Boss-Extrude1", a new one "Boss-Extrude"
        icon = icons.family(family)
        return title, icon if not icon.isNull() else _command_icon(title)
    # Addon panels name themselves (sketchstart's "Edit Sketch", the Rib).
    for widget in _children(view):
        own = widget.property("swstyle_pm_title")
        if own:
            icon = icons.family(widget.property("swstyle_pm_icon") or "")
            if icon.isNull():
                icon = _command_icon(own)
            if (icon is None or icon.isNull()) and own.rstrip("0123456789") != own:
                icon = _command_icon(own.rstrip("0123456789"))      # an edited feature: "Chamfer1" -> Chamfer's icon
            if icon is None or icon.isNull():
                # no picture in the icon pack: the initials tile the CommandManager button shows too
                try:
                    icon = icons.initials(own.rstrip("0123456789") or own)
                except Exception as _fw_err:
                    _fw_log("propertymanager.py:729", _fw_err)
            return own, icon if icon is not None else QtGui.QIcon()
    if box_title:
        title = box_title.replace(" parameters", "").replace(" Parameters", "")
        return title, _command_icon(title)
    return "PropertyManager", QtGui.QIcon()


_CMD_ICONS = {}
_CMD_MISSED = set()
_NATIVE_MISSED = set()
_CMD_NAMES = {}         # menu text -> the native command behind it (icons-pm-1119)
_NATIVE_CMD = {}        # native command name -> catalog command


def _sw_icon(native):
    """The picture the ribbon button of the catalog command behind a native command shows (its pack family,
    the pack's FW_<key>, the drawn set), or None."""
    if not native:
        return None
    try:
        from . import catalog, icons
        if not _NATIVE_CMD:
            for cmd in catalog.BY_KEY.values():
                for n in cmd.natives:
                    _NATIVE_CMD.setdefault(n, cmd)
            _NATIVE_CMD.setdefault("", None)
        cmd = _NATIVE_CMD.get(native)
        if cmd is None and native not in _NATIVE_MISSED:
            # a wrapper added to the catalog after the first look (toolfirst, sketchfirstlive): look again once
            _NATIVE_MISSED.add(native)
            for c in catalog.BY_KEY.values():
                for n in c.natives:
                    _NATIVE_CMD.setdefault(n, c)
            cmd = _NATIVE_CMD.get(native)
        if cmd is None:
            return None
        for icon in ((icons.family(cmd.icon) if cmd.icon else None), icons.family("FW_" + cmd.key), icons.drawn(cmd.key)):
            if icon is not None and icons.paints(icon):
                return icon
    except Exception:
        return None
    return None
_CMD_ALIAS = {"Hole Specification": "PartDesign_Hole", "Pattern": "PartDesign_MultiTransform",
              "Boundary-Surface": "SWStyle_BoundarySurface", "Surface-Revolve": "SWStyle_SurfaceRevolve",
              "Slicing": "SWStyle_Slicing", "Boss-Extrude": "PartDesign_Pad", "Cut-Extrude": "PartDesign_Pocket",
              "Shell": "PartDesign_Thickness", "Revolve": "PartDesign_Revolution", "Cut-Revolve": "PartDesign_Groove",
              "Composite Curve": "SWStyle_CompositeCurve",
              # sheet metal and weldment pages whose title is not their command's menu text
              "Base Flange": "SWStyle_SMBaseFlange", "Edge-Flange": "SWStyle_SMEdgeFlange",
              "Break Corner": "SWStyle_SMBreakCorner", "Cross Break": "SWStyle_SMCrossBreak",
              "Form Tool Feature": "SWStyle_SMFormingTool", "Bends": "SWStyle_SMInsertBends", "Lofted Bends": "SWStyle_SMLoftedBend", "Surface-Extrude": "SWStyle_SurfaceExtrude",
              "Surface-Offset": "SWStyle_SurfaceOffset", "Surface-Knit": "SWStyle_SurfaceKnit", "Offset Surface": "SWStyle_SurfaceOffset",
              "Knit Surface": "SWStyle_SurfaceKnit", "Fill Surface": "SWStyle_FilledSurface", "Delete Face": "SWStyle_DeleteFace",
              "Insert Component": "SWStyle_InsertComponents", "Dimension": "FreeWorks_SmartDimension", "Explode": "SWStyle_ExplodedView",
              "Mate": "SWStyle_Mate", "Coincident": "SWStyle_Mate", "Parallel": "SWStyle_Mate",
              "Perpendicular": "SWStyle_Mate", "Tangent": "SWStyle_Mate", "Concentric": "SWStyle_Mate",
              "Lock": "SWStyle_Mate", "Distance": "SWStyle_Mate", "Angle": "SWStyle_Mate",
              "Structural Member": "SWStyle_WEStructuralMember", "Trim/Extend": "SWStyle_WETrimExtend",
              "End Cap": "SWStyle_WEEndCap", "Broken View": "FreeWorks_DrawBreak"}


def _command_icon(title):
    ""

    if _CMD_ICONS and title and title not in _CMD_NAMES and title not in _CMD_MISSED:
        # commands registered after the first page (Silhouette Entities, Mirror Entities...): look again once
        _CMD_MISSED.add(title)
        _CMD_ICONS.clear()
    if not _CMD_ICONS:
        try:
            for name in Gui.listCommands():
                if not name.startswith(("SWStyle_", "PartDesign_", "FreeWorks_")):
                    continue
                info = Gui.Command.get(name).getInfo()
                text = (info.get("menuText") or "").replace("&", "").replace("...", "").replace("\u2026", "").strip()
                if text and info.get("pixmap") and (text not in _CMD_ICONS or name.startswith("SWStyle_")):
                    _CMD_ICONS[text] = info["pixmap"]
                    _CMD_NAMES[text] = name
                elif text and text not in _CMD_NAMES:
                    # a Python command without a Pixmap (Silhouette Entities): its button's drawn picture
                    _CMD_NAMES[text] = name
        except Exception as _fw_err:
            _fw_log("propertymanager.py:769", _fw_err)
        _CMD_ICONS.setdefault("", "")
    sw = _sw_icon(_CMD_ALIAS.get(title) or _CMD_NAMES.get(title))
    if sw is not None:
        return sw
    pix = _CMD_ICONS.get(title)
    if title in _CMD_ALIAS:
        try:
            pix = Gui.Command.get(_CMD_ALIAS[title]).getInfo().get("pixmap")
        except Exception:
            pix = None
    try:
        icon = Gui.getIcon(pix) if pix else QtGui.QIcon()
    except Exception:
        icon = QtGui.QIcon()
    if title in _CMD_ALIAS and (icon is None or icon.isNull()):
        # a Python command without a Pixmap: the same initials tile its CommandManager button shows
        try:
            from . import icons
            icon = icons.initials(title)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:787", _fw_err)
    return icon



# text}. Labels, check boxes, group titles and list entries are renamed; the
# lists keep their order, so FreeCAD (which reads the position) is unaffected.
_EXTRUDE = {
    "Pad Parameters": "Direction 1",
    "Pocket Parameters": "Direction 1",
    "Mode": "Directions",
    "One sided": "One Direction",
    "Two sided": "Two Directions",
    "Symmetric": "Mid Plane",
    "Side 1": "Direction 1",
    "Side 2": "Direction 2",
    "Type": "End Condition",
    "Dimension": "Blind",
    "To last": "Through All",
    "Through all": "Through All",
    "To first": "Up To Next",
    "Up to face": "Up To Surface",
    "Up to shape": "Up To Body",
    "Length": "Depth",
    "Offset to face": "Offset Distance",
    "Taper angle": "Draft Angle",
    "Reversed": "Reverse Direction",
    "Direction": "Direction of Extrusion",
}
_REVOLVE = {
    "Revolution Parameters": "Direction 1",
    "Groove Parameters": "Direction 1",
    "Type": "Revolve Type",
    "Angle": "Blind",
    "To last": "Through All",
    "Through all": "Through All",
    "To first": "Up To Next",
    "Up to face": "Up To Surface",
    "Two angles": "Two Directions",
    "Axis": "Axis of Revolution",
    "2nd angle": "Direction 2 Angle",
    "Symmetric to plane": "Mid Plane",
    "Reversed": "Reverse Direction",
}
_DRESSUP = {
    "Use all edges": "Select all edges",
    "Select": "Pick",
}
WORDS = {
    "PartDesign::Pad": _EXTRUDE,
    "PartDesign::Pocket": _EXTRUDE,
    "PartDesign::Revolution": _REVOLVE,
    "PartDesign::Groove": _REVOLVE,
    "PartDesign::Fillet": dict(_DRESSUP, Radius="Radius", **{"Fillet Parameters": "Items To Fillet"}),
    "PartDesign::Chamfer": dict(_DRESSUP, **{
        "Chamfer Parameters": "Items To Chamfer",
        "Type": "Chamfer Type",
        "Equal distance": "Equal Distance",
        "Two distances": "Distance Distance",
        "Distance and angle": "Angle Distance",
        "Size": "Distance",
        "Size 2": "Distance 2",
    }),
    "PartDesign::Thickness": dict(_DRESSUP, **{
        "Thickness": "Thickness",
        "Thickness Parameters": "Parameters",
        "Thickness parameters": "Parameters",
    }),
    "PartDesign::Draft": dict(_DRESSUP, **{
        "Draft angle": "Draft Angle",
        "Neutral Plane": "Neutral Plane",
        "Pull Direction": "Direction of Pull",
        "Reverse pull direction": "Reverse Direction",
    }),
    "PartDesign::Mirrored": {"Plane": "Mirror Face/Plane", "Transform body": "Bodies to Mirror",
                             "Transform tool shapes": "Features to Mirror"},
    "PartDesign::LinearPattern": {"Transform body": "Bodies to Pattern",
                                  "Transform tool shapes": "Features to Pattern"},
    "PartDesign::PolarPattern": {"Transform body": "Bodies to Pattern",
                                 "Transform tool shapes": "Features to Pattern"},
}
_ORIGINAL = "swstyle_pm_original"

# FreeCAD's PartDesign panels in the user's language: the table above is keyed by FreeCAD's English text,
# which a translated FreeCAD does not show. native_variants(text) is the English text and what FreeCAD's own
# translation contexts make of it (found on the bench in Italian: every key of the table translates under
# one of these contexts).
NATIVE_CONTEXTS = ['PartDesignGui::DlgActiveBody', 'PartDesignGui::DlgPrimitives', 'PartDesignGui::DlgReference', 'PartDesignGui::TaskBooleanParameters', 'PartDesignGui::TaskBoxPrimitives', 'PartDesignGui::TaskChamferParameters', 'PartDesignGui::TaskDatumParameters', 'PartDesignGui::TaskDlgBooleanParameters', 'PartDesignGui::TaskDlgChamferParameters', 'PartDesignGui::TaskDlgDatumParameters', 'PartDesignGui::TaskDlgDraftParameters', 'PartDesignGui::TaskDlgDressUpParameters', 'PartDesignGui::TaskDlgExtrudeParameters', 'PartDesignGui::TaskDlgFeatureParameters', 'PartDesignGui::TaskDlgFeaturePick', 'PartDesignGui::TaskDlgFilletParameters', 'PartDesignGui::TaskDlgGrooveParameters', 'PartDesignGui::TaskDlgHelixParameters', 'PartDesignGui::TaskDlgHoleParameters', 'PartDesignGui::TaskDlgLinearPatternParameters', 'PartDesignGui::TaskDlgLoftParameters', 'PartDesignGui::TaskDlgMirroredParameters', 'PartDesignGui::TaskDlgMultiTransformParameters', 'PartDesignGui::TaskDlgPadParameters', 'PartDesignGui::TaskDlgPipeParameters', 'PartDesignGui::TaskDlgPocketParameters', 'PartDesignGui::TaskDlgPrimitiveParameters', 'PartDesignGui::TaskDlgRevolutionParameters', 'PartDesignGui::TaskDlgScaledParameters', 'PartDesignGui::TaskDlgShapeBinder', 'PartDesignGui::TaskDlgSketchBasedParameters', 'PartDesignGui::TaskDlgThicknessParameters', 'PartDesignGui::TaskDlgTransformedParameters', 'PartDesignGui::TaskDraftParameters', 'PartDesignGui::TaskDressUpParameters', 'PartDesignGui::TaskExtrudeParameters', 'PartDesignGui::TaskExtrudeParameters::Side', 'PartDesignGui::TaskFeatureParameters', 'PartDesignGui::TaskFeaturePick', 'PartDesignGui::TaskFilletParameters', 'PartDesignGui::TaskHelixParameters', 'PartDesignGui::TaskHoleParameters', 'PartDesignGui::TaskLoftParameters', 'PartDesignGui::TaskMirroredParameters', 'PartDesignGui::TaskMultiTransformParameters', 'PartDesignGui::TaskPadParameters', 'PartDesignGui::TaskPadPocketParameters', 'PartDesignGui::TaskPatternParameters', 'PartDesignGui::TaskPipeOrientation', 'PartDesignGui::TaskPipeParameters', 'PartDesignGui::TaskPipeScaling', 'PartDesignGui::TaskPocketParameters', 'PartDesignGui::TaskPreviewParameters', 'PartDesignGui::TaskRevolutionParameters', 'PartDesignGui::TaskScaledParameters', 'PartDesignGui::TaskShapeBinder', 'PartDesignGui::TaskSketchBasedParameters', 'PartDesignGui::TaskThicknessParameters', 'PartDesignGui::TaskTransformedMessages', 'PartDesignGui::TaskTransformedParameters', 'PartDesignGui::ViewProvider', 'PartDesignGui::ViewProviderBase', 'PartDesignGui::ViewProviderBody', 'PartDesignGui::ViewProviderBoolean', 'PartDesignGui::ViewProviderChamfer', 'PartDesignGui::ViewProviderDatum', 'PartDesignGui::ViewProviderDatumCoordinateSystem', 'PartDesignGui::ViewProviderDatumLine', 'PartDesignGui::ViewProviderDatumPlane', 'PartDesignGui::ViewProviderDatumPoint', 'PartDesignGui::ViewProviderDraft', 'PartDesignGui::ViewProviderDressUp', 'PartDesignGui::ViewProviderExtrude', 'PartDesignGui::ViewProviderFillet', 'PartDesignGui::ViewProviderGroove', 'PartDesignGui::ViewProviderHelix', 'PartDesignGui::ViewProviderHole', 'PartDesignGui::ViewProviderLinearPattern', 'PartDesignGui::ViewProviderLoft', 'PartDesignGui::ViewProviderMirrored', 'PartDesignGui::ViewProviderMultiTransform', 'PartDesignGui::ViewProviderPad', 'PartDesignGui::ViewProviderPipe', 'PartDesignGui::ViewProviderPocket', 'PartDesignGui::ViewProviderPolarPattern', 'PartDesignGui::ViewProviderPrimitive', 'PartDesignGui::ViewProviderPython', 'PartDesignGui::ViewProviderRevolution', 'PartDesignGui::ViewProviderScaled', 'PartDesignGui::ViewProviderShapeBinder', 'PartDesignGui::ViewProviderSketchBased', 'PartDesignGui::ViewProviderSubShapeBinder', 'PartDesignGui::ViewProviderSubShapeBinderPython', 'PartDesignGui::ViewProviderThickness', 'PartDesignGui::ViewProviderTransformed', 'PartDesignGui::Workbench', 'TaskHoleParameters']
_VARIANTS = {}


def native_variants(text):
    """{text} plus its translations under FreeCAD's PartDesign contexts (cached)."""
    got = _VARIANTS.get(text)
    if got is None:
        got = {text}
        try:
            translate = QtCore.QCoreApplication.translate
            for context in NATIVE_CONTEXTS:
                shown = translate(context, text)
                if shown:
                    got.add(shown)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:native_variants", _fw_err)
        _VARIANTS[text] = got
    return got


_LOCALIZED = {}


def localized(words):
    ""
    got = _LOCALIZED.get(id(words))
    if got is None:
        got = dict(words)
        for english, sw in words.items():
            for shown in native_variants(english):
                got.setdefault(shown, sw)
        _LOCALIZED[id(words)] = got
    return got



# (reference geometry, mates, dimensions, measure); a feature page has none (2024 shots:
# Boss-Extrude, Cut-Extrude, Fillet, Shell, Hole Wizard, Rectangle).
KEEP_VISIBLE = {"Plane", "Axis", "Point", "Coordinate System", "Mate", "Smart Dimension",
                "Measure", "Note", "Balloon", "Appearances", "Appearance", "Section View",
                "Structural Member"}

# restarts its PartDesign command, see _editing_command). Mate has its own pushpin (asmpm) and
# Smart Dimension stays on by itself.
KEEP_VISIBLE_COMMANDS = {"Plane": "SWStyle_RefPlane", "Axis": "SWStyle_RefAxis", "Point": "SWStyle_RefPoint",
                         "Coordinate System": "SWStyle_RefCoordinateSystem", "Section View": "sectionview.start",
                         "Appearances": "SWStyle_Appearance", "Appearance": "SWStyle_Appearance",
                         "Measure": "SWStyle_Measure", "Note": "FreeWorks_DrawNote", "Balloon": "FreeWorks_DrawBalloon",
                         "Structural Member": "SWStyle_WEStructuralMember"}


# left of each box, in the order the boxes come on the page.

STRIPS = ("#53a9ff", "#ff80c0", "#8000ff", "#5fbf5f", "#3fbfbf", "#e04fd0")
STRIP = "swstrip"


# also between sessions: pkg101 keeps it in the user parameters).
FOLDS = {}
_FOLD_SEEN = {}
FOLD_PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/PMFolds"


def _fold_key_name(key):
    return "%s|%s" % key


def _load_folds():
    ""
    try:
        grp = App.ParamGet(FOLD_PARAMS)
        for name in grp.GetBools():
            if "|" in name:
                page, title = name.split("|", 1)
                FOLDS[(page, title)] = bool(grp.GetBool(name, True))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PropertyManager folds: %r\n" % error)


def _save_fold(key, open_):
    try:
        App.ParamGet(FOLD_PARAMS).SetBool(_fold_key_name(key), bool(open_))
    except Exception as _fw_err:
        _fw_log("propertymanager.py:915", _fw_err)


_load_folds()
_current_title = None       # (id(view), title) while a sync runs: one title lookup per pass (pkg97)


def _group_title(group):
    for label in group.findChildren(QtWidgets.QWidget):
        if label.inherits("QSint::ActionLabel") and callable(getattr(label, "text", None)):
            return label.text()
    return ""


def _group_open(group):
    """The QSint group's content frame shows while the group is expanded."""
    frames = [c for c in group.children() if isinstance(c, QtWidgets.QFrame) and not c.inherits("QSint::TaskHeader")]
    content = frames[-1] if frames else None
    return content is not None and not content.isHidden()


FOLD_SETTLE_S = 5.0     # longest a code fold may take to finish (slow PC, page still building)


def settle_fold(group):
    ""



    try:
        import time
        group.setProperty("swfold_settle", time.time() + FOLD_SETTLE_S)
        group.setProperty("swfold_target", not _group_open(group))     # the state the fold ends in
    except Exception as _fw_err:
        _fw_log("propertymanager.py:settle_fold", _fw_err)


def _settling(group):
    try:
        import time
        until = group.property("swfold_settle")
        if not until:
            return False
        if time.time() >= float(until) or _group_open(group) == bool(group.property("swfold_target")):
            group.setProperty("swfold_settle", 0.0)     # the fold has ended: later changes are the user's
            return False
        return True
    except Exception:
        return False


class _FoldWatch(QtCore.QObject):
    """pkg446: a group's fold is noted the moment its rows show or hide. Noting it only on the page's
    sync lost a fold or unfold the user made just before closing the page (Mirror, one run in three)."""

    @classmethod
    def watch(cls, group):
        frames = [c for c in group.children() if isinstance(c, QtWidgets.QFrame) and not c.inherits("QSint::TaskHeader")]
        if frames and not getattr(frames[-1], "_sw_fold_watch", None):
            frames[-1]._sw_fold_watch = cls(group, frames[-1])

    def __init__(self, group, content):
        super().__init__(content)
        self.group_id = id(group)
        content.installEventFilter(self)

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.Show, QtCore.QEvent.Hide):
                seen = _FOLD_SEEN.get(self.group_id)
                open_ = not obj.isHidden()       # a page closing hides its parents, not the rows themselves
                if isinstance(seen, tuple) and seen[1] != open_:
                    FOLDS[seen[0]] = open_
                    _FOLD_SEEN[self.group_id] = (seen[0], open_)
                    _save_fold(seen[0], open_)
        except Exception:
            pass
        return False


def _fold_memory(view, page):
    """Each sync: a group folded or opened by the user is remembered for the page; a page that
    opens gets its groups folded as they were left."""
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup") or group.isHidden():
            continue
        title = _group_title(group)
        if not title or not group.property("expandable"):
            continue
        key = (page, title)
        open_ = _group_open(group)
        seen = _FOLD_SEEN.get(id(group))
        if seen is not None and not isinstance(seen, tuple):
            seen = (key, seen)          # an older pmlayout notes the bare state
        if seen is None or seen[0] != key:
            # first sight of this group under this page and group title: apply the memory (a FreeCAD
            # page is seen first under its own titles, Pad, and renamed Boss-Extrude a moment later)
            want = FOLDS.get(key)
            if want is not None and want != open_ and not _settling(group):
                try:
                    settle_fold(group)
                    QtCore.QMetaObject.invokeMethod(group, "showHide")
                    open_ = want
                except Exception as _fw_err:
                    _fw_log("propertymanager.py:959", _fw_err)
            if seen is None:
                group.destroyed.connect(lambda *a, k=id(group): _FOLD_SEEN.pop(k, None))
                _FoldWatch.watch(group)      # pkg446
            _FOLD_SEEN[id(group)] = (key, open_)
        elif seen[1] != open_:
            if _settling(group):
                continue            # a fold made by code still animating, not the user's click
            FOLDS[key] = open_
            _FOLD_SEEN[id(group)] = (key, open_)
            _save_fold(key, open_)


TIGHT = "swTight"


def _tight_groups(view):
    ""



    for panel in view.findChildren(QtWidgets.QWidget):


        if panel.inherits("QSint::ActionPanel") and panel.layout() is not None and panel.layout().spacing() > 2:
            panel.layout().setSpacing(2)
            m = panel.layout().contentsMargins()
            panel.layout().setContentsMargins(m.left(), min(m.top(), 2), m.right(), min(m.bottom(), 2))
        if panel.inherits("QSint::ActionPanel") and isinstance(panel.layout(), QtWidgets.QBoxLayout):
            # look audit 1920x1080: on a tall pane Qt shared the spare height between the groups
            # (Shell's Parameters 329 px for 205, Mirror Face/Plane 148 around one box), as every item

            lay = panel.layout()
            last = lay.count() - 1
            if last >= 0 and lay.itemAt(last).spacerItem() is not None and lay.stretch(last) == 0:
                lay.setStretch(last, 1)
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup"):
            continue
        frames = [c for c in group.children() if isinstance(c, QtWidgets.QFrame) and not c.inherits("QSint::TaskHeader")]
        if not frames:
            continue
        content = frames[-1]
        lays = [content.layout()]
        for child in content.children():
            if isinstance(child, QtWidgets.QWidget) and child.layout() is not None:
                lays.append(child.layout())
        for lay in lays:
            if lay is None or lay.property(TIGHT):
                continue
            m = lay.contentsMargins()
            if m.top() > 3 or m.bottom() > 3:
                lay.setContentsMargins(m.left(), min(m.top(), 3), m.right(), min(m.bottom(), 3))
            lay.setProperty(TIGHT, True)


NARROW = "swNarrow"


def _narrow_rows(view):
    ""



    try:
        limit = 250
        for form in view.findChildren(QtWidgets.QFormLayout):
            # every sync: a page may fill its form after the first one
            if form.rowWrapPolicy() == QtWidgets.QFormLayout.DontWrapRows:
                form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
            if form.rowWrapPolicy() != QtWidgets.QFormLayout.WrapAllRows and form.minimumSize().width() > limit:
                form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapAllRows)
        for label in view.findChildren(QtWidgets.QLabel):
            if label.property(NARROW) or label.wordWrap():          # a page of a stack counts while hidden
                continue
            text = label.text() or ""
            if " " in text.strip() and label.sizeHint().width() > limit and not _inside_header(label):
                label.setProperty(NARROW, True)
                label.setWordWrap(True)
        for button in view.findChildren(QtWidgets.QAbstractButton):
            # look audit 1920x1080: the stock Hole page cut "Include in depth" to "Include in de..." (a check
            # box in a 106 px column, 112 needed); a check box or option a few pixels short gets its width
            if not isinstance(button, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)) or not button.isVisible():
                continue
            need = button.sizeHint().width()
            if button.width() < need <= button.width() + 24 and button.minimumWidth() < need:
                button.setMinimumWidth(need)
    except Exception as _fw_err:
        _fw_log("propertymanager.py:narrow_rows", _fw_err)


NO_BOX_HEADER = "swstyle_no_box_header"


def _no_box_header(view):
    ""


    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup"):
            continue
        flagged = any(w.property(NO_BOX_HEADER) for w in group.findChildren(QtWidgets.QWidget))
        for head in group.children():
            if isinstance(head, QtWidgets.QWidget) and head.inherits("QSint::TaskHeader"):
                if flagged and not head.isHidden():
                    head.hide()
                    head.setProperty(NO_BOX_HEADER, True)
                elif not flagged and head.property(NO_BOX_HEADER):
                    head.setProperty(NO_BOX_HEADER, None)
                    head.show()


STRIP_PAGES = ("Plane",)      # kept for older callers; every page has the strips now (rcmenus pkg197)


_OWN_STRIP = "border-left: 4px solid #3399ff"      # asmpm.PICK_STYLE's strip (a page's own style sheet wins over ours)
_OWN_SHEET = "swstrip_own_sheet"
# pick-box tints the sheet metal / weldment pages give their second, third... boxes (frame scan 11-20: those
# boxes had no strip, so the first strip went to a later box)
_PICK_FILLS = ("ffd6ec", "e6d6ff", "e3d6ff", "ccffff", "ffd6d6", "d6f5d6")


def _own_strip(box, want):
    """A box with its own style sheet strip (the assembly pages) gets the same strip as every other page:
    14 px, in the order colour (frame scan, PM thread 11-20: their boxes all had a thin blue strip)."""
    cur = box.styleSheet() or ""
    if _OWN_STRIP in cur:
        box.setProperty(_OWN_SHEET, cur)        # the page (re)set its own sheet: keep it as the base
    own = box.property(_OWN_SHEET)
    if own is None:
        return
    colour = STRIPS[int(want) - 1] if want else None
    box.setStyleSheet(own.replace(_OWN_STRIP, "border-left: 14px solid %s" % colour) if colour else own)


def _selection_box(b):
    """A box that takes picks from the graphics area: a pick field (swpickbox) or a list the page or FreeCAD
    empties with Delete / Clear Selections (pmboxes.handles). Option lists (types, sizes, tables) are not."""
    if b.property("swpickbox"):
        return True
    if not isinstance(b, QtWidgets.QListWidget):
        return False
    sheet = b.styleSheet() or ""
    if _OWN_STRIP in sheet or b.property(_OWN_SHEET) is not None:
        return True             # the assembly pages' pick boxes (asmpm.PICK_STYLE): their own blue strip
    if any("background: #" + c in sheet for c in _PICK_FILLS):
        return True             # sheet metal / weldment pick boxes tinted by the page (pink, violet...): strip too
    if b.property("swActive") is not None or type(b).__name__ in ("_ItemsList", "PickBox", "_PickList"):
        return True             # the add-on's own pages: a box they mark active, or their pick-list classes
                                # (_PickList: SimulationXpress and the Simulation PMs' Fixture/Load/Contact boxes)
    try:
        from . import pmboxes, pmlistmenu
        return pmboxes.handles(b) or b.objectName() in getattr(pmlistmenu, "HANDLED", ())
    except Exception:
        return False


class BoxGrip(QtWidgets.QWidget):
    ""


    SIZE = (14, 7)

    @classmethod
    def add(cls, box):
        if box.findChild(cls) is None:
            cls(box)

    def __init__(self, box):
        super().__init__(box)
        self.box = box
        self.setObjectName("SWBoxGrip")
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip("Drag to resize the box")
        self.resize(*self.SIZE)
        self._from = None
        self._natural = box.height()
        self._limits = (box.minimumHeight(), box.maximumHeight())
        box.installEventFilter(self)
        self._place()
        self.show()
        self.raise_()

    def _place(self):
        b = self.box
        self.move(int((b.width() - self.width()) / 2), b.height() - self.height() - 1)

    def eventFilter(self, obj, event):
        if obj is self.box and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self._place()
            self.raise_()
        return False

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(QtGui.QColor("#8a8f96"), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        r = min(self.width(), self.height()) / 2.0 - 1
        p.drawEllipse(QtCore.QPointF(self.width() / 2.0, self.height() / 2.0), r, r)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._from = (event.globalPosition().y(), self.box.height())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._from is not None:
            y0, h0 = self._from
            self.box.setFixedHeight(int(max(28, min(800, h0 + event.globalPosition().y() - y0))))
            event.accept()

    def mouseReleaseEvent(self, event):
        self._from = None

    def mouseDoubleClickEvent(self, event):
        lo, hi = self._limits
        self.box.setMinimumHeight(lo)
        self.box.setMaximumHeight(hi)
        if lo == 0 and hi >= 16777215:
            self.box.setFixedHeight(self._natural)       # the height the page gave it, then free again
            self.box.setMinimumHeight(0)
            self.box.setMaximumHeight(hi)
        self.box.updateGeometry()
        w = self.box.parentWidget()
        while w is not None:
            if w.layout() is not None:
                w.layout().activate()
            w = w.parentWidget() if w.parentWidget() is not None and not w.isWindow() else None


def _strips(view, title=None):
    ""


    boxes = [b for b in view.findChildren(QtWidgets.QWidget) if b.isVisible() and _selection_box(b)]
    keep = set(id(b) for b in boxes)
    for box in [b for b in view.findChildren(QtWidgets.QWidget) if b.property(STRIP) and id(b) not in keep]:
        box.setProperty(STRIP, "")
        if box.property(_OWN_SHEET) is not None:
            _own_strip(box, "")
        box.style().unpolish(box)
        box.style().polish(box)
        _refit(box)
    boxes.sort(key=lambda b: (b.mapTo(view, QtCore.QPoint(0, 0)).y(), b.mapTo(view, QtCore.QPoint(0, 0)).x()))
    for box in boxes:
        if isinstance(box, QtWidgets.QListWidget):
            BoxGrip.add(box)
    for i, box in enumerate(boxes):
        want = str(min(i, len(STRIPS) - 1) + 1)
        if _OWN_STRIP in (box.styleSheet() or ""):
            _own_strip(box, want)               # an assembly page's box (again, if the page reset its sheet)
        if box.property(STRIP) != want:
            box.setProperty(STRIP, want)
            if box.property(_OWN_SHEET) is not None:
                _own_strip(box, want)
            box.style().unpolish(box)
            box.style().polish(box)
            _refit(box)


def _refit(box):
    """A list box lays its contents out again for the strip: polish alone redraws the 14 px strip but
    leaves the list's contents where the 1 px border put them, so a picked name was written over the
    strip ("Cut-Extrude1" in Linear Pattern's Features box). Setting the box's own style sheet again
    makes it take the strip's width; the text is changed by a trailing space so Qt does not skip it."""
    if not isinstance(box, QtWidgets.QAbstractScrollArea):
        return
    try:
        sheet = box.styleSheet() or ""
        box.setStyleSheet(sheet[:-1] if sheet.endswith(" ") else sheet + " ")
    except Exception as _fw_err:
        _fw_log("propertymanager.py:refit", _fw_err)


def _editing_type():
    try:
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        return editobj.type_id(edit) if edit is not None else None
    except Exception:
        return None


def _reword(view):
    ""
    words = WORDS.get(_editing_type())
    if not words:
        return
    words = localized(words)
    header = view.findChild(QtWidgets.QWidget, HEADER)
    inside = set(id(w) for w in _children(header)) if header is not None else set()     # pkg97: one walk, not a parent walk per widget
    for widget in _children(view):
        if widget.objectName() == HEADER or id(widget) in inside:
            continue
        if isinstance(widget, QtWidgets.QComboBox):
            _reword_combo(widget, words)
        elif isinstance(widget, QtWidgets.QGroupBox):
            new = words.get(widget.title())
            if new and new != widget.title():
                _remember(widget, widget.title())
                widget.setTitle(new)
        elif isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
            text = widget.text()
            new = words.get(text)
            if new and new != text:
                _remember(widget, text)
                widget.setText(new)


def _reword_combo(combo, words):
    renamed = False
    for i in range(combo.count()):
        new = words.get(combo.itemText(i))
        if new and new != combo.itemText(i):
            if not renamed:
                _remember(combo, [combo.itemText(j) for j in range(combo.count())])
                renamed = True
            combo.setItemText(i, new)


def _remember(widget, original):
    if widget.property(_ORIGINAL) is None:
        widget.setProperty(_ORIGINAL, original)


def _inside_header(widget):
    parent = _parent_widget(widget)
    while parent is not None:
        if parent.objectName() == HEADER:
            return True
        parent = _parent_widget(parent)
    return False


def _unword(view):
    for widget in _children(view):
        original = widget.property(_ORIGINAL)
        if original is None:
            continue
        try:
            if isinstance(widget, QtWidgets.QComboBox):
                for i, text in enumerate(original):
                    if i < widget.count():
                        widget.setItemText(i, text)
            elif isinstance(widget, QtWidgets.QGroupBox):
                widget.setTitle(original)
            else:
                widget.setText(original)
            widget.setProperty(_ORIGINAL, None)
        except RuntimeError as _fw_err:
            _fw_log("propertymanager.py:1095", _fw_err)


def _strip_group_icons(view):
    ""
    for box in _boxes(view):
        for label in _children(box, QtWidgets.QToolButton):
            if label.property("class") != "header" or label.icon().isNull():
                continue
            _header_icons.setdefault(id(label), (label, label.icon()))
            label.setIcon(QtGui.QIcon())


def pm_comment():
    """The comment of the feature being edited, when Show Comments in PropertyManager is on."""
    try:
        from . import optionspages
        if not optionspages.stored("FeatureManager", "Show Comments in PropertyManager", True):
            return ""
        gdoc = Gui.ActiveDocument
        edit = gdoc.getInEdit() if gdoc is not None else None
        obj = editobj.of(edit) if edit is not None else None
        return (getattr(obj, "Comment", "") or "").strip() if obj is not None else ""
    except Exception:
        return ""


class Header(QtWidgets.QWidget):
    """Title, check/cross and help, wired to FreeCAD's own dialog buttons."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName(HEADER)
        self.view = view
        self.box = None
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 6)
        outer.setSpacing(6)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        self.icon = QtWidgets.QLabel(self)
        self.icon.setFixedSize(20, 20)
        self.title = QtWidgets.QLabel(self)
        self.title.setObjectName("SWStyle_PMTitle")
        self.help = self._tool("PM_HELP", "Help")
        self.help_native = None
        self.help.clicked.connect(self.show_help)

        self.pin = self._tool("PIN_NORMAL", "Keep Visible")
        self.pin.setCheckable(True)
        self.pin.toggled.connect(self._pin_icon)
        self.feature = None      # (document, object name, command) of the feature being made
        self.page = None         # the own page's title while it is open (Keep Visible)
        self.ok_seen = False     # OK was pressed on the open page (not Cancel / Escape)
        top.addWidget(self.icon)
        top.addWidget(self.title, 1)
        top.addWidget(self.help)
        outer.addLayout(top)
        self.row = QtWidgets.QHBoxLayout()
        self.row.setSpacing(2)
        self.row.addStretch(1)
        outer.addLayout(self.row)
        # Options > FeatureManager > Show Comments in PropertyManager: the feature's comment
        self.comment = QtWidgets.QLabel(self)
        self.comment.setObjectName("SWStyle_PMComment")
        self.comment.setWordWrap(True)
        self.comment.setStyleSheet("QLabel { background: #fff6c8; color: #3a3000; border: 1px solid #d8c060;"
                                   " padding: 3px; }")
        self.comment.hide()
        outer.addWidget(self.comment)

        from . import detailedpreview
        self.eye, self.detail = detailedpreview.make_button(self)
        self.eye.hide()
        self.row.insertWidget(0, self.eye)

        self.undo = self._tool("STANDARD_UNDO", "Undo")
        self.redo = self._tool("STANDARD_REDO", "Redo")
        self.undo.hide()
        self.redo.hide()
        self.row.insertWidget(1, self.undo)
        self.row.insertWidget(2, self.redo)

        self.row.insertWidget(3, self.pin)
        from . import pmundo
        pmundo.register_buttons(self.undo, self.redo)
        outer.addWidget(self.detail)
        self.buttons = []
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self.sync)
        self.timer.start()
        # pkg97: a page that opens or closes is dressed at once, not at the next tick: the
        # TaskPanel gets the page's boxes as children, and the view says so (taskUpdate)
        self._soon_pending = False
        try:
            view.taskUpdate.connect(self._soon)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:1193", _fw_err)
        self._watched = []
        for panel in _children(view):
            if _class(panel) == "Gui::TaskView::TaskPanel":
                panel.installEventFilter(self)
                self._watched.append(panel)
        view.installEventFilter(self)

    def eventFilter(self, obj, event):
        try:
            if isinstance(event, QtCore.QEvent) and event.type() in (QtCore.QEvent.ChildAdded, QtCore.QEvent.ChildRemoved):
                self._soon()
        except Exception as _fw_err:
            _fw_log("propertymanager.py:1206", _fw_err)
        return False

    def _soon(self, *args):
        """One sync as soon as the event loop is free (the page is complete by then)."""
        if self._soon_pending:
            return
        self._soon_pending = True
        QtCore.QTimer.singleShot(0, self._sync_now)

    def _sync_now(self):
        self._soon_pending = False
        try:
            self.sync()
        except RuntimeError as _fw_err:
            _fw_log("propertymanager.py:1221", _fw_err)
        self.timer.start()      # the next tick counts from here

    def _tool(self, family, tip, tint=None):
        button = QtWidgets.QToolButton(self)
        button.setAutoRaise(True)
        button.setIconSize(QtCore.QSize(20, 20))
        button.setToolTip(tip)
        icon = icons.family(family)
        if tint and not icon.isNull():
            icon = _tinted(icon, tint)
        if icon.isNull():
            icon = _drawn(family)
            button.setProperty("fw_drawn", family)      # drawn in the theme's colours: redrawn on a theme change
        if icon.isNull():
            button.setText(tip)
        else:
            button.setIcon(icon)
        return button

    def _retheme(self):
        """The header's drawn pictures (the "?" and the eye) follow a theme switch: drawn once in Light, the grey
        "?" stayed nearly invisible on Dark."""
        try:
            now = theme.current_theme() if theme is not None else None
        except Exception:
            now = None
        if now == getattr(self, "_drawn_theme", now):
            self._drawn_theme = now
            return
        self._drawn_theme = now
        for b in self.findChildren(QtWidgets.QToolButton):
            family = b.property("fw_drawn")
            if family:
                icon = _drawn(family)
                if not icon.isNull():
                    b.setIcon(icon)

    ERROR_CSS = ("color: #c00000;", "color: #ff8a8a;")

    def _error_lines(self):
        ""


        try:
            want = error_css()
            for label in self.view.findChildren(QtWidgets.QLabel):
                css = label.styleSheet().strip()
                if css in self.ERROR_CSS and css != want:
                    label.setProperty("swstyle_warning", True)
                    label.setStyleSheet(want)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:error_lines", _fw_err)

    def sync(self):
        """Mirror the native button box: which buttons exist, enabled, visible."""
        global _current_title
        self._retheme()
        self._error_lines()
        title, icon = _title(self.view)
        _current_title = (id(self.view), title)
        try:
            self._sync(title, icon)
        finally:
            _current_title = None

    def _prompt_follow(self, control):
        """pkg243: a page's status-bar prompt goes with the page. Mirror's "Select a face or plane to
        mirror about." stayed on under the next page (Delete Face). When the page changes, the prompt
        the old page left is cleared, unless the new page has already put up its own."""
        try:
            bar = Gui.getMainWindow().statusBar()
            now = bar.currentMessage()
            try:
                import shiboken6
                key = shiboken6.getCppPointer(control)[0] if control is not None else None
            except Exception:
                key = id(control) if control is not None else None
            was = getattr(self, "_prompt_page", None)
            if key != was:
                if was is not None and now and now == getattr(self, "_prompt_text", None):
                    bar.clearMessage()
                    now = ""
                self._prompt_page = key
            self._prompt_text = now if control is not None else None
        except Exception as _fw_err:
            _fw_log("propertymanager.py:1270", _fw_err)

    def _sync(self, title, icon):
        if self.title.text() != title:
            self.title.setText(title)
        self.icon.setPixmap(icon.pixmap(20, 20) if not icon.isNull() else QtGui.QPixmap())
        self.icon.setVisible(not icon.isNull())
        text = pm_comment()
        if self.comment.text() != text:
            self.comment.setText(text)
        self.comment.setVisible(bool(text))
        control = _edit_control(self.view)
        self._prompt_follow(control)
        box = control.findChild(QtWidgets.QDialogButtonBox) if control is not None else None
        if control is not None:
            control.setVisible(False)
        # Watchers only (no command running): no PropertyManager header.
        self.setVisible(control is not None)
        # PySide can hand back a stale wrapper (a QSpacerItem) while a stock panel builds.
        natives = [] if box is None else [b for b in box.buttons()
                                          if isinstance(b, QtWidgets.QAbstractButton) and not b.isHidden()]
        if box is not self.box or [n for n, _ in self.buttons] != natives:
            self._rebuild(box, natives)
        blocked = pmmessage.blocked(self.view)       # a field cannot be read: OK is not ready
        for native, mine in self.buttons:
            try:
                enabled = native.isEnabled()
                if box is not None and box.buttonRole(native) in OK_ROLES:
                    # NO DEAD CONTROLS: OK stays live; pressed before the page is ready it says in red
                    # what is still missing (pmkeys.accept)
                    mine.setProperty("fw_ready", bool(enabled and not blocked))
                    enabled = True
                mine.setEnabled(enabled)
            except RuntimeError as _fw_err:
                _fw_log("propertymanager.py:1299", _fw_err)
        # each dressing in its own try: one failure (a stale wrapper, a panel we do not know)
        # must not leave the rest of the panel native
        def _boxes(view):

            if control is not None:
                _strips(view, title)
                _tight_groups(view)
                _fold_memory(view, title)
        for name, dress in (("group icons", _strip_group_icons), ("wording", _reword),
                            ("boxes", _boxes),
                            ("selection boxes", selectionbox.install), ("fields", pmfields.install),
                            ("bodies", multibody.install_pm), ("contours", contours.install),
                            ("fillet/chamfer", filletchamfer.install), ("keys", pmkeys.install),
                            ("values", pmvalues.install), ("tab order", _tab_order),
                            ("handles", pmhandles.install), ("messages", pmmessage.install),
                            ("preview", pmpreview.install), ("boxes2", pmboxes.install),
                            ("layout", pmlayout.install), ("undo", pmundo.install),
                            ("no box header", _no_box_header), ("narrow", _narrow_rows)):
            try:
                pmfields.purge_stale(self.view)     # a dressing before may have left one
                try:
                    dress(self.view)
                except (AttributeError, TypeError) as stale:
                    if "LayoutItem" not in str(stale) and "WidgetItem" not in str(stale):
                        raise
                    pmfields.purge_stale(self.view)     # a stale wrapper came up mid-way: once more (each is idempotent)
                    dress(self.view)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: PropertyManager %s not dressed: %r\n" % (name, error))
        try:
            _open_focus(self.view, control, title)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: PropertyManager opening focus: %r\n" % error)
        try:
            from . import detailedpreview
            detailedpreview.sync(self.eye, self.detail, control is not None)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:1329", _fw_err)
        self._follow(control is not None)

    def retheme(self):
        """The look switched theme: colour the panel again."""
        view = self.view
        if id(view) in _saved:
            view.setPalette(_theme_palette(view.palette()))
            view.setStyleSheet(_qss())
        self._pin_icon(self.pin.isChecked())
        try:
            pmlayout.retheme(view)
        except Exception as _fw_err:
            _fw_log("propertymanager.py:1342", _fw_err)
        self.update()

    def show_help(self):
        """The feature's help: its entry in the User Guide (FreeCAD's own Help button opened the online wiki)."""

        kind = _editing_type()
        native = "Sketcher_Workbench" if kind == "Sketcher::SketchObject" else _feature_command(kind)
        try:
            from . import pmhelp
            pmhelp.show(self.view, self.title.text(), native)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no help for %s (%s)\n" % (self.title.text(), error))

    def _ok_pressed(self, *args):
        self.ok_seen = True

    def _pin_icon(self, on):
        family = "PIN_ACTIVE" if on else "PIN_NORMAL"
        icon = icons.family(family)
        if icon.isNull():
            icon = _drawn(family)
        if not icon.isNull():
            self.pin.setIcon(icon)

    def _follow(self, open_):
        """Remember the feature in the panel; when it is finished with OK and the pin
        is in, start the same feature again."""
        title = self.title.text()
        self.pin.setVisible(open_ and title in KEEP_VISIBLE and title not in ("Mate", "Smart Dimension"))
        shows = open_ and pmundo.shows_buttons(title)
        self.undo.setProperty("fw_shows", bool(shows))
        self.redo.setProperty("fw_shows", bool(shows))
        if not open_ and (pmundo.depth() != (0, 0) or pmundo._watchers):
            pmundo.clear()
        pmundo._refresh()
        if open_:
            if self.feature is None:
                self.feature = _editing_command()
            if self.page is None and title in KEEP_VISIBLE_COMMANDS:
                self.page = title
            return
        feature, self.feature = self.feature, None
        page, self.page = self.page, None
        ok_seen, self.ok_seen = self.ok_seen, False
        if feature is None:


            if page is not None and ok_seen and self.pin.isChecked():
                QtCore.QTimer.singleShot(200, lambda: _restart(KEEP_VISIBLE_COMMANDS[page]))
            elif not ok_seen:
                self.pin.setChecked(False)
            return
        doc_name, name, command = feature
        try:
            doc = App.getDocument(doc_name)
        except Exception:
            return
        if doc is None or doc.getObject(name) is None:
            return  # Cancelled: the new feature is gone.
        pmkeys.finished(doc_name, name)
        if not self.pin.isChecked():
            return
        QtCore.QTimer.singleShot(200, lambda: _restart(command))

    def _rebuild(self, box, natives):
        # (OK_ROLES: module level, the roles whose button stays live and says what is missing)
        for _, mine in self.buttons:
            if mine is not self.help:
                mine.setParent(None)
                mine.deleteLater()
        self.buttons = []
        self.box = box
        self.help_native = None
        if box is None:
            return
        roles = QtWidgets.QDialogButtonBox
        only = len(natives) == 1
        index = 0
        for native in natives:
            role = box.buttonRole(native)
            text = native.text().replace("&", "")
            if role == roles.HelpRole:
                self.help_native = native
                self.buttons.append((native, self.help))
                continue
            # A lone Close finishes the command (check); a lone Cancel stays a cross.
            cancel = box.standardButton(native) == roles.Cancel
            if role in (roles.AcceptRole, roles.YesRole, roles.ApplyRole) or (only and not cancel):
                mine = self._tool("CHECK_MARK", text or "OK", OK_GREEN)
            elif role in (roles.RejectRole, roles.NoRole, roles.DestructiveRole):
                mine = self._tool("STANDARD_CANCEL", text or "Cancel")
            else:
                mine = QtWidgets.QToolButton(self)
                mine.setText(text)
                mine.setToolTip(text)
            if role in OK_ROLES or role == roles.AcceptRole:
                # pressed, not clicked: the panel (and its button) is gone before clicked's other
                # slots run; click() emits pressed first. Also the corner's OK and Enter. (It sat under
                # Apply / Yes only, so a plain OK never counted and Keep Visible never opened the page again.)
                native.pressed.connect(self._ok_pressed)
            if role == roles.AcceptRole:
                mine.clicked.connect(lambda *_, button=native: pmkeys.accept(button))
            elif role in OK_ROLES:
                # Apply / Yes: as before when the page allows it (FEM's Apply re-meshes); else what is missing
                mine.clicked.connect(lambda *_, button=native: button.click() if button.isEnabled() else pmkeys.accept(button))
            elif role in (roles.RejectRole, roles.NoRole, roles.DestructiveRole):
                # features-420: a Cancel pressed while the preview rebuilds waits for it (pmkeys.when_idle)
                mine.clicked.connect(lambda *_, button=native: pmkeys.when_idle(button.click, button))
            else:
                mine.clicked.connect(native.click)
            self.row.insertWidget(index, mine)
            index += 1
            self.buttons.append((native, mine))

    def release(self):
        self.timer.stop()
        control = _edit_control(self.view)
        if control is not None:
            control.setVisible(True)
        self.setParent(None)
        self.deleteLater()


OK_ROLES = (QtWidgets.QDialogButtonBox.AcceptRole, QtWidgets.QDialogButtonBox.YesRole,
            QtWidgets.QDialogButtonBox.ApplyRole)


def _feature_command(kind):
    if not kind or not kind.startswith("PartDesign::"):
        return None
    command = "PartDesign_" + kind.split("::", 1)[1]
    try:
        return command if Gui.Command.get(command) is not None else None
    except Exception:
        return None


def _editing_command():
    try:
        edit = Gui.ActiveDocument.getInEdit()
        obj = editobj.of(edit) if edit is not None else None
    except Exception:
        return None
    command = _feature_command(obj.TypeId) if obj is not None else None
    return (obj.Document.Name, obj.Name, command) if command else None


def _restart(command):
    """Keep Visible: start command again, the way its ribbon button does."""
    try:
        if Gui.Control.activeDialog():
            return
        Gui.Selection.clearSelection()
        if command == "sectionview.start":
            # Section View's command is a toggle (it would turn the section off): its page again
            from . import sectionview
            sectionview.controller().start()
            return
        from . import featureflow
        if not featureflow.run(command):
            Gui.runCommand(command, 0)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: could not start %s again (%s)\n" % (command, error))


def _header_of(widget):
    """The PropertyManager header of the page widget sits on, or None."""
    w = widget
    while w is not None:
        if w.inherits("Gui::TaskView::TaskView") or w.objectName() == "PMRoot":
            break
        w = w.parentWidget()
    if w is None:
        w = widget.window()
    for header in w.findChildren(Header):
        if header.isVisible():
            return header
    return None


def _header(view):
    for child in view.children():
        if isinstance(child, Header):
            return child
    return None


def style(dock):
    view = _view(dock)
    if view is None:
        return False
    key = id(view)
    if key not in _saved:
        _saved[key] = (view.styleSheet(), QtGui.QPalette(view.palette()))
        view.setPalette(_theme_palette(view.palette()))
        view.setStyleSheet(_qss())
    header = _header(view)
    if header is None:
        header = Header(view)
        view.layout().insertWidget(0, header)
    header.sync()
    return True


def prepare():
    """pkg97: the header (and its watch on the task panel) exists before the first command runs,
    so the first page of the session is dressed at once too."""
    try:
        for dock in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
            if _view(dock) is not None:
                style(dock)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PropertyManager prepare: %r\n" % error)


QtCore.QTimer.singleShot(1500, prepare)


def unstyle(dock):
    view = _view(dock)
    if view is None:
        return False
    header = _header(view)
    if header is not None:
        header.release()
    _unword(view)
    selectionbox.uninstall(view)
    pmkeys.forget(view)
    old = _saved.pop(id(view), None)
    if old is not None:
        view.setStyleSheet(old[0])
        view.setPalette(old[1])
    for label, icon in list(_header_icons.values()):
        try:
            label.setIcon(icon)
        except RuntimeError as _fw_err:
            _fw_log("propertymanager.py:1571", _fw_err)
    _header_icons.clear()
    return True
