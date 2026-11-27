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
from PySide import QtCore, QtGui

from . import asmcore as ac

SIZE = 22                   # the glyph's square, in pixels
NODE = "FwMateGlyphs"
STATE = {"node": None, "view": None, "mates": (), "pending": False}
_IMAGES = {}


def _image(kind):
    """(width, height, RGBA bytes bottom row first) of the glyph for a mate kind."""
    if kind in _IMAGES:
        return _IMAGES[kind]
    from . import asmpm
    img = QtGui.QImage(SIZE, SIZE, QtGui.QImage.Format_RGBA8888)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(QtGui.QPen(QtGui.QColor(getattr(asmpm, "MATE_BLUE", "#2b7ea8")), 1))
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(QtCore.QRectF(0.5, 0.5, SIZE - 1.0, SIZE - 1.0))
        icon = asmpm.mate_icon(kind)
        if icon is not None and not icon.isNull():
            pm = icon.pixmap(SIZE - 4, SIZE - 4)
            p.drawPixmap(QtCore.QRect(2, 2, SIZE - 4, SIZE - 4), pm)
    finally:
        p.end()
    img = img.mirrored(False, True)         # Coin's image rows go from the bottom up
    data = bytes(img.constBits())[:SIZE * SIZE * 4] if img.bytesPerLine() == SIZE * 4 else \
        b"".join(bytes(img.constScanLine(y))[:SIZE * 4] for y in range(SIZE))
    _IMAGES[kind] = (SIZE, SIZE, data)
    return _IMAGES[kind]


def anchor(comp, sub):
    """Where a mate's glyph goes for one of its entities, in the assembly: the face's or edge's
    centre (a hole's or a circle's lies on its axis), the vertex itself."""
    try:
        e = ac.element(comp, sub)
    except Exception:
        e = None
    if e is None:
        return None
    try:
        if e.ShapeType == "Vertex":
            return App.Vector(e.Point)
        return App.Vector(e.CenterOfMass)
    except Exception:
        try:
            return App.Vector(e.BoundBox.Center)
        except Exception:
            return None


def glyphs(joint):
    """[(point, kind)] for a mate: one beside each entity it holds."""
    kind = ac.mate_type(joint)
    out = []
    for name in ("Reference1", "Reference2"):
        ref = getattr(joint, name, None)
        if not ref or ref[0] is None:
            continue
        subs = ref[1] if len(ref) > 1 and ref[1] else [""]
        pt = anchor(ref[0], subs[0])
        if pt is not None:
            out.append((pt, kind))
    return out


def picked_mates():
    """The mates picked now, with their assembly: (assembly, [mates]) or (None, [])."""
    try:
        doc = App.ActiveDocument
        asm = ac.assembly_of(doc) if doc is not None else None
        if asm is None:
            return None, []
        mates = set(ac.mates(asm))
        out = []
        for s in Gui.Selection.getSelectionEx(doc.Name, 0):
            o = s.Object
            if o in mates and o not in out:
                out.append(o)
            for sub in s.SubElementNames or ():
                for part in sub.split("."):
                    m = doc.getObject(part) if part else None
                    if m in mates and m not in out:
                        out.append(m)
        return asm, out
    except Exception as _fw_err:
        _fw_log("asmmateglyph.py:picked", _fw_err)
        return None, []


def _remove():
    node, view = STATE["node"], STATE["view"]
    STATE["node"] = STATE["view"] = None
    STATE["mates"] = ()
    if node is None or view is None:
        return
    try:
        view.getSceneGraph().removeChild(node)
    except Exception as _fw_err:      # the view closed
        _fw_log("asmmateglyph.py:remove", _fw_err)


def _build(items):
    from pivy import coin
    root = coin.SoSeparator()
    root.setName(NODE)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    ann = coin.SoAnnotation()
    root.addChild(ann)
    for pt, kind in items:
        w, h, data = _image(kind)
        sep = coin.SoSeparator()
        tr = coin.SoTranslation()
        tr.translation.setValue(pt.x, pt.y, pt.z)
        sep.addChild(tr)
        im = coin.SoImage()
        im.image.setValue(coin.SbVec2s(w, h), 4, data)
        im.vertAlignment = coin.SoImage.BOTTOM      # up and to the right of the entity
        im.horAlignment = coin.SoImage.LEFT
        sep.addChild(im)
        ann.addChild(sep)
    return root


def refresh():
    """Draw the glyphs of the mates picked now (and take away the old ones)."""
    STATE["pending"] = False
    asm, mates = picked_mates()
    key = tuple(m.Name for m in mates)
    try:
        view = Gui.ActiveDocument.ActiveView if mates and Gui.ActiveDocument is not None else None
    except Exception:
        view = None
    if key == STATE["mates"] and view is STATE["view"] and STATE["node"] is not None:
        return STATE["node"]
    _remove()
    if not mates or view is None or not hasattr(view, "getSceneGraph"):
        return None
    items = []
    for m in mates:
        items.extend(glyphs(m))
    if not items:
        return None
    try:
        node = _build(items)
        view.getSceneGraph().addChild(node)
        STATE.update(node=node, view=view, mates=key)
        return node
    except Exception as _fw_err:
        _fw_log("asmmateglyph.py:draw", _fw_err)
        return None


def _later():
    if not STATE["pending"]:
        STATE["pending"] = True
        QtCore.QTimer.singleShot(0, refresh)


class _Observer:
    def addSelection(self, doc, obj, sub, pnt):
        _later()

    def removeSelection(self, doc, obj, sub):
        _later()

    def setSelection(self, doc):
        _later()

    def clearSelection(self, doc):
        _later()


_OBSERVER = []


def install():
    if _OBSERVER:
        return
    obs = _Observer()
    Gui.Selection.addObserver(obs)
    _OBSERVER.append(obs)
