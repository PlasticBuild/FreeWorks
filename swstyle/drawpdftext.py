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
import xml.etree.ElementTree as ET

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

ED = "{https://www.freecad.org/wiki/index.php?title=Svg_Namespace}editable"
SVG_NS = "http://www.w3.org/2000/svg"


def _num(text, default=0.0):
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)", str(text or ""))
    return float(m.group(1)) if m else default


def _style(el):
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _get(el, name, inherited=None):
    v = _style(el).get(name)
    if v is None:
        v = el.get(name)
    return inherited if v is None else v


def split_svg(svg_path, values=None):
    """(the SVG without its texts as bytes, [text]) of a sheet format. Each text: {"x", "y" (SVG user units,
    transforms applied), "size", "family", "weight", "fill", "anchor", "text"}; a field's text is its value from
    values {field: value} (the sheet's EditableTexts)."""
    from . import drawdxf
    values = values or {}
    for prefix, uri in (("", SVG_NS), ("freecad", ED[1:].split("}")[0]),
                        ("xlink", "http://www.w3.org/1999/xlink")):
        try:
            ET.register_namespace(prefix, uri)
        except Exception as _fw_err:
            _fw_log("drawpdftext.py:62", _fw_err)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    texts = []

    def walk(el, m, inh):
        tag = el.tag.split("}")[-1]
        m = drawdxf._mat(m, drawdxf._transform(el.get("transform")))
        inh = dict(inh)
        for k in ("font-size", "font-family", "font-weight", "fill", "text-anchor"):
            v = _get(el, k)
            if v is not None:
                inh[k] = v
        if (_get(el, "display") == "none") or (_get(el, "visibility") == "hidden"):
            return
        for ch in list(el):
            ctag = ch.tag.split("}")[-1]
            if ctag == "text":
                _collect(ch, m, inh)
                el.remove(ch)
            else:
                walk(ch, m, inh)

    def _collect(el, m, inh):
        inh = dict(inh)
        for k in ("font-size", "font-family", "font-weight", "fill", "text-anchor"):
            v = _get(el, k)
            if v is not None:
                inh[k] = v
        m = drawdxf._mat(m, drawdxf._transform(el.get("transform")))
        field = el.get(ED)
        spans = [s for s in el.iter() if s.tag.split("}")[-1] == "tspan"]
        if field is not None and field in values:
            lines = str(values[field]).split("\n")
        elif spans:
            lines = ["".join(s.itertext()) for s in spans]
        else:
            lines = ["".join(el.itertext())]
        x0, y0 = _num(el.get("x")), _num(el.get("y"))
        k = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            s = spans[i] if i < len(spans) else (spans[-1] if spans else el)
            sinh = dict(inh)
            for kk in ("font-size", "font-family", "font-weight", "fill", "text-anchor"):
                v = _get(s, kk)
                if v is not None:
                    sinh[kk] = v
            size = _num(sinh.get("font-size"), 3.5)
            x = _num(s.get("x"), x0) if s.get("x") is not None else x0
            y = _num(s.get("y"), y0) if s.get("y") is not None else y0
            if i >= max(len(spans), 1):     # a line past the text's own lines: one line further down each
                y += (i - max(len(spans), 1) + 1) * size * 1.25
            X = m[0] * x + m[2] * y + m[4]
            Y = m[1] * x + m[3] * y + m[5]
            texts.append({"x": X, "y": Y, "size": size * k, "family": sinh.get("font-family", "osifont"),
                          "weight": sinh.get("font-weight", "normal"), "fill": sinh.get("fill", "#000000"),
                          "anchor": sinh.get("text-anchor", "start"), "text": line,
                          "angle": math.degrees(math.atan2(m[1], m[0]))})

    walk(root, (1, 0, 0, 1, 0, 0), {})
    return ET.tostring(root, encoding="utf-8"), texts


def _view_box(svg_path):
    try:
        root = ET.parse(svg_path).getroot()
        vb = [float(v) for v in re.findall(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?", root.get("viewBox", ""))]
        if len(vb) == 4:
            return vb
        return [0.0, 0.0, _num(root.get("width")), _num(root.get("height"))]
    except Exception:
        return None


_OSIFONT = []      # the family name osifont's file registered under (TechDraw's own font file)


def _osifont():
    """TechDraw's osifont, registered from its file so a PDF can embed it as text (PC 11-13: on Windows the
    title block text came out as outlines; a family Qt only finds by substitution is drawn as paths)."""
    if _OSIFONT:
        return _OSIFONT[0]
    import os
    fam = "osifont"
    roots = [App.getResourceDir(), App.getHomePath(), os.path.join(App.getHomePath(), "share"),
             os.path.join(App.getHomePath(), "data")]
    for r in roots:
        for sub in (("Mod", "TechDraw", "Resources", "fonts"), ("examples",)):
            path = os.path.join(r, *sub, "osifont-lgpl3fe.ttf")
            if os.path.isfile(path):
                try:
                    fid = QtGui.QFontDatabase.addApplicationFont(path)
                    got = QtGui.QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                    if got:
                        fam = got[0]
                        break
                except Exception as _fw_err:
                    _fw_log("drawpdftext.py:161", _fw_err)
        else:
            continue
        break
    _OSIFONT.append(fam)
    return fam


def _family(text):
    """The family to draw a text with: the SVG's first family when Qt has it, else osifont (from its file)."""
    first = str(text or "").split(",")[0].strip().strip("'\"")
    first = {"sans": "sans-serif"}.get(first, first)
    if not first or first.lower().startswith("osifont"):
        return _osifont()
    try:
        if first not in QtGui.QFontDatabase.families():
            return _osifont()
    except Exception as _fw_err:
        _fw_log("drawpdftext.py:179", _fw_err)
    return first


def _colour(text):
    c = QtGui.QColor(str(text or "#000000"))
    return c if c.isValid() and str(text).lower() != "none" else None


LAST = {}       # checks: what the last PDF page wrote ("texts", "error")


class RealText(object):
    """with RealText(page, scene) as rt: render the scene, then rt.draw(painter, target, src).
    While inside, TechDraw's drawing of the sheet format is hidden; draw() paints the format from a copy without
    its texts (Qt SVG), then the texts as real text."""

    def __init__(self, page, scene, color=True):
        self.page, self.scene, self.color = page, scene, color
        self.item, self.texts, self.vb, self.renderer, self.hidden, self.modified = None, [], None, None, False, None
        self.symbols = []       # [(svg item, renderer of the copy without texts, its view box, texts)]

    def __enter__(self):
        LAST.clear()
        try:
            from PySide import QtSvg
        except ImportError:
            from PySide6 import QtSvg
        try:
            from . import drawsheet
            path = drawsheet.page_template_path(self.page)
            tpl = self.page.Template
            vo = getattr(tpl, "ViewObject", None) if tpl is not None else None
            if vo is None or not path or not vo.Visibility:
                LAST["error"] = "no sheet format shown"
                self._symbols(QtSvg)
                return self
            values = dict(getattr(tpl, "EditableTexts", {}) or {})
            data, texts = split_svg(path, values)
            self.vb = _view_box(path)
            r = QtSvg.QSvgRenderer(QtCore.QByteArray(data))
            if not r.isValid() or not self.vb:
                LAST["error"] = "copy not valid"
                self._symbols(QtSvg)
                return self
            self.renderer, self.texts, self.item = r, texts, vo
            # TechDraw's drawing of the format (and the screen's paper colour) hidden while the PDF is written
            self.modified = self._modified()
            vo.Visibility = False
            self.hidden = True
            QtWidgets.QApplication.processEvents()
        except Exception as error:
            LAST["error"] = str(error)
            App.Console.PrintWarning("FreeCAD: PDF text: %s\n" % error)
            self.texts = []
        self._symbols(QtSvg)
        return self

    def _modified(self):
        try:
            import FreeCADGui as Gui
            return Gui.getDocument(self.page.Document.Name).Modified
        except Exception:
            return None

    def _symbols(self, QtSvg):
        """The tables (BOM, revision, hole...), balloons and other symbol annotations: their texts as real text too
        (drawings-land281; Qt's SVG renderer wrote them as outlines, so a PDF's BOM was not searchable)."""
        import io
        try:
            by_name = {}
            for it in self.scene.items():
                n = it.data(1)
                if n:                           # only a view's own group carries its name
                    by_name.setdefault(str(n), it)
            for o in list(getattr(self.page, "Views", []) or []):
                svg = str(getattr(o, "Symbol", "") or "")
                if "<text" not in svg or o.Name not in by_name:
                    LAST.setdefault("skip", []).append((o.Name, "<text" in svg, o.Name in by_name))
                    continue
                rot = getattr(o, "Rotation", 0.0)
                if abs(float(getattr(rot, "Value", rot) or 0.0)) > 1e-9:
                    continue                    # a turned symbol keeps Qt's drawing
                item = self._svg_item(by_name[o.Name])
                if item is None or not item.isVisible():
                    LAST.setdefault("skip", []).append((o.Name, "item", item))
                    continue
                full = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
                data, texts = split_svg(io.BytesIO(svg.encode("utf-8")))
                bare = QtSvg.QSvgRenderer(QtCore.QByteArray(data))
                vb = full.viewBoxF()
                if not full.isValid() or not bare.isValid() or vb.width() <= 0 or vb.height() <= 0:
                    LAST.setdefault("skip", []).append((o.Name, "svg", full.isValid(), bare.isValid(), str(vb)))
                    continue
                bare.setViewBox(vb)
                LAST.setdefault("symbols", []).append((o.Name, item.type(), str(item.mapRectToScene(item.boundingRect())),
                                                       by_name[o.Name].type()))
                item.setVisible(False)
                self.symbols.append((item, bare, [vb.x(), vb.y(), vb.width(), vb.height()], texts))
        except Exception as error:
            LAST["symbols_error"] = str(error)
            _fw_log("drawpdftext.py:symbols", error)

    @staticmethod
    def _svg_item(top):
        """The item that draws a symbol's SVG (TechDraw's QGCustomSvg, a QGraphicsObject under the view's group)."""
        todo = [top]
        while todo:
            x = todo.pop(0)
            svgish = x is not top and isinstance(x, QtWidgets.QGraphicsObject) and \
                not isinstance(x, QtWidgets.QGraphicsTextItem)       # the caption / label texts are text items
            if svgish and (hasattr(x, "renderer") or not x.childItems()):
                return x
            todo += list(x.childItems())
        return None

    def __exit__(self, *exc):
        for item, _r, _vb, _t in self.symbols:
            try:
                item.setVisible(True)
            except Exception as _fw_err:
                _fw_log("drawpdftext.py:symbols restore", _fw_err)
        if self.hidden and self.item is not None:
            try:
                self.item.Visibility = True
                if self.modified is False:
                    import FreeCADGui as Gui
                    Gui.getDocument(self.page.Document.Name).Modified = False
                QtWidgets.QApplication.processEvents()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: PDF text (restore): %s\n" % error)
        return False

    def draw(self, painter, target, src):
        """The sheet format (without texts) and its texts as real text, over what scene.render(painter, target,
        src) drew."""
        if src.width() <= 0 or src.height() <= 0 or target.width() <= 0 or target.height() <= 0:
            return                      # a sheet with no template has no page area: nothing to draw over
        s = min(target.width() / src.width(), target.height() / src.height())
        ox = target.x() + (target.width() - src.width() * s) / 2.0
        oy = target.y() + (target.height() - src.height() * s) / 2.0

        def dev(p):
            return QtCore.QPointF(ox + (p.x() - src.x()) * s, oy + (p.y() - src.y()) * s)

        def symbols():                  # over the sheet format, as on screen
            ns = 0
            for item, bare, vb, texts in self.symbols:
                try:
                    sb = item.mapRectToScene(item.boundingRect())
                    box = QtCore.QRectF(dev(sb.topLeft()), dev(sb.bottomRight())).normalized()
                    painter.save()
                    bare.render(painter, box)
                    painter.restore()
                    ns += draw_texts(painter, box, vb, texts, self.color)
                except Exception as _fw_err:
                    LAST["symbols_draw_error"] = str(_fw_err)
                    _fw_log("drawpdftext.py:symbols draw", _fw_err)
            LAST["symbol_texts"] = ns
            return ns
        if self.renderer is None or self.item is None or not self.vb:
            return symbols()
        box = QtCore.QRectF(dev(src.topLeft()), dev(src.bottomRight())).normalized()   # the sheet: the format's box
        if not self.color:
            painter.save()
        self.renderer.render(painter, box)
        if not self.color:
            painter.restore()
        n = draw_texts(painter, box, self.vb, self.texts, self.color)
        LAST["texts"] = n
        symbols()
        return n


def draw_texts(painter, box, vb, texts, color=True):
    """split_svg's texts as real text (QPainter.drawText, which a PDF keeps as text), the SVG's view box vb drawn
    into box. Returns how many were drawn."""
    kx = box.width() / vb[2] if vb[2] else 1.0
    ky = box.height() / vb[3] if vb[3] else 1.0
    n = 0
    for t in texts:
        dx = box.x() + (t["x"] - vb[0]) * kx
        dy = box.y() + (t["y"] - vb[1]) * ky
        size = t["size"] * ky
        if size <= 0:
            continue
        font = QtGui.QFont(_family(t["family"]))
        LAST["fonts"] = sorted(set(LAST.get("fonts", [])) | {QtGui.QFontInfo(font).family()})   # checks: what drew
        font.setPixelSize(100)
        if str(t["weight"]).lower() in ("bold", "700", "800", "900"):
            font.setBold(True)
        fm = QtGui.QFontMetricsF(font)
        w = fm.horizontalAdvance(t["text"])
        shift = {"middle": -w / 2.0, "end": -w}.get(t["anchor"], 0.0)
        c = _colour(t["fill"])
        if c is None:
            continue
        if not color:
            if c.lightness() > 235:
                continue                # white in black and white: not drawn (as on paper)
            c = QtGui.QColor("black")
        painter.save()
        painter.translate(dx, dy)
        if abs(t.get("angle", 0.0)) > 0.01:
            painter.rotate(t["angle"])
        painter.scale(size / 100.0, size / 100.0)
        painter.setFont(font)
        painter.setPen(c)
        painter.drawText(QtCore.QPointF(shift, 0.0), t["text"])
        painter.restore()
        n += 1
    return n
