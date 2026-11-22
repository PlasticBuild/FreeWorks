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

import base64
import json
import os
import re
import shutil
import zipfile
import zlib

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

PROP = "SWDetailCache"
OPTION = "detail_cache"
SUFFIX = "_Detailing"


# --------------------------------------------------------------------------- the data
def option(doc):
    try:
        from . import drawdocprops as DP
        return bool(DP.prop(doc, OPTION))
    except Exception:
        return False


def _pts(e):
    try:
        if type(e.Curve).__name__ in ("Line", "LineSegment"):
            ps = [e.Vertexes[0].Point, e.Vertexes[-1].Point]
        else:
            ps = e.discretize(Deflection=0.02)
    except Exception:
        return []
    out = []
    for p in ps:
        out += [round(p.x, 3), round(p.y, 3)]
    return out


def view_lines(v):
    """{"visible": [[x, y, x, y...]...], "hidden": [...]} of what v shows now (view geometry, scaled, y down)."""
    out = {"visible": [], "hidden": []}
    for key, fn in (("visible", "getVisibleEdges"), ("hidden", "getHiddenEdges")):
        try:
            edges = getattr(v, fn)() or []
        except Exception:
            edges = []
        for e in edges:
            p = _pts(e)
            if len(p) >= 4:
                out[key].append(p)
    return out


def encode(data):
    return base64.b64encode(zlib.compress(json.dumps(data, separators=(",", ":")).encode(), 6)).decode()


def decode(text):
    try:
        return json.loads(zlib.decompress(base64.b64decode(text)).decode())
    except Exception as _fw_err:
        _fw_log("drawdetail.py:91", _fw_err)
        return None


def _parts(doc):
    return [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawViewPart")]


def store(doc):
    """Every drawn view keeps its lines (views not drawn now, as in Detailing mode, keep what they had)."""
    n = 0
    for v in _parts(doc):
        lines = view_lines(v)
        if not lines["visible"] and not lines["hidden"]:
            continue
        try:
            vo = v.ViewObject
            width = float(getattr(vo, "LineWidth", 0.5) or 0.5)
            hwidth = float(getattr(vo, "HiddenWidth", 0.35) or 0.35)
        except Exception:
            width, hwidth = 0.5, 0.35
        lines["width"], lines["hwidth"] = width, hwidth
        if PROP not in v.PropertiesList:
            v.addProperty("App::PropertyString", PROP, "FreeCAD", "Detailing mode data: the lines the view showed")
            v.setPropertyStatus(PROP, ["Hidden", "Output"])
        text = encode(lines)
        if getattr(v, PROP) != text:
            setattr(v, PROP, text)
        n += 1
    return n


DIM_TYPES = ("TechDraw::DrawViewDimension",)


def _render_items(page):
    """{dimension Name: (scene rect, SVG bytes)} of the dimensions drawn on page's open sheet now (TechDraw draws a
    dimension from its view's lines, so in Detailing mode it would not show)."""
    scene = _scene(page)
    if scene is None:
        return {}
    try:
        from PySide import QtSvg
    except Exception:
        return {}
    names = {o.Name for o in page.Views if o.TypeId in DIM_TYPES}
    out = {}
    for it in scene.items():
        try:
            n = it.data(1)
        except Exception:
            continue
        if not n or str(n) not in names or str(n) in out:
            continue
        r = it.sceneBoundingRect()
        if r.width() <= 0 or r.height() <= 0 or r.width() > 1e5:
            continue
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        gen = QtSvg.QSvgGenerator()
        gen.setOutputDevice(buf)
        gen.setSize(QtCore.QSize(int(r.width()) + 1, int(r.height()) + 1))
        gen.setViewBox(QtCore.QRectF(0, 0, r.width(), r.height()))
        painter = QtGui.QPainter(gen)
        scene.render(painter, QtCore.QRectF(0, 0, r.width(), r.height()), r)
        painter.end()
        out[str(n)] = (r, bytes(buf.data()))
    return out


def store_dimensions(doc):
    n = 0
    for page in [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]:
        if getattr(page, "SWDetailing", False):
            continue
        for name, (r, svg) in _render_items(page).items():
            o = doc.getObject(name)
            if o is None:
                continue
            if PROP not in o.PropertiesList:
                o.addProperty("App::PropertyString", PROP, "FreeCAD", "Detailing mode data: how it was drawn")
                o.setPropertyStatus(PROP, ["Hidden", "Output"])
            setattr(o, PROP, encode({"rect": [r.x(), r.y(), r.width(), r.height()],
                                     "svg": base64.b64encode(svg).decode()}))
            n += 1
    return n


def clear(doc):
    for v in _parts(doc) + [o for o in doc.Objects if o.TypeId in DIM_TYPES]:
        if PROP in v.PropertiesList:
            v.removeProperty(PROP)


def has_data(path):
    try:
        with zipfile.ZipFile(path) as z:
            return PROP.encode() in z.read("Document.xml")
    except Exception:
        return False


# --------------------------------------------------------------------------- the file
_KEEP = re.compile(rb'(<Property name="KeepUpdated" type="App::PropertyBool"[^>]*>\s*<Bool value=")(true|false)(")')
_DET = re.compile(rb'(<Property name="SWDetailing" type="App::PropertyBool"[^>]*>\s*<Bool value=")(true|false)(")')


def _rewrite(src, dst, keep):
    """A copy of the FCStd src at dst with every sheet's Keep Updated set to keep (and Detailing mode off when
    keep, on when not)."""
    tmp = dst + ".part"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "Document.xml":
                val = b"true" if keep else b"false"
                data = _KEEP.sub(lambda m: m.group(1) + val + m.group(3), data)
                data = _DET.sub(lambda m: m.group(1) + (b"false" if keep else b"true") + m.group(3), data)
            zout.writestr(info, data)
    os.replace(tmp, dst)
    return dst


def open_fast(path):
    """Opens the drawing at path in Detailing mode without projecting its views. None when it holds no data."""
    if not has_data(path):
        return None
    folder, base = os.path.split(path)
    stem = os.path.splitext(base)[0]
    copy = os.path.join(folder, stem + SUFFIX + ".FCStd")   # beside it: the models are found the same way
    _rewrite(path, copy, keep=False)
    try:
        doc = App.openDocument(copy)
    finally:
        try:
            os.remove(copy)
        except Exception as _fw_err:
            _fw_log("drawdetail.py:226", _fw_err)
    doc.FileName = path                     # it saves to the drawing's own file
    try:
        doc.Label = stem
    except Exception as _fw_err:
        _fw_log("drawdetail.py:231", _fw_err)
    for o in doc.Objects:
        if o.TypeId == "TechDraw::DrawPage":
            if "SWDetailing" not in o.PropertiesList:
                o.addProperty("App::PropertyBool", "SWDetailing", "FreeCAD", "Detailing mode")
            o.SWDetailing = True
            o.KeepUpdated = False
    try:
        import FreeCADGui as Gui
        Gui.getDocument(doc.Name).Modified = False
    except Exception as _fw_err:
        _fw_log("drawdetail.py:242", _fw_err)
    QtCore.QTimer.singleShot(0, lambda n=doc.Name: _paint_doc(n))
    return doc


def in_detailing(doc):
    return any(o.TypeId == "TechDraw::DrawPage" and getattr(o, "SWDetailing", False) for o in doc.Objects)


# --------------------------------------------------------------------------- drawing the saved lines
_ITEMS = {}         # id(scene) -> {view Name: item}


def _scene(page):
    try:
        import TechDrawGui
        return TechDrawGui.getSceneForPage(page)
    except Exception:
        return None


def _valid(it):
    try:
        import shiboken6 as shiboken
    except Exception:
        try:
            import shiboken2 as shiboken
        except Exception:
            return True
    return shiboken.isValid(it)


def _path(data, key):
    path = QtGui.QPainterPath()
    for flat in data.get(key, []):
        path.moveTo(flat[0] * 10.0, flat[1] * 10.0)
        for i in range(2, len(flat) - 1, 2):
            path.lineTo(flat[i] * 10.0, flat[i + 1] * 10.0)
    return path


def _make_item(v, data):
    from . import drawings as D
    group = QtWidgets.QGraphicsItemGroup()
    for key, wkey, style in (("hidden", "hwidth", QtCore.Qt.DashLine), ("visible", "width", QtCore.Qt.SolidLine)):
        if not data.get(key):
            continue
        it = QtWidgets.QGraphicsPathItem(_path(data, key))
        pen = QtGui.QPen(QtGui.QColor(0, 0, 0))
        pen.setWidthF(float(data.get(wkey, 0.5)) * 10.0)
        pen.setStyle(style)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        it.setPen(pen)
        group.addToGroup(it)
    group.setAcceptedMouseButtons(QtCore.Qt.NoButton)
    group.setData(0, "SWDetailCache")
    x, y = D.view_position(v)
    group.setPos(D.to_scene(x, y))
    try:
        group.setRotation(-float(v.Rotation))
    except Exception as _fw_err:
        _fw_log("drawdetail.py:303", _fw_err)
    group.setZValue(-1)
    return group


def _make_dim_item(data):
    try:
        from PySide import QtSvg
        try:
            from PySide import QtSvgWidgets
            Item = QtSvgWidgets.QGraphicsSvgItem
        except Exception:
            Item = QtSvg.QGraphicsSvgItem
        x, y, w, h = data["rect"]
        rend = QtSvg.QSvgRenderer(QtCore.QByteArray(base64.b64decode(data["svg"])))
        it = Item()
        it.setSharedRenderer(rend)
        it._fw_renderer = rend
        it.setPos(x, y)
        b = it.boundingRect()
        if b.width() > 0 and b.height() > 0:
            it.setTransform(QtGui.QTransform().scale(w / b.width(), h / b.height()))
        it.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        it.setData(0, "SWDetailCache")
        it.setZValue(-1)
        return it
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Detailing dimension: %s\n" % error)
        return None


def _key(v):
    from . import drawings as D
    try:
        return (D.view_position(v), float(getattr(v, "Rotation", 0.0)), len(getattr(v, PROP, "") or ""))
    except Exception:
        return None


def paint(page):
    """The saved lines of the views of page that are not drawn (Detailing mode); removed once a view is drawn or
    Detailing mode is left. Called by the sheet tick."""
    scene = _scene(page)
    if scene is None:
        return []
    mine = _ITEMS.setdefault(id(scene), {})
    want = {}
    if getattr(page, "SWDetailing", False):
        for v in page.Views:
            for o in ([v] + list(getattr(v, "Views", []) or [])):
                if not o.isDerivedFrom("TechDraw::DrawViewPart") or not getattr(o, PROP, ""):
                    continue
                try:
                    if o.getVisibleEdges():
                        continue                # TechDraw draws it itself
                except Exception as _fw_err:
                    _fw_log("drawdetail.py:359", _fw_err)
                want[o.Name] = o
        for o in page.Views:
            if o.TypeId in DIM_TYPES and getattr(o, PROP, ""):
                want[o.Name] = o
    for name in list(mine):
        it, key = mine[name]
        alive = _valid(it)
        if not alive or name not in want or key != _key(want[name]):
            if alive:
                try:
                    scene.removeItem(it)
                except Exception as _fw_err:
                    _fw_log("drawdetail.py:372", _fw_err)
            del mine[name]
    for name, v in want.items():
        if name in mine:
            continue
        data = decode(getattr(v, PROP))
        if not data:
            continue
        it = _make_dim_item(data) if v.TypeId in DIM_TYPES else _make_item(v, data)
        if it is None:
            continue
        scene.addItem(it)
        mine[name] = (it, _key(v))
    return list(mine)


def _paint_doc(name):
    try:
        doc = App.getDocument(name)
    except Exception:
        return
    for p in doc.Objects:
        if p.TypeId == "TechDraw::DrawPage":
            paint(p)


def painted(page):
    scene = _scene(page)
    return [n for n, (it, _k) in _ITEMS.get(id(scene), {}).items() if _valid(it)] if scene is not None else []


# --------------------------------------------------------------------------- saving
class _Observer:
    def slotStartSaveDocument(self, doc, path):
        try:
            if not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects):
                return
            if option(doc):
                store(doc)
                store_dimensions(doc)
            elif not in_detailing(doc):
                clear(doc)              # the option turned off: the data goes
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Detailing mode data: %s\n" % error)
        try:
            from . import drawshade         # reduced display data: the shaded pictures left out of the file
            drawshade.drop_for_save(doc)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: reduced display data: %s\n" % error)

    def slotFinishSaveDocument(self, doc, path):
        try:
            from . import drawshade
            if doc.Name in drawshade.DROPPED:
                from PySide import QtCore
                QtCore.QTimer.singleShot(0, lambda n=doc.Name: _put_back(n))
        except Exception as _fw_err:
            _fw_log("drawdetail.py:429", _fw_err)
        try:
            if in_detailing(doc) and path and os.path.isfile(path):
                _rewrite(path, path, keep=True)   # the file opens as usual anywhere: its sheets keep up to date
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Detailing mode save: %s\n" % error)


def _put_back(name):
    try:
        from . import drawshade
        drawshade.put_back(App.getDocument(name))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: reduced display data: %s\n" % error)


_INSTALLED = []


def install():
    if not _INSTALLED:
        _INSTALLED.append(_Observer())
        App.addDocumentObserver(_INSTALLED[0])
