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

from . import drawings as D

Qt = QtCore.Qt

STYLES = (("Solid", 1), ("Dashed", 2), ("Phantom", 5), ("Chain", 4), ("Center", 4), ("Stitch", 3),
          ("Thin/Thick Chain", 4))
THICKNESS = (("Default", None), ("0.18mm", 0.18), ("0.25mm", 0.25), ("0.35mm", 0.35), ("0.5mm", 0.5),
             ("0.7mm", 0.7), ("1mm", 1.0), ("1.4mm", 1.4))
DEFAULT = (1, 0.5, (0.0, 0.0, 0.0))
ANNOTATIONS = ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon", "TechDraw::DrawLeaderLine",
               "TechDraw::DrawRichAnno", "TechDraw::DrawViewSymbol", "TechDraw::DrawWeldSymbol",
               "TechDraw::DrawTileWeld", "TechDraw::DrawViewAnnotation")
COLOR_PARAM = "SWColorDisplayMode"


# ---------------------------------------------------------------- what is picked
def active():
    try:
        return D.in_drawing() and D.active_page() is not None
    except Exception as _fw_err:
        _fw_log("drawlineformat.py:54", _fw_err)
        return False


def picked():
    """[("edge", view, index)], [("view", view)], [("anno", obj)] from the selection on the drawing."""
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        o = s.Object
        if o is None or o.isDerivedFrom("TechDraw::DrawPage") or o.isDerivedFrom("TechDraw::DrawTemplate"):
            continue
        subs = [n.split(".")[-1] for n in s.SubElementNames if n]
        if o.isDerivedFrom("TechDraw::DrawViewPart"):
            edges = [int(n[4:]) for n in subs if n.startswith("Edge") and n[4:].isdigit()]
            if edges:
                out += [("edge", o, i) for i in edges]
            elif not subs:
                out.append(("view", o))
        elif o.TypeId in ANNOTATIONS or getattr(o, "SWAnnotation", ""):
            out.append(("anno", o))
    return out


# ---------------------------------------------------------------- edge formats, kept on the view
def formats(v):
    out = {}
    for line in list(getattr(v, "SWEdgeFormats", []) or []):
        try:
            i, st, w, c = line.split("|")
            out[int(i)] = (int(st), float(w), tuple(float(x) for x in c.split(",")))
        except Exception as _fw_err:
            _fw_log("drawlineformat.py:83", _fw_err)
    return out


def _store(v, table):
    if "SWEdgeFormats" not in v.PropertiesList:
        v.addProperty("App::PropertyStringList", "SWEdgeFormats", "FreeCAD", "Line Format: edge style|width|colour")
    v.SWEdgeFormats = ["%d|%d|%g|%s" % (i, st, w, ",".join("%g" % x for x in c))
                       for i, (st, w, c) in sorted(table.items())]


def color_display(doc=None):
    """Color Display Mode: True shows line colours, False draws them black."""
    doc = doc or App.ActiveDocument
    return bool(getattr(doc, "Meta", {}).get(COLOR_PARAM, "1") == "1") if doc is not None else True


def _hidden(v):
    return set(getattr(v, "SWHiddenEdges", []) or [])


def apply_view(v):
    """Draw v's edges with their kept formats (Color Display Mode and Hide/Show Edges honoured). TechDraw 1.1's
    formatGeometricEdge on an edge that already has a format leaves the view's format list broken (the next
    change crashes FreeCAD, bench 11-11), so the list is cleared and made again, every edge new."""
    if _busy(v):                          # never while the view's lines are being made (it crashes)
        if v.Name not in _LATER:
            _LATER.add(v.Name)
            doc = v.Document
            QtCore.QTimer.singleShot(300, lambda n=v.Name, dn=doc.Name: _later(dn, n))
        return
    table = formats(v)
    hidden = _hidden(v)
    black = not color_display(v.Document)
    try:
        v.clearGeomFormats()
        for i in sorted(set(table) | hidden):
            st, w, c = table.get(i, DEFAULT)
            v.formatGeometricEdge(int(i), int(st), float(w), (0.0, 0.0, 0.0) if black else tuple(float(x) for x in c),
                                  i not in hidden)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Line Format: %s\n" % error)


_LATER = set()


def _busy(v):
    try:
        return bool(v.isWaitingForHlr()) if hasattr(v, "isWaitingForHlr") else False
    except Exception:
        return False


def _later(doc_name, name):
    _LATER.discard(name)
    try:
        v = App.getDocument(doc_name).getObject(name)
    except Exception:
        v = None
    if v is not None:
        apply_view(v)


def apply_edge(v, index, fmt=None):
    """Edge index of v as kept (fmt, when given, is kept first)."""
    if fmt is not None:
        table = formats(v)
        table[int(index)] = fmt
        _store(v, table)
    apply_view(v)


def edge_count(v):
    try:
        return len(v.getVisibleEdges()) + len(v.getHiddenEdges())
    except Exception:
        return 0


def _edges_of(items):
    """{view: [indices]} for picked edges and whole views (every edge of a picked view)."""
    out = {}
    for it in items:
        if it[0] == "edge":
            out.setdefault(it[1], []).append(it[2])
        elif it[0] == "view":
            out.setdefault(it[1], []).extend(range(edge_count(it[1])))      # visible and hidden lines
    return out


def _change(label, items, edge_fn, anno_fn=None, view_fn=None):
    doc = App.ActiveDocument
    if doc is None or not items:
        return False
    doc.openTransaction(label)
    try:
        for v, ids in _edges_of(items).items():
            table = formats(v)
            for i in ids:
                table[i] = edge_fn(table.get(i, DEFAULT))
            _store(v, table)
            apply_view(v)
        for it in items:
            if it[0] == "anno" and anno_fn is not None:
                anno_fn(it[1].ViewObject)
            elif it[0] == "view" and view_fn is not None:
                view_fn(it[1].ViewObject)
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    return True


def set_color(items, color):
    """color: QColor, (r, g, b) in 0..1, or None for the default (black)."""
    if isinstance(color, QtGui.QColor):
        color = (color.redF(), color.greenF(), color.blueF())
    c = tuple(color) if color is not None else DEFAULT[2]

    def anno(vo):
        if "Color" in vo.PropertiesList:
            vo.Color = c
    return _change("Line Color", items, lambda f: (f[0], f[1], c), anno)


def set_thickness(items, width):
    w = DEFAULT[1] if width is None else float(width)

    def vo_width(vo):
        if "LineWidth" in vo.PropertiesList:
            vo.LineWidth = w
    return _change("Line Thickness", items, lambda f: (f[0], w, f[2]), vo_width, vo_width)


def set_style(items, style):
    return _change("Line Style", [it for it in items if it[0] != "anno"], lambda f: (int(style), f[1], f[2]))


def set_color_display(doc, on):
    meta = dict(doc.Meta)
    meta[COLOR_PARAM] = "1" if on else "0"
    doc.Meta = meta
    for v in doc.Objects:
        if v.isDerivedFrom("TechDraw::DrawViewPart") and getattr(v, "SWEdgeFormats", None):
            apply_view(v)
    doc.recompute()


def reapply(doc):
    """Edge formats again after a view is made again (TechDraw keeps GeomFormats by index)."""
    for v in doc.Objects:
        if v.isDerivedFrom("TechDraw::DrawViewPart") and getattr(v, "SWEdgeFormats", None):
            apply_view(v)


# ---------------------------------------------------------------- the drop-downs and commands on a drawing
def _sample(pattern, width):
    try:
        from . import lineformat, style
        color = QtGui.QColor("#e6e6e6") if style.dark() else QtGui.QColor(Qt.black)
        return lineformat._sample(pattern, width, color)
    except Exception:
        return QtGui.QIcon()


def style_menu(parent=None):
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("SWLineStyleMenu")
    items = [it for it in picked() if it[0] != "anno"]
    cur = set()
    for v, ids in _edges_of(items).items():
        table = formats(v)
        cur |= {table.get(i, DEFAULT)[0] for i in ids}
    patterns = {"Solid": "solid", "Dashed": "dash", "Phantom": "phantom", "Chain": "chain", "Center": "center",
                "Stitch": "stitch", "Thin/Thick Chain": "chain"}
    for text, st in STYLES:
        a = menu.addAction(_sample(patterns[text], 1.5), text)
        a.setObjectName("SWLineStyle_" + text.replace("/", ""))
        a.setCheckable(True)
        a.setChecked(cur == {st} and text in ("Solid", "Dashed", "Phantom", "Chain", "Stitch"))
        a.setEnabled(bool(items))
        a.triggered.connect(lambda _c=False, s=st: set_style(picked(), s))
    return menu


def thickness_menu(parent=None):
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("SWLineThicknessMenu")
    items = picked()
    for text, w in THICKNESS:
        a = menu.addAction(_sample("solid", 2.0 if w is None else max(1.0, w * 6)), text)
        a.setObjectName("SWLineThickness_" + text)
        a.setEnabled(bool(items))
        a.triggered.connect(lambda _c=False, width=w: set_thickness(picked(), width))
    return menu


def pick_color(parent=None):
    items = picked()
    if not items:
        return None
    start = QtGui.QColor(Qt.black)
    it = items[0]
    try:
        if it[0] == "edge":
            start = QtGui.QColor.fromRgbF(*formats(it[1]).get(it[2], DEFAULT)[2])
        elif it[0] == "anno" and "Color" in it[1].ViewObject.PropertiesList:
            start = QtGui.QColor.fromRgbF(*it[1].ViewObject.Color[:3])
    except Exception as _fw_err:
        _fw_log("drawlineformat.py:295", _fw_err)
    box = QtWidgets.QColorDialog(start, parent or Gui.getMainWindow())
    box.setWindowTitle("Line Color")
    box.setObjectName("SWLineColor")
    default = QtWidgets.QPushButton("Default")
    default.setObjectName("SWLineColorDefault")
    default.clicked.connect(lambda: (set_color(items, None), box.reject()))
    box.layout().addWidget(default)
    box.colorSelected.connect(lambda c: set_color(items, c))
    try:
        from . import lineformat
        lineformat.LAST[:] = [box]
    except Exception as _fw_err:
        _fw_log("drawlineformat.py:308", _fw_err)
    box.open()
    return box


def _wrap(part_fn, draw_fn):
    def fn(*a, **k):
        return draw_fn(*a, **k) if active() else part_fn(*a, **k)
    fn._sw_drawing = True
    return fn


def _patch_lineformat():
    from . import lineformat as LF
    if getattr(LF.style_menu, "_sw_drawing", False):
        return
    LF.style_menu = _wrap(LF.style_menu, style_menu)
    LF.thickness_menu = _wrap(LF.thickness_menu, thickness_menu)
    LF.pick_color = _wrap(LF.pick_color, pick_color)
    for name, cmd in LF.COMMANDS.items():
        part_active = cmd.IsActive
        cmd.IsActive = (lambda p=part_active: (App.ActiveDocument is not None and bool(picked())) if active()
                        else p())
    LF.COMMANDS["SWStyle_LineColor"].run = lambda: LF.pick_color()
    LF.COMMANDS["SWStyle_LineThickness"].run = lambda: LF._popup(LF.thickness_menu())
    LF.COMMANDS["SWStyle_LineStyle"].run = lambda: LF._popup(LF.style_menu())


# ---------------------------------------------------------------- the toolbar's drawing buttons
EXTRA = (("LayerProperties", "Layer Properties", "Opens the drawing's layers", "TechDraw_ToggleFrame"),
         ("HideShowEdges", "Hide/Show Edges", "Hides or shows model edges of a drawing view", "TechDraw_ShowAll"),
         ("ColorDisplayMode", "Color Display Mode", "Shows the line colours set, or every line black",
          "TechDraw_DecorateLine"))


def _extra_clicked(key, button):
    page = D.active_page()
    if page is None:
        return
    if key == "LayerProperties":
        from . import drawpmparts as PP
        PP.LayerDialog(page.Document).exec_()
    elif key == "HideShowEdges":
        Gui.runCommand("FreeWorks_DrawHideShowEdges", 0)
    elif key == "ColorDisplayMode":
        set_color_display(page.Document, button.isChecked())


def _patch_toolbar():
    from . import linebar as LB
    tb = LB.toolbar(create=False)
    if tb is None or tb.property("sw_drawing_buttons"):
        return tb is not None
    from . import lineformat as LF
    # the drop-downs look the menu up when they open (so the drawing one is used on a drawing)
    for name, getter in (("SWStyle_LineThickness", lambda: LF.thickness_menu),
                         ("SWStyle_LineStyle", lambda: LF.style_menu)):
        b = tb.buttons.get(name)
        if b is None or b.menu() is None:
            continue
        holder = b.menu()
        try:
            holder.aboutToShow.disconnect()
        except Exception as _fw_err:
            _fw_log("drawlineformat.py:372", _fw_err)
        holder.aboutToShow.connect(lambda h=holder, g=getter: LB.LineFormatToolbar._fill(h, g()))
    acts = []
    first = tb.actions()[0] if tb.actions() else None
    for key, label, tip, icon in EXTRA:
        b = QtWidgets.QToolButton(tb)
        b.setObjectName("SWLineFormat_" + key)
        b.setToolTip("<b>%s</b><br>%s" % (label, tip))
        b.setStatusTip(tip)
        b.setAutoRaise(True)
        try:
            b.setIcon(QtGui.QIcon(D.pixmap(icon)))
        except Exception:
            b.setText(label)
        if key == "ColorDisplayMode":
            b.setCheckable(True)
            b.setChecked(True)
        b.clicked.connect(lambda _c=False, k=key, w=b: _extra_clicked(k, w))
        if key == "LayerProperties" and first is not None:
            acts.append(tb.insertWidget(first, b))
        else:
            acts.append(tb.addWidget(b))
    tb.setProperty("sw_drawing_buttons", True)
    _ACTS[:] = acts
    return True


_ACTS = []
_TIMER = []


def _tick():
    try:
        if not _patch_toolbar():
            return
        from . import linebar as LB
        tb = LB.toolbar(create=False)
        if tb is None or not tb.isVisible():
            return
        on = active()
        for a in _ACTS:
            if a.isVisible() != on:
                a.setVisible(on)
        if on:
            b = tb.findChild(QtWidgets.QToolButton, "SWLineFormat_ColorDisplayMode")
            want = color_display(D.active_page().Document)
            if b is not None and b.isChecked() != want:
                b.setChecked(want)
    except Exception as _fw_err:
        _fw_log("drawlineformat.py:421", _fw_err)


def install():
    try:
        _patch_lineformat()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: drawing Line Format: %s\n" % error)
    if not _TIMER:
        t = QtCore.QTimer()
        t.setInterval(500)
        t.timeout.connect(_tick)
        t.start()
        _TIMER.append(t)
