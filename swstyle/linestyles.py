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
import Part
from PySide import QtCore

SKETCH = "Sketcher::SketchObject"

STYLE_OF_LAYER = {1: "Dashed", 11: "Phantom", 12: "Chain", 13: "Center", 14: "Stitch", 15: "Thin/Thick Chain"}
LAYER_OF_STYLE = dict((v, k) for k, v in STYLE_OF_LAYER.items())
LAYER_OF_STYLE["Solid"] = 0


def _mask(seq):
    """16 on/off steps (first step first, as OpenGL's stipple reads the low bit first) -> pattern."""
    m = 0
    for i, on in enumerate(seq[:16]):
        if on:
            m |= 1 << i
    return m


# style -> (pattern, scale factor, extra width in pixels)
PATTERNS = {
    "Dashed": (_mask([1] * 10 + [0] * 6), 1, 0),
    "Phantom": (_mask([1] * 9 + [0] * 2 + [1] + [0] * 2 + [1] + [0]), 2, 0),
    "Chain": (_mask([1] * 11 + [0] * 2 + [1] + [0] * 2), 2, 0),
    "Center": (_mask([1] * 11 + [0] * 2 + [1] + [0] * 2), 3, 0),
    "Stitch": (_mask([1, 1, 0, 0] * 4), 1, 0),
    "Thin/Thick Chain": (_mask([1] * 11 + [0] * 2 + [1] + [0] * 2), 2, 1),
}
OVERLAY = "FWLineStyles"


def layer_of(sketch, index):
    try:
        return sketch.GeometryFacadeList[index].GeometryLayerId
    except Exception:
        return 0


_CACHE = {}       # sketch -> (time, styles): a sketch not in edit is read again once a second


def invalidate():
    _CACHE.clear()


def styled_cached(sketch, now, editing):
    import time
    key = (sketch.Document.Name, sketch.Name)
    hit = _CACHE.get(key)
    count = getattr(sketch, "GeometryCount", None)
    if hit is not None and now - hit[0] < 1.0 and (not editing or (count is not None and hit[2] == count)):
        # fix232: the sketch in edit too, while it has as many entities (a drag no longer reads every
        # entity's layer ten times a second); Line Format calls invalidate() when it sets a style
        return hit[1]
    styles = styled(sketch)
    _CACHE[key] = (now, styles, count)
    return styles


def styled(sketch):
    """{geometry index: style} of the entities drawn with a pattern."""
    out = {}
    try:
        facades = sketch.GeometryFacadeList
    except Exception:
        return out
    for i, f in enumerate(facades):
        try:
            style = STYLE_OF_LAYER.get(f.GeometryLayerId)
        except Exception:
            style = None
        if style:
            out[i] = style
    return out


# ------------------------------------------------------------------------------------- Coin
def _coin():
    from pivy import coin
    return coin


def _find(root, name=None, type_name=None, all_=False):
    coin = _coin()
    sa = coin.SoSearchAction()
    if name is not None:
        sa.setName(coin.SbName(name))
    if type_name is not None:
        sa.setType(coin.SoType.fromName(type_name))
    sa.setInterest(coin.SoSearchAction.ALL if all_ else coin.SoSearchAction.FIRST)
    sa.setSearchingAll(True)
    sa.apply(root)
    if all_:
        paths = sa.getPaths()
        return [paths[i].getTail() for i in range(paths.getLength())]
    p = sa.getPath()
    return p.getTail() if p is not None else None


def _matrix(placement):
    coin = _coin()
    m = placement.toMatrix()
    return coin.SbMatrix(m.A11, m.A21, m.A31, m.A41, m.A12, m.A22, m.A32, m.A42,
                         m.A13, m.A23, m.A33, m.A43, m.A14, m.A24, m.A34, m.A44)


def _overlay_root(scene, name):
    coin = _coin()
    for i in range(scene.getNumChildren()):
        c = scene.getChild(i)
        if c.getName().getString() == name:
            return c
    sep = coin.SoSeparator()
    sep.setName(name)
    scene.addChild(sep)
    return sep


def _drop_overlays(scene, keep=()):
    for i in reversed(range(scene.getNumChildren())):
        c = scene.getChild(i)
        n = c.getName().getString()
        if n.startswith(OVERLAY) and n not in keep:
            scene.removeChild(i)


def _fill(sep, placement, curves, width):
    """curves: [(style or None, [(x,y,z)], [(r,g,b)], pattern of an unstyled curve)]."""
    coin = _coin()
    sep.removeAllChildren()
    ps = coin.SoPickStyle()
    ps.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(ps)
    t = coin.SoMatrixTransform()
    t.matrix.setValue(_matrix(placement))
    sep.addChild(t)
    lm = coin.SoLightModel()
    lm.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(lm)
    for style, pts, colors, base in curves:
        if len(pts) < 2:
            continue
        pattern, scale, extra = PATTERNS[style] if style else (base, 1, 0)
        s = coin.SoSeparator()
        ds = coin.SoDrawStyle()
        ds.lineWidth = float(width + extra)
        ds.linePattern = pattern
        if hasattr(ds, "linePatternScaleFactor"):
            ds.linePatternScaleFactor = int(scale)
        s.addChild(ds)
        bc = coin.SoBaseColor()
        mb = coin.SoMaterialBinding()
        if isinstance(colors, list) and len(colors) == len(pts):
            bc.rgb.setValues(0, len(colors), colors)
            mb.value = coin.SoMaterialBinding.PER_VERTEX
        else:
            c = colors[0] if isinstance(colors, list) else colors
            bc.rgb.setValue(*c)
            mb.value = coin.SoMaterialBinding.OVERALL
        s.addChild(bc)
        s.addChild(mb)
        co = coin.SoCoordinate3()
        co.point.setValues(0, len(pts), pts)
        s.addChild(co)
        ls = coin.SoLineSet()
        ls.numVertices.setValue(len(pts))
        s.addChild(ls)
        sep.addChild(s)


# ------------------------------------------------------------------------------------- edit mode
def _sublayer(sketch, i, facade):
    try:
        if facade.InternalType not in ("None", None, ""):
            return 2
    except Exception as _fw_err:
        _fw_log("linestyles.py:205", _fw_err)
    return 1 if sketch.getConstruction(i) else 0


def _edit_curves(sketch, styles, scene):
    """[(style, pts, colors)] for the styled entities of the sketch in edit, the originals made
    see-through. None when FreeCAD's edit curves cannot be matched to the geometry."""
    coin = _coin()
    geos = sketch.Geometry
    facades = sketch.GeometryFacadeList
    order = {0: [], 1: [], 2: []}
    for i, g in enumerate(geos):
        if isinstance(g, Part.Point):
            continue
        order[_sublayer(sketch, i, facades[i])].append(i)
    out = []
    for k in (0, 1, 2):
        ls = _find(scene, "CurvesLineSet%d" % k)
        co = _find(scene, "CurvesCoordinate%d" % k)
        mat = _find(scene, "CurvesMaterials%d" % k)
        if ls is None or co is None or mat is None:
            return None
        counts = list(ls.numVertices.getValues())
        if len(counts) != len(order[k]):
            return None
        if not any(styles.get(geo) for geo in order[k]):
            if mat.transparency.getNum() and mat.transparency[0] > 0.5:
                mat.transparency.setValue(0.0)      # no styled entity left in this set
            continue
        total = sum(counts)
        pts = co.point.getValues()
        diffuse = mat.diffuseColor.getValues()
        per_vertex = len(diffuse) == total and total != len(counts)
        per_part = len(diffuse) == len(counts)
        base = 0xFFFF
        parent_ds = _find(scene, ("CurvesDrawStyle", "CurvesConstructionDrawStyle", "CurvesInternalDrawStyle")[k])
        if parent_ds is not None:
            base = parent_ds.linePattern.getValue()
        start = 0
        for j, (geo, n) in enumerate(zip(order[k], counts)):
            p = [tuple(pts[q].getValue()) for q in range(start, start + n)]
            if per_vertex:
                cols = [tuple(diffuse[q].getValue()) for q in range(start, start + n)]
            elif per_part:
                cols = [tuple(diffuse[j].getValue())]
            else:
                cols = [tuple(diffuse[0].getValue())] if len(diffuse) else [(0.0, 0.0, 0.0)]
            out.append((styles.get(geo), p, cols, base))
            start += n
        # FreeCAD's own curves of this set go see-through: the copies draw them all
        if not (mat.transparency.getNum() == 1 and mat.transparency[0] > 0.5):
            mat.transparency.setValue(1.0)
    return out


# ------------------------------------------------------------------------------------- outside edit
def _shape_curves(sketch, styles):
    """[(style, pts, color)] for the styled entities of a sketch shown outside edit, its own edges
    of them made see-through. None when its edges cannot be matched to the geometry."""
    coin = _coin()
    vp = sketch.ViewObject
    root = vp.RootNode
    es = _find(root, type_name="SoBrepEdgeSet")
    mat = _find(root, "LineMaterial")
    bind = _find(root, "LineBind")
    co = None
    for i in range(root.getNumChildren()):
        c = root.getChild(i)
        if c.isOfType(coin.SoCoordinate3.getClassTypeId()):
            co = c
            break
    if es is None or mat is None or bind is None or co is None:
        return None
    idx = list(es.coordIndex.getValues())
    edges, cur = [], []
    for v in idx:
        if v < 0:
            if cur:
                edges.append(cur)
            cur = []
        else:
            cur.append(v)
    if cur:
        edges.append(cur)
    curves = [i for i, g in enumerate(sketch.Geometry)
              if not isinstance(g, Part.Point) and not sketch.getConstruction(i)]
    if len(edges) != len(curves):
        return None
    pts = co.point.getValues()
    color = tuple(vp.LineColor[:3])
    out = []
    for geo, e in zip(curves, edges):
        out.append((styles.get(geo), [tuple(pts[j].getValue()) for j in e], [color], 0xFFFF))
    # the sketch's own edges go see-through: the copies draw them all
    if bind.value.getValue() != coin.SoMaterialBinding.OVERALL:
        bind.value = coin.SoMaterialBinding.OVERALL
    if not (mat.transparency.getNum() == 1 and mat.transparency[0] > 0.5):
        mat.transparency.setValue(1.0)
    return out


def _restore(sketch, scene, editing):
    """No styled entity left: FreeCAD's own lines are drawn as they were."""
    coin = _coin()
    if editing:
        for k in (0, 1, 2):
            mat = _find(scene, "CurvesMaterials%d" % k)
            if mat is not None:
                mat.transparency.setValue(0.0)
        return
    root = sketch.ViewObject.RootNode
    mat = _find(root, "LineMaterial")
    bind = _find(root, "LineBind")
    if mat is None or bind is None:
        return
    bind.value = coin.SoMaterialBinding.OVERALL
    mat.diffuseColor.setValue(*tuple(sketch.ViewObject.LineColor[:3]))
    mat.transparency.setValue(0.0)


# ------------------------------------------------------------------------------------- watcher
def _files_busy():
    """A file is opening or a document rebuilding (FreeCAD lets timers run between features then): the pass
    waits, the next tick after does it once (File handling perf-1127)."""
    try:
        if App.isRestoring():
            return True
        for d in App.listDocuments().values():
            if getattr(d, "Restoring", False) or getattr(d, "Recomputing", False):
                return True
    except Exception:
        return False
    return False


class _Watcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.keys = {}
        self.hidden = {}

    def tick(self):
        if _files_busy():
            return            # opening or rebuilding: the next tick after draws the styles once
        try:
            self._tick()
        except Exception as exc:          # a drawing problem must never stop FreeCAD
            App.Console.PrintLog("FreeCAD line styles: %s\n" % exc)

    def _tick(self):
        gdoc = Gui.ActiveDocument
        view = getattr(gdoc, "ActiveView", None) if gdoc else None
        if view is None or not hasattr(view, "getSceneGraph"):
            return
        scene = view.getSceneGraph()
        doc = gdoc.Document
        vp = gdoc.getInEdit()
        edited = getattr(vp, "Object", None)
        import time
        now = time.time()
        keep = []
        hidden = set()
        for sk in doc.Objects:
            if not sk.isDerivedFrom(SKETCH):
                continue
            styles = styled_cached(sk, now, sk is edited)
            if not styles:
                continue
            name = "%s_%s" % (OVERLAY, sk.Name)
            if sk is edited:
                curves = _edit_curves(sk, styles, scene)
                width = 2.0
                ds = _find(scene, "CurvesDrawStyle")
                if ds is not None:
                    width = ds.lineWidth.getValue()
            else:
                if not sk.ViewObject.Visibility:
                    continue
                curves = _shape_curves(sk, styles)
                width = float(sk.ViewObject.LineWidth)
            if curves is None:
                continue
            hidden.add(sk.Name)
            keep.append(name)
            place = sk.getGlobalPlacement()
            key = (sk is edited, repr(place), width, tuple((s, tuple(p), tuple(c), b) for s, p, c, b in curves))
            sep = _overlay_root(scene, name)
            if self.keys.get(name) != key or sep.getNumChildren() == 0:
                _fill(sep, place, curves, width)
                self.keys[name] = key
        for gone in self.hidden.get(doc.Name, set()) - hidden:
            sk = doc.getObject(gone)
            if sk is not None:
                _restore(sk, scene, sk is edited)
        self.hidden[doc.Name] = hidden
        _drop_overlays(scene, keep)
        for n in list(self.keys):
            if n not in keep:
                del self.keys[n]


_WATCHER = []


def install():
    if _WATCHER:
        return
    try:
        w = _Watcher()
    except Exception:
        return
    _WATCHER.append(w)
    w.timer.start()
