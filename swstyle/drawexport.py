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

import os
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawpmparts as P

PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/DrawExport"
PDF_SHEETS = ("Current sheet", "All sheets", "Selected sheets")
DXF_SHEETS = ("Active sheet only", "All sheets to separate files", "All sheets to one file")


def pages(doc):
    from . import drawsheet
    return drawsheet.pages(doc)      # in the sheet order


def current_page(doc):
    p = D.active_page()
    if p is not None and p.Document is doc:
        return p
    ps = pages(doc)
    return ps[0] if ps else None


def options():
    from . import drawdxf
    g = App.ParamGet(PARAM)
    return {"pdf": g.GetString("PdfSheets", "All sheets"), "dxf": g.GetString("DxfSheets", "Active sheet only"),
            "selected": [s for s in g.GetString("Selected", "").split("\n") if s],
            "version": g.GetString("DxfVersion", drawdxf.DEFAULT_VERSION), "scale11": g.GetBool("DxfScale11", False),
            "splines": g.GetString("DxfSplines", "Splines"), "font": g.GetString("DxfFont", "TrueType"),
            "line_styles": g.GetString("DxfLineStyles", drawdxf.LINE_STYLES[0]),
            "merge": g.GetBool("DxfMergeEnds", False),
            "merge_distance": g.GetFloat("DxfMergeDistance", drawdxf.MERGE_DISTANCE),
            "views_blocks": g.GetBool("DxfViewsAsBlocks", False),
            "pdf_color": g.GetBool("PdfColor", True), "pdf_high": g.GetBool("PdfHighQuality", True),
            "pdf_hf": g.GetBool("PdfHeaderFooter", False), "pdf_weights": g.GetBool("PdfPrinterLineWeights", False)}


def set_pdf_options(color=None, high=None, header_footer=None, printer_weights=None):
    """PDF Export Options: Export PDF in color, High quality lines, Print header/footer, Use specified printer
    line weights (the File > Print Line Weights)."""
    g = App.ParamGet(PARAM)
    for key, val in (("PdfColor", color), ("PdfHighQuality", high), ("PdfHeaderFooter", header_footer),
                     ("PdfPrinterLineWeights", printer_weights)):
        if val is not None:
            g.SetBool(key, bool(val))


def set_dxf_options(version=None, scale11=None, splines=None, font=None, line_styles=None, merge=None,
                    merge_distance=None, views_blocks=None):
    """DXF/DWG Export Options: Version, Scale output 1:1, Splines (as splines / polylines), Fonts, Line styles
    (AutoCAD standard styles / custom styles: the hidden lines' linetype), End points merge (Enable merging,
    Merge distance mm)."""
    g = App.ParamGet(PARAM)
    if views_blocks is not None:
        g.SetBool("DxfViewsAsBlocks", bool(views_blocks))
    if merge is not None:
        g.SetBool("DxfMergeEnds", bool(merge))
    if merge_distance is not None:
        g.SetFloat("DxfMergeDistance", max(0.0, float(merge_distance)))
    if line_styles is not None:
        g.SetString("DxfLineStyles", line_styles)
    if version is not None:
        g.SetString("DxfVersion", version)
    if scale11 is not None:
        g.SetBool("DxfScale11", bool(scale11))
    if splines is not None:
        g.SetString("DxfSplines", splines)
    if font is not None:
        g.SetString("DxfFont", font)


def output_scale(page):
    """Scale output 1:1: the factor that brings the sheet's views back to full size (their common scale, else the
    sheet's)."""
    scales = set()
    for v in page.Views:
        if v.isDerivedFrom("TechDraw::DrawViewPart") and not getattr(v, "SWShadeOf", ""):
            try:
                scales.add(round(float(v.Scale), 9))
            except Exception as _fw_err:
                _fw_log("drawexport.py:108", _fw_err)
    k = scales.pop() if len(scales) == 1 else float(getattr(page, "Scale", 1.0) or 1.0)
    return 1.0 / k if k else 1.0


def set_options(pdf=None, dxf=None, selected=None):
    g = App.ParamGet(PARAM)
    if pdf is not None:
        g.SetString("PdfSheets", pdf)
    if dxf is not None:
        g.SetString("DxfSheets", dxf)
    if selected is not None:
        g.SetString("Selected", "\n".join(selected))


def sheets_for(doc, writer, opts=None):
    opts = opts or options()
    every = pages(doc)
    cur = current_page(doc)
    if writer == "pdf":
        how = opts["pdf"]
        if how == "All sheets":
            return every
        if how == "Selected sheets":
            chosen = [p for p in every if p.Label in opts["selected"]]
            return chosen or ([cur] if cur else [])
        return [cur] if cur else []
    if opts["dxf"] in ("All sheets to separate files", "All sheets to one file"):
        return every
    return [cur] if cur else []


class _NoPrint:
    """Layers set not to print are hidden while exporting."""

    def __init__(self, doc):
        self.doc = doc
        self.hidden = []

    def __enter__(self):
        for o in P.non_printing(self.doc):
            try:
                if o.ViewObject is not None and o.ViewObject.Visibility:
                    o.ViewObject.Visibility = False
                    self.hidden.append(o)
            except Exception as _fw_err:
                _fw_log("drawexport.py:154", _fw_err)
        if self.hidden:
            QtWidgets.QApplication.processEvents()
        return self

    def __exit__(self, *_):
        for o in self.hidden:
            try:
                o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("drawexport.py:164", _fw_err)


def _size(page):
    """The sheet's paper (mm); a sheet with no sheet format, or an empty one, prints on Letter landscape."""
    try:
        w, h = float(page.Template.Width), float(page.Template.Height)
        if w > 0 and h > 0:
            return w, h
    except Exception as _fw_err:
        _fw_log("drawexport.py:size", _fw_err)
    return 279.4, 215.9


def _scene(page):
    import TechDrawGui
    from . import drawsheet
    # the scene of the sheet's open window, that window brought to the front (not TechDraw's doubleClicked: on an
    # open sheet it emptied the scene, bench FreeCAD 1.1); a sheet with no window yet is opened
    scene = TechDrawGui.getSceneForPage(page)
    sub = drawsheet.sheet_window(scene)
    if sub is not None:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if mdi is not None and mdi.activeSubWindow() is not sub:
            mdi.setActiveSubWindow(sub)
    else:
        drawsheet.show_page(page)
        QtWidgets.QApplication.processEvents()
        scene = TechDrawGui.getSceneForPage(page)
    QtWidgets.QApplication.processEvents()
    # a sheet window opened just now fills its scene over the next event loops: wait until its item count settles
    # (items are only counted: touching TechDraw's items from Python, e.g. parentItem(), could delete them)
    if scene is not None and list(getattr(page, "Views", []) or []):
        import time
        end, last, same = time.time() + 5.0, -1, 0
        while time.time() < end and same < 3:
            try:
                n = len(scene.items())
            except Exception:
                break
            same = same + 1 if n == last and n > 0 else 0
            last = n
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents, 50)
            time.sleep(0.03)
    return scene


def _fields_current(doc):
    try:
        from . import drawsheet
        drawsheet.fields_current(doc)       # every sheet's title block as it is now (SHEET n OF m)
    except Exception as _fw_err:
        _fw_log("drawexport.py:212", _fw_err)


def write_pdf(doc, path, sheets, opts=None):
    """One PDF: a page per sheet at its paper size (in colour or black and white, high quality lines or not, with
    the Print Header/Footer when asked)."""
    _fields_current(doc)
    # white paper: the sheet's own paper (TechDraw's PageColor, grey on screen) is hidden with the sheet format
    # while drawpdftext writes it; changing PageColor made TechDraw rebuild every sheet's scene
    return _write_pdf(doc, path, sheets, opts)


_COLOUR = re.compile(r'\b(fill|stroke)="(#[0-9a-fA-F]{6})"')
_IMAGE = re.compile(r'(xlink:href|href)="data:image/(png|jpeg|jpg);base64,([^"]+)"')
MONO = {}      # checks: what the last black and white page was written as ("vector", "images")


def _gray(hexcol, opacity=1.0):
    r, g, b = int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return 255 - (255 - y) * max(0.0, min(1.0, opacity))       # as it shows over the white sheet


def mono_svg(svg):
    ""

    from . import drawprint

    def tag(m):
        t = m.group(0)
        attrs = dict(re.findall(r'\b([a-z-]+)="([^"]*)"', t))

        def col(mm):
            key, c = mm.group(1), mm.group(2)
            try:
                op = float(attrs.get(key + "-opacity", "1"))
            except ValueError:
                op = 1.0
            return '%s="%s"' % (key, "#ffffff" if _gray(c, op) > 235 else "#000000")
        t = _COLOUR.sub(col, t)
        t = re.sub(r'\b(fill|stroke)-opacity="[^"]*"', lambda mm: '%s-opacity="1"' % mm.group(1), t)
        return t

    def image(m):
        try:
            img = QtGui.QImage.fromData(QtCore.QByteArray.fromBase64(m.group(3).encode("ascii")))
            if img.isNull():
                return m.group(0)
            base = QtGui.QImage(img.size(), QtGui.QImage.Format_ARGB32)
            base.fill(QtCore.Qt.white)
            p = QtGui.QPainter(base)
            p.drawImage(0, 0, img)
            p.end()
            buf = QtCore.QBuffer()
            buf.open(QtCore.QIODevice.WriteOnly)
            drawprint.mono(base).save(buf, "PNG")
            MONO["images"] = MONO.get("images", 0) + 1
            return '%s="data:image/png;base64,%s"' % (m.group(1), bytes(buf.data().toBase64()).decode("ascii"))
        except Exception:
            return m.group(0)
    svg = re.sub(r"<[a-zA-Z][^<>]*>", tag, svg)
    return _IMAGE.sub(image, svg)


def mono_vector(scene, painter, target, src, high=True):
    ""


    MONO.clear()
    try:
        try:
            from PySide import QtSvg
        except ImportError:
            from PySide6 import QtSvg
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        gen = QtSvg.QSvgGenerator()
        gen.setOutputDevice(buf)
        size = QtCore.QSize(int(target.width()), int(target.height()))
        gen.setSize(size)
        gen.setViewBox(QtCore.QRectF(0, 0, target.width(), target.height()))
        p = QtGui.QPainter(gen)
        p.setRenderHint(QtGui.QPainter.Antialiasing, bool(high))
        scene.render(p, QtCore.QRectF(0, 0, target.width(), target.height()), src, QtCore.Qt.KeepAspectRatio)
        p.end()
        svg = mono_svg(bytes(buf.data()).decode("utf-8", "replace"))
        MONO["svg"] = svg
        import io
        from . import drawpdftext
        # Qt's SVG renderer writes text into a PDF as outlines: the texts are taken out and written as real text
        data, texts = drawpdftext.split_svg(io.BytesIO(svg.encode("utf-8")))
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(data))
        if not r.isValid():
            return False
        painter.fillRect(target, QtCore.Qt.white)
        r.render(painter, target)
        vb = [0.0, 0.0, float(target.width()), float(target.height())]
        MONO["texts"] = drawpdftext.draw_texts(painter, QtCore.QRectF(target), vb, texts, False)
        MONO["vector"] = True
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: black and white PDF: %s\n" % error)
        return False


def _write_pdf(doc, path, sheets, opts=None):
    o = opts or options()
    color, high, hf = o.get("pdf_color", True), o.get("pdf_high", True), o.get("pdf_hf", False)
    # TechDraw's own exportPageAsPdf wrote the sheet format's texts as outlines: every PDF goes through the writer

    from . import drawprint, drawpdftext
    writer = QtGui.QPdfWriter(path)
    writer.setResolution(300 if high else 150)
    painter = None
    for n, page in enumerate(sheets):
        w, h = _size(page)
        size = QtGui.QPageSize(QtCore.QSizeF(w, h), QtGui.QPageSize.Millimeter)
        writer.setPageSize(size)
        writer.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
        if painter is None:
            painter = QtGui.QPainter(writer)
        elif not writer.newPage():
            break
        scene = _scene(page)
        if scene is None:
            continue
        src = QtCore.QRectF(D.to_scene(0, h), D.to_scene(w, 0))
        target = QtCore.QRectF(0, 0, writer.width(), writer.height())
        for it in scene.selectedItems():
            it.setSelected(False)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, bool(high))
        with drawpdftext.RealText(page, scene, color) as texts:
            if color:
                scene.render(painter, target, src, QtCore.Qt.KeepAspectRatio)
            else:
                if not mono_vector(scene, painter, target, src, high):   # its lines stay lines (vector)
                    dpi = 300 if high else 150
                    img = QtGui.QImage(int(w / 25.4 * dpi), int(h / 25.4 * dpi), QtGui.QImage.Format_ARGB32)
                    img.fill(QtCore.Qt.white)
                    p2 = QtGui.QPainter(img)
                    p2.setRenderHint(QtGui.QPainter.Antialiasing, bool(high))
                    scene.render(p2, QtCore.QRectF(0, 0, img.width(), img.height()), src, QtCore.Qt.KeepAspectRatio)
                    p2.end()
                    painter.drawImage(target, drawprint.mono(img))
            texts.draw(painter, target, src)
        if hf:
            drawprint.draw_header_footer(painter, target, doc, page, n + 1, len(sheets))
    if painter is not None:
        painter.end()
    return [path]


def _separate(path, page, n):
    if n == 0:
        return path
    base, ext = os.path.splitext(path)
    return "%s_%s%s" % (base, page.Label.replace(" ", "_"), ext)


def _bend_layer(raw, page):
    ""
    try:
        from . import drawdxf
        drawdxf.bend_layer(raw, drawdxf.bend_segments(page))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: DXF bend lines: %s\n" % error)


def _extra(page, o):
    ""

    from . import drawdxf
    out = []
    try:
        out += drawdxf.view_captions(page)              # SECTION A-A, DETAIL B ... under their views
        if o.get("version", drawdxf.DEFAULT_VERSION) != "R12":    # R12 has no HATCH entity
            out += drawdxf.section_hatches(page)
    except Exception as _fw_err:
        _fw_log("drawexport.py:extra labels/hatch", _fw_err)
    try:
        from . import drawsheet
        tpl = page.Template
        path = drawsheet.page_template_path(page)
        if tpl is not None and path and os.path.isfile(path) and getattr(page, "SWFormatShown", True) is not False:
            out += drawdxf.format_entities(path, dict(getattr(tpl, "EditableTexts", {}) or {}))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: DXF sheet format: %s\n" % error)
    try:
        styles = o.get("line_styles", drawdxf.LINE_STYLES[0])
        out += drawdxf.center_marks(page, drawdxf.center_linetype(styles))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: DXF centre marks: %s\n" % error)
    return out


def _layers(page):
    ""

    from . import drawdxf
    try:
        from . import drawdocprops as DP
        doc = page.Document
        vis = DP._thick(DP.prop(doc, "lf_visible"))           # Line Font > Visible Edges
        thin = DP.thickness_mm("Thin", 0.18, doc)
    except Exception:
        vis, thin = 0.35, 0.18
    try:
        return drawdxf.sheet_layers(page, vis, thin)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: DXF layers: %s\n" % error)
        return None


def view_blocks(page, taken=None, suffix=""):
    """Export drawing views as blocks: {TechDraw layer (object name): block name} for each model view on the sheet,
    its dimensions, balloons and annotations attached to it included."""
    from . import drawdxf
    taken = set() if taken is None else taken
    out = {}
    views = [v for v in page.Views if v.isDerivedFrom("TechDraw::DrawViewPart") and not getattr(v, "SWShadeOf", "")]
    for v in views:
        out[v.Name] = drawdxf.block_name(v.Label + suffix, taken)
    for o in page.Views:
        if o.Name in out:
            continue
        home = None
        try:
            if o.isDerivedFrom("TechDraw::DrawViewDimension") and o.References2D:
                home = o.References2D[0][0]
            elif hasattr(o, "SourceView"):
                home = o.SourceView
            elif hasattr(o, "BaseView"):
                home = o.BaseView
        except Exception:
            home = None
        if home is None:
            try:
                from . import drawattach
                home = drawattach.attached_to(o)
            except Exception:
                home = None
        if home is not None and getattr(home, "Name", None) in out:
            out[o.Name] = out[home.Name]
    return out


def _vblocks(pages, o):
    if not o.get("views_blocks"):
        return None
    taken = set()
    return [view_blocks(p, taken, "" if n == 0 else "_" + p.Label) for n, p in enumerate(pages)]


def _merge(o):
    """The End points merge distance for drawdxf.convert (0 = Enable merging off)."""
    return float(o.get("merge_distance", 0.0)) if o.get("merge") else 0.0


def _hidden(page, o):
    """The sheet's hidden lines for the DXF (in the Line styles' dashed linetype), or None."""
    from . import drawdxf
    try:
        lines = drawdxf.hidden_lines(page)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: DXF hidden lines: %s\n" % error)
        return None
    if not lines:
        return None
    return {"lines": [(0.0, g) for g in lines],
            "linetype": drawdxf.hidden_linetype(o.get("line_styles", drawdxf.LINE_STYLES[0]))}


def write_dxf(doc, path, sheets, dwg=False, opts=None):
    _fields_current(doc)
    import tempfile
    import TechDraw
    from . import drawdxf
    o = opts or options()
    out = []
    if o.get("dxf") == "All sheets to one file" and len(sheets) > 1:
        return [_write_one_dxf(path, sheets, dwg, o)]
    for n, page in enumerate(sheets):
        target = _separate(path, page, n)
        raw = os.path.join(tempfile.mkdtemp(), "techdraw.dxf")
        TechDraw.writeDXFPage(page, raw)
        _bend_layer(raw, page)
        k = output_scale(page) if o.get("scale11") else 1.0
        units, size = drawdxf.doc_units(doc)        # units105: written in the drawing's own units
        k /= size
        version, splines = o.get("version", drawdxf.DEFAULT_VERSION), o.get("splines", "Splines") == "Splines"
        font = o.get("font", "TrueType")
        if dwg:
            import importDWG
            tmp = os.path.join(tempfile.mkdtemp(), "sheet.dxf")
            drawdxf.convert(raw, tmp, version, k, splines, font, hidden=_hidden(page, o), merge=_merge(o) / size,
                            extra=_extra(page, o), layers=_layers(page), view_blocks=_vblocks([page], o), units=units)
            convert = getattr(importDWG, "convertToDwg", None)
            if convert is None or not convert(tmp, target):
                raise RuntimeError("the DWG converter did not write the file")
        else:
            drawdxf.convert(raw, target, version, k, splines, font, hidden=_hidden(page, o), merge=_merge(o) / size,
                            extra=_extra(page, o), layers=_layers(page), view_blocks=_vblocks([page], o), units=units)
        out.append(target)
    return out


SHEET_GAP = 20.0      # mm between sheets laid side by side in one DXF / DWG


def _write_one_dxf(path, sheets, dwg, o):
    """All sheets to one file: every sheet in the same DXF / DWG, side by side from left to right."""
    import tempfile
    import TechDraw
    from . import drawdxf
    raws, x = [], 0.0
    for page in sheets:
        raw = os.path.join(tempfile.mkdtemp(), "techdraw.dxf")
        TechDraw.writeDXFPage(page, raw)
        _bend_layer(raw, page)
        raws.append((raw, x))
        x += _size(page)[0] + SHEET_GAP
    k = output_scale(sheets[0]) if o.get("scale11") else 1.0
    units, size = drawdxf.doc_units(sheets[0].Document)        # units105
    k /= size
    version, splines = o.get("version", drawdxf.DEFAULT_VERSION), o.get("splines", "Splines") == "Splines"
    font = o.get("font", "TrueType")
    target = path
    if dwg:
        import importDWG
        target = os.path.join(tempfile.mkdtemp(), "sheets.dxf")
    lines = []
    for page, (_r, dx) in zip(sheets, raws):
        h = _hidden(page, o)
        if h:
            lines += [(dx, g) for _x, g in h["lines"]]
    hidden = dict(_hidden(sheets[0], o) or {}, lines=lines) if lines else None
    extra, layers = [], {"rename": {}, "records": [], "weights": {}}
    for page, (_r, dx) in zip(sheets, raws):
        extra += [drawdxf.shift_entity(e, dx) for e in _extra(page, o)]
        got = _layers(page) or {}
        layers["rename"].update(got.get("rename", {}))
        layers["weights"].update(got.get("weights", {}))
        have = {drawdxf._name(r) for r in layers["records"]}
        layers["records"] += [r for r in got.get("records", []) if drawdxf._name(r) not in have]
    drawdxf.convert(raws[0][0], target, version, k, splines, font, more=raws[1:], hidden=hidden, merge=_merge(o) / size,
                    extra=extra, layers=layers if layers["records"] else None, view_blocks=_vblocks(sheets, o),
                    units=units)
    if dwg:
        convert = getattr(importDWG, "convertToDwg", None)
        if convert is None or not convert(target, path):
            raise RuntimeError("the DWG converter did not write the file")
    return path


def write(doc, path, writer, opts=None):
    """Save As for a drawing: writer is pdf, dxf, dwg, svg or drawimage (JPEG / PNG / Tif). Returns the files
    written."""
    _fields_current(doc)
    if writer == "drawimage":
        cur = current_page(doc) or (pages(doc)[:1] or [None])[0]
        if cur is None:
            raise RuntimeError("the drawing has no sheet")
        with _NoPrint(doc):
            return write_image(doc, path, cur)
    sheets = sheets_for(doc, "pdf" if writer in ("pdf", "svg") else "dxf", opts)
    if not sheets:
        raise RuntimeError("the drawing has no sheet")
    with _NoPrint(doc):
        if writer == "pdf":
            from . import drawprint
            with drawprint.PrintWeights(sheets, (opts or options()).get("pdf_weights", False)):
                return write_pdf(doc, path, sheets, opts)
        if writer in ("dxf", "dwg"):
            return write_dxf(doc, path, sheets, writer == "dwg", opts)
        import TechDrawGui
        TechDrawGui.exportPageAsSvg(sheets[0], path)
        return [path]


def image_pixels(page, st, screen=None):
    """(width, height) in pixels of a sheet saved as a picture: Print capture, the sheet at the DPI; Screen
    capture, the sheet fitted in the graphics area (screen: its (width, height))."""
    from . import drawprint
    w, h = drawprint._sheet_size(page)
    if st.get("output") == "Print capture":
        k = max(50, min(1200, int(st.get("dpi", 300)))) / 25.4
        return min(14000, int(round(w * k))), min(14000, int(round(h * k)))
    sw, sh = screen or (1920, 1080)
    k = min(sw / w, sh / h)
    return max(1, int(round(w * k))), max(1, int(round(h * k)))


def write_image(doc, path, page):
    ""


    from . import drawprint, saveas
    st = saveas.image_settings()
    scene = _scene(page)
    if scene is None:
        raise RuntimeError("the sheet has no window")
    screen = None
    gv = D.page_view(page)
    if gv is not None and gv.viewport().width() > 10 and gv.viewport().height() > 10:
        screen = (gv.viewport().width(), gv.viewport().height())
    pw, ph = image_pixels(page, st, screen)
    w, h = drawprint._sheet_size(page)
    src = QtCore.QRectF(D.to_scene(0, h), D.to_scene(w, 0))
    img = QtGui.QImage(pw, ph, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.white)
    picked = list(scene.selectedItems())
    for it in picked:
        it.setSelected(False)
    paper = drawprint._white_paper(scene, page)
    painter = QtGui.QPainter(img)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        scene.render(painter, QtCore.QRectF(0, 0, pw, ph), src, QtCore.Qt.KeepAspectRatio)
    finally:
        painter.end()
        for it, brush in paper:
            try:
                it.setBrush(brush)
            except Exception as _fw_err:
                _fw_log("drawexport.py:image paper", _fw_err)
        for it in picked:
            try:
                it.setSelected(True)
            except Exception as _fw_err:
                _fw_log("drawexport.py:image pick", _fw_err)
    img = img.convertToFormat(QtGui.QImage.Format_RGB32)       # JPEG has no alpha; white paper throughout
    img = saveas._toned(img, st.get("type", "RGB"))
    if st.get("output") == "Print capture":
        dpm = int(round(max(50, min(1200, int(st.get("dpi", 300)))) / 0.0254))
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
    if not img.save(path):
        raise RuntimeError("the picture could not be written")
    return [path]


class ExportOptionsDialog(QtWidgets.QDialog):
    """Save As > Options... for a drawing: which sheets go out."""

    def __init__(self, doc, writer="pdf", parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.writer = writer
        self.setObjectName("SWExportOptions")
        self.setWindowTitle("Export Options")
        o = options()
        lay = QtWidgets.QVBoxLayout(self)
        pdf = QtWidgets.QGroupBox("PDF: Export", self)
        pl = QtWidgets.QVBoxLayout(pdf)
        self.pdf = {}
        for name in PDF_SHEETS:
            b = QtWidgets.QRadioButton(name, pdf)
            b.setObjectName("SWExportPdf" + name.replace(" ", ""))
            b.setChecked(name == o["pdf"])
            pl.addWidget(b)
            self.pdf[name] = b
        self.list = QtWidgets.QListWidget(pdf)
        self.list.setObjectName("SWExportSheetList")
        for p in pages(doc):
            it = QtWidgets.QListWidgetItem(p.Label)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if p.Label in o["selected"] else QtCore.Qt.Unchecked)
            self.list.addItem(it)
        self.list.setEnabled(self.pdf["Selected sheets"].isChecked())
        self.pdf["Selected sheets"].toggled.connect(self.list.setEnabled)
        pl.addWidget(self.list)
        self.pdf_color = QtWidgets.QCheckBox("Export PDF in color", pdf)
        self.pdf_color.setObjectName("SWExportPdfColor")
        self.pdf_color.setChecked(o["pdf_color"])
        self.pdf_high = QtWidgets.QCheckBox("High quality lines", pdf)
        self.pdf_high.setObjectName("SWExportPdfHighQuality")
        self.pdf_high.setChecked(o["pdf_high"])
        self.pdf_hf = QtWidgets.QCheckBox("Print header/footer", pdf)
        self.pdf_hf.setObjectName("SWExportPdfHeaderFooter")
        self.pdf_hf.setChecked(o["pdf_hf"])
        self.pdf_weights = QtWidgets.QCheckBox("Use specified printer line weights", pdf)
        self.pdf_weights.setObjectName("SWExportPdfPrinterLineWeights")
        self.pdf_weights.setChecked(o.get("pdf_weights", False))
        for b in (self.pdf_color, self.pdf_high, self.pdf_hf, self.pdf_weights):
            pl.addWidget(b)
        lay.addWidget(pdf)
        dxf = QtWidgets.QGroupBox("DXF/DWG: Export", self)
        dl = QtWidgets.QVBoxLayout(dxf)
        self.dxf = {}
        for name in DXF_SHEETS:
            b = QtWidgets.QRadioButton(name, dxf)
            b.setObjectName("SWExportDxf" + name.replace(" ", ""))
            b.setChecked(name == o["dxf"])
            dl.addWidget(b)
            self.dxf[name] = b
        from . import drawdxf
        grid = QtWidgets.QGridLayout()
        self.version = QtWidgets.QComboBox(dxf)
        self.version.setObjectName("SWExportDxfVersion")
        self.version.addItems([v for v, _ in drawdxf.VERSIONS])
        self.version.setCurrentText(o["version"])
        grid.addWidget(QtWidgets.QLabel("Version:", dxf), 0, 0)
        grid.addWidget(self.version, 0, 1)
        self.font = {}
        frow = QtWidgets.QHBoxLayout()
        for name in ("TrueType", "AutoCAD STANDARD"):
            b = QtWidgets.QRadioButton(name, dxf)
            b.setObjectName("SWExportDxfFont" + name.replace(" ", ""))
            b.setChecked(name == o["font"])
            frow.addWidget(b)
            self.font[name] = b
        fbox = QtWidgets.QButtonGroup(dxf)
        for b in self.font.values():
            fbox.addButton(b)
        grid.addWidget(QtWidgets.QLabel("Fonts:", dxf), 1, 0)
        grid.addLayout(frow, 1, 1)
        self.splines = {}
        srow = QtWidgets.QHBoxLayout()
        sbox = QtWidgets.QButtonGroup(dxf)
        for key, name in (("Splines", "Export all splines as splines"),
                          ("Polylines", "Export all splines as polylines")):
            b = QtWidgets.QRadioButton(name, dxf)
            b.setObjectName("SWExportDxf" + key)
            b.setChecked(key == o["splines"])
            sbox.addButton(b)
            srow.addWidget(b)
            self.splines[key] = b
        grid.addWidget(QtWidgets.QLabel("Splines:", dxf), 2, 0)
        grid.addLayout(srow, 2, 1)
        self.line_styles = {}
        lrow = QtWidgets.QHBoxLayout()
        lbox = QtWidgets.QButtonGroup(dxf)
        for name in drawdxf.LINE_STYLES:
            b = QtWidgets.QRadioButton(name, dxf)
            b.setObjectName("SWExportDxf" + name.replace(" ", ""))
            b.setChecked(name == o.get("line_styles", drawdxf.LINE_STYLES[0]))
            lbox.addButton(b)
            lrow.addWidget(b)
            self.line_styles[name] = b
        grid.addWidget(QtWidgets.QLabel("Line styles:", dxf), 3, 0)
        grid.addLayout(lrow, 3, 1)
        mrow = QtWidgets.QHBoxLayout()
        self.merge = QtWidgets.QCheckBox("Enable merging", dxf)
        self.merge.setObjectName("SWExportDxfMerge")
        self.merge.setChecked(bool(o.get("merge")))
        self.merge_distance = QtWidgets.QDoubleSpinBox(dxf)
        self.merge_distance.setObjectName("SWExportDxfMergeDistance")
        self.merge_distance.setDecimals(4)
        self.merge_distance.setRange(0.0001, 100.0)
        self.merge_distance.setSingleStep(0.01)
        self.merge_distance.setSuffix("mm")
        self.merge_distance.setValue(float(o.get("merge_distance", drawdxf.MERGE_DISTANCE)))
        self.merge_distance.setEnabled(self.merge.isChecked())
        self.merge.toggled.connect(self.merge_distance.setEnabled)
        mrow.addWidget(self.merge)
        mrow.addWidget(QtWidgets.QLabel("Merge distance:", dxf))
        mrow.addWidget(self.merge_distance)
        mrow.addStretch(1)
        grid.addWidget(QtWidgets.QLabel("End points merge:", dxf), 4, 0)
        grid.addLayout(mrow, 4, 1)
        dl.addLayout(grid)
        self.scale11 = QtWidgets.QCheckBox("Scale output 1:1", dxf)
        self.scale11.setObjectName("SWExportDxfScale11")
        self.scale11.setChecked(o["scale11"])
        dl.addWidget(self.scale11)
        self.views_blocks = QtWidgets.QCheckBox("Export drawing views as blocks", dxf)
        self.views_blocks.setObjectName("SWExportDxfViewsAsBlocks")
        self.views_blocks.setToolTip("Each drawing view, with its annotations, goes out as one block.")
        self.views_blocks.setChecked(bool(o.get("views_blocks")))
        dl.addWidget(self.views_blocks)
        # R12 has no splines: they go out as polylines
        self.version.currentTextChanged.connect(
            lambda v: (self.splines["Polylines"].setChecked(True) if v == "R12" else None,
                       self.splines["Splines"].setEnabled(v != "R12")))
        self.splines["Splines"].setEnabled(o["version"] != "R12")
        lay.addWidget(dxf)
        pdf.setEnabled(writer in ("pdf", "svg"))
        dxf.setEnabled(writer in ("dxf", "dwg"))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def ok(self):
        pdf = next(n for n, b in self.pdf.items() if b.isChecked()) if any(b.isChecked() for b in self.pdf.values()) \
            else "All sheets"
        dxf = next(n for n, b in self.dxf.items() if b.isChecked()) if any(b.isChecked() for b in self.dxf.values()) \
            else "Active sheet only"
        sel = [self.list.item(i).text() for i in range(self.list.count())
               if self.list.item(i).checkState() == QtCore.Qt.Checked]
        set_options(pdf, dxf, sel)
        set_pdf_options(self.pdf_color.isChecked(), self.pdf_high.isChecked(), self.pdf_hf.isChecked(),
                        self.pdf_weights.isChecked())
        set_dxf_options(self.version.currentText(), self.scale11.isChecked(),
                        next((k for k, b in self.splines.items() if b.isChecked()), "Splines"),
                        next((k for k, b in self.font.items() if b.isChecked()), "TrueType"),
                        next((k for k, b in self.line_styles.items() if b.isChecked()), None),
                        self.merge.isChecked(), self.merge_distance.value(), self.views_blocks.isChecked())
        self.accept()
