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

import FreeCAD as App

from . import drawings as D

PPM = 20.0             # picture pixels per sheet millimetre
REZ = 10.0             # TechDraw draws an image one pixel per scene unit (10 per mm)
MAX_PX = 3000
LAST_PPM = {}         # view name -> pixels per mm its last picture was drawn at
SHADED = ("Shaded", "Shaded With Edges")



def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def _shapes(v):
    out = []
    for o in _fw_xs(v) + list(getattr(v, "Source", []) or []):
        try:
            sh = o.Shape
        except Exception:
            continue
        if sh is None or sh.isNull() or not sh.Faces:
            continue
        out.append((o, sh))
    return out


def _colour(o):
    vo = getattr(o, "ViewObject", None)
    for name in ("ShapeColor",):
        try:
            c = getattr(vo, name)
            return c[0], c[1], c[2]
        except Exception as _fw_err:
            _fw_log("drawshade.py:60", _fw_err)
    try:
        m = vo.ShapeAppearance[0]
        c = m.DiffuseColor
        return c[0], c[1], c[2]
    except Exception as _fw_err:
        _fw_log("drawshade.py:66", _fw_err)
    return 0.75, 0.75, 0.78


def _alpha(o):
    """Opacity of one source component, from its current view material (0..1)."""
    vo = getattr(o, "ViewObject", None)
    try:
        if vo.OverrideMaterial:
            return max(0.0, min(1.0, 1.0 - float(vo.ShapeMaterial.Transparency)))
    except Exception as _fw_err:
        _fw_log("drawshade.py:77", _fw_err)
    try:
        return max(0.0, min(1.0, 1.0 - float(vo.ShapeAppearance[0].Transparency)))
    except Exception as _fw_err:
        _fw_log("drawshade.py:81", _fw_err)
    try:
        return max(0.0, min(1.0, 1.0 - float(vo.Transparency) / 100.0))
    except Exception:
        return 1.0


def _decals(v, shapes):
    ""

    names = set()
    for o, _sh in shapes:
        names.add(o.Name)
        try:
            names.update(x.Name for x in o.OutListRecursive)
        except Exception as _fw_err:
            _fw_log("drawshade.py:decal-sources", _fw_err)
    out = []
    for d in v.Document.Objects:
        of = getattr(d, "DecalOf", None)
        if of is None or "DecalFace" not in getattr(d, "PropertiesList", ()) or of.Name not in names:
            continue
        try:
            if d.ViewObject is not None and not d.ViewObject.Visibility:
                continue
        except Exception as _fw_err:
            _fw_log("drawshade.py:decal-shown", _fw_err)
        picture = getattr(d, "DecalPicture", "") or getattr(d, "ImageFile", "")
        if picture and os.path.exists(picture):
            out.append((d, picture))
    return out


def render(v, path, ppm=PPM):
    ""



    from PySide import QtCore, QtGui
    shapes = _shapes(v)
    if not shapes:
        return None
    d, x, y = D.view_frame(v)
    box = None
    for _o, sh in shapes:
        if box is None:
            box = App.BoundBox(sh.BoundBox)
        else:
            box.add(sh.BoundBox)
    c = box.Center
    light = (d * 0.8 - x * 0.25 + y * 0.35)
    light.normalize()
    tol = max(0.05, box.DiagonalLength / 300.0)
    tris = []                     # (depth, [(u, w) x3], shade colour)
    flat = []                     # each facet's corners (u, w, depth), for the decals' places in the order
    hw = hh = 1e-6
    for o, sh in shapes:
        r, g, b = _colour(o)
        for face in sh.Faces:
            try:
                pts, idx = face.tessellate(tol)
            except Exception:
                continue
            if not idx:
                continue
            rev = face.Orientation == "Reversed"
            uv = []
            for p in pts:
                q = p - c
                uv.append((q.dot(x), q.dot(y), q.dot(d)))
                hw = max(hw, abs(uv[-1][0]))
                hh = max(hh, abs(uv[-1][1]))
            for t in idx:
                p0, p1, p2 = pts[t[0]], pts[t[1]], pts[t[2]]
                n = (p1 - p0).cross(p2 - p0)
                if n.Length < 1e-12:
                    continue
                n.normalize()
                if rev:
                    n = -n
                if n.dot(d) < 0:
                    n = -n                       # a facet seen from behind is lit as its front
                lit = 0.30 + 0.55 * max(0.0, n.dot(light)) + 0.15 * max(0.0, n.dot(d))
                col = QtGui.QColor.fromRgbF(min(1.0, r * lit + 0.04), min(1.0, g * lit + 0.04),
                                            min(1.0, b * lit + 0.04))
                col.setAlphaF(_alpha(o) if getattr(v, "SWSeeThrough", True) else 1.0)
                depth = (uv[t[0]][2] + uv[t[1]][2] + uv[t[2]][2]) / 3.0
                tris.append((depth, (uv[t[0]][:2], uv[t[1]][:2], uv[t[2]][:2]), col))
                flat.append((uv[t[0]], uv[t[1]], uv[t[2]], depth))
    if not tris:
        return None
    # the decals, each laid in the far-first order just in front of its face (vdp185)
    for dec, picture in _decals(v, shapes):
        try:
            if _curved_decal(dec, picture, c, d, x, y, light, tris):
                continue                # draped over its curved face, as in the 3D view
            pl = dec.Placement
            n = pl.Rotation.multVec(App.Vector(0, 0, 1))
            if n.dot(d) <= 1e-6:
                continue                # its face looks away from the viewer
            a, b = dec.XSize.Value / 2.0, dec.YSize.Value / 2.0
            quad = []
            for lx, ly in ((-a, b), (a, b), (a, -b), (-a, -b)):     # the picture's top left, clockwise
                q = pl.multVec(App.Vector(lx, ly, 0)) - c
                quad.append((q.dot(x), q.dot(y), q.dot(d)))
            lit = 0.30 + 0.55 * max(0.0, n.dot(light)) + 0.15 * max(0.0, n.dot(d))
            # after every facet of the face it lies on (the facets in its plane, under it), else at its middle
            m = (n.dot(x), n.dot(y), n.dot(d))
            o = pl.Base - c
            o = (o.dot(x), o.dot(y), o.dot(d))
            near = 0.05 + tol
            under = [f[3] for f in flat if all(abs(sum((pp[i] - o[i]) * m[i] for i in range(3))) <= near
                                              for pp in f[:3])]
            depth = (max(under) if under else sum(q[2] for q in quad) / 4.0) + 1e-6
            tris.append((depth, [q[:2] for q in quad], (picture, lit)))
        except Exception as _fw_err:
            _fw_log("drawshade.py:decal", _fw_err)
    hw *= 1.01
    hh *= 1.01
    k = float(getattr(v, "Scale", 1.0) or 1.0)
    # a big view at the chosen quality would pass MAX_PX: fewer pixels per mm, the same for both sides, so the
    # picture keeps the model's shape (it came out squeezed sideways to the view's lines, vd112, 11-20)
    ppm = min(float(ppm), MAX_PX / (2 * hw * k), MAX_PX / (2 * hh * k))
    LAST_PPM[(v.Document.Name, v.Name)] = ppm
    W = int(min(MAX_PX, max(16, 2 * hw * k * ppm)))
    H = int(min(MAX_PX, max(16, 2 * hh * k * ppm)))
    sx, sy = W / (2 * hw), H / (2 * hh)
    img = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    pt = QtGui.QPainter(img)
    pt.setRenderHint(QtGui.QPainter.Antialiasing, False)
    tris.sort(key=lambda t: t[0])                 # far first (depth along the direction to the viewer)
    shaded = {}
    for _z, uvs, col in tris:
        poly = QtGui.QPolygonF([QtCore.QPointF((u + hw) * sx, (hh - w) * sy) for u, w in uvs])
        if isinstance(col, tuple) and col[0] == "drape":
            _drape_triangle(pt, poly, col[1], col[2], col[3], shaded)
            continue
        if isinstance(col, tuple):
            _decal_on(pt, poly, *col)
            continue
        pt.setBrush(col)
        pt.setPen(QtGui.QPen(col, 0.8))           # the facet's own colour over the seams
        pt.drawPolygon(poly)
    pt.end()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not img.save(path, "PNG"):
        return None
    return 2 * hw * k, 2 * hh * k


def _curved_decal(dec, picture, c, d, x, y, light, tris):
    """A decal on a curved face, draped over it triangle by triangle from the same mesh the 3D view draws
    (decalpm.drape_mesh), each triangle lit as the face there and put in the far-first order just in front
    of the face. True when it was drawn so; False for a flat face (the flat quad is right there)."""
    from . import decalpm
    face = decalpm.face_of(dec)
    if face is None or not decalpm.curved(face):
        return False
    mesh = decalpm.drape_mesh(dec, face)
    if mesh is None:
        return False
    pts, nrm, uvs, keep = mesh
    pl = dec.Placement
    rot = pl.Rotation
    proj = []
    for p in pts:
        q = pl.multVec(p) - c
        proj.append((q.dot(x), q.dot(y), q.dot(d)))
    for t in keep:
        n = rot.multVec(nrm[t[0]] + nrm[t[1]] + nrm[t[2]])
        if n.Length < 1e-12:
            continue
        n.normalize()
        if n.dot(d) <= 1e-6:
            continue                        # this part of the picture is round the back
        lit = 0.30 + 0.55 * max(0.0, n.dot(light)) + 0.15 * max(0.0, n.dot(d))
        depth = (proj[t[0]][2] + proj[t[1]][2] + proj[t[2]][2]) / 3.0 + 1e-4
        tris.append((depth, [proj[i][:2] for i in t], ("drape", picture, [uvs[i] for i in t], lit)))
    return True


def _drape_triangle(pt, poly, picture, uvs, lit, shaded):
    """One draped triangle of a decal's picture: the picture's own triangle (uvs, 0..1 with v up) mapped onto poly."""
    from PySide import QtCore, QtGui
    level = int(round(max(0.0, min(1.0, lit + 0.04)) * 32))
    image = shaded.get((picture, level))
    if image is None:
        image = QtGui.QImage(picture)
        if image.isNull():
            return
        image = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
        tint = QtGui.QPainter(image)
        tint.setCompositionMode(QtGui.QPainter.CompositionMode_Multiply)
        g = level / 32.0
        tint.fillRect(image.rect(), QtGui.QColor.fromRgbF(g, g, g))
        tint.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        tint.drawImage(0, 0, QtGui.QImage(picture).convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied))
        tint.end()
        shaded[(picture, level)] = image
    w, h = float(image.width()), float(image.height())
    (s0, t0), (s1, t1), (s2, t2) = [(u * w, (1.0 - v) * h) for u, v in uvs]
    det = (s1 - s0) * (t2 - t0) - (s2 - s0) * (t1 - t0)
    if abs(det) < 1e-9:
        return
    p0, p1, p2 = poly[0], poly[1], poly[2]
    # the affine map (s, t) -> screen that takes the picture's triangle onto poly
    a = ((p1.x() - p0.x()) * (t2 - t0) - (p2.x() - p0.x()) * (t1 - t0)) / det
    b = ((p2.x() - p0.x()) * (s1 - s0) - (p1.x() - p0.x()) * (s2 - s0)) / det
    cc = ((p1.y() - p0.y()) * (t2 - t0) - (p2.y() - p0.y()) * (t1 - t0)) / det
    dd = ((p2.y() - p0.y()) * (s1 - s0) - (p1.y() - p0.y()) * (s2 - s0)) / det
    tx = p0.x() - a * s0 - b * t0
    ty = p0.y() - cc * s0 - dd * t0
    path = QtGui.QPainterPath()
    path.addPolygon(poly)
    path.closeSubpath()
    pt.save()
    pt.setClipPath(path)
    pt.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    pt.setTransform(QtGui.QTransform(a, cc, b, dd, tx, ty))
    pt.drawImage(0, 0, image)
    pt.restore()


def _decal_on(pt, poly, picture, lit):
    """A decal's picture drawn on the quad poly (its top left first, clockwise), lit as its face."""
    from PySide import QtCore, QtGui
    image = QtGui.QImage(picture)
    if image.isNull():
        return
    image = image.convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied)
    shade = QtGui.QPainter(image)
    shade.setCompositionMode(QtGui.QPainter.CompositionMode_Multiply)
    g = max(0.0, min(1.0, lit + 0.04))
    shade.fillRect(image.rect(), QtGui.QColor.fromRgbF(g, g, g))
    shade.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
    shade.drawImage(0, 0, QtGui.QImage(picture).convertToFormat(QtGui.QImage.Format_ARGB32_Premultiplied))
    shade.end()
    w, h = float(image.width()), float(image.height())
    src = QtGui.QPolygonF([QtCore.QPointF(0, 0), QtCore.QPointF(w, 0), QtCore.QPointF(w, h), QtCore.QPointF(0, h)])
    t = QtGui.QTransform()
    if not QtGui.QTransform.quadToQuad(src, poly, t):
        return
    pt.save()
    pt.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    pt.setTransform(t)
    pt.drawImage(0, 0, image)
    pt.restore()


def picture_of(v):
    page = next((o for o in v.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return None, None
    for o in page.Views:
        if getattr(o, "SWShadeOf", "") == v.Name:
            return page, o
    return page, None


def _faint(v, on):
    """Shaded: the view's lines made hairlines (kept, so the view is still picked and dimensioned)."""
    vo = getattr(v, "ViewObject", None)
    if vo is None:
        return
    if "SWLineWidthBefore" not in v.PropertiesList:
        v.addProperty("App::PropertyFloat", "SWLineWidthBefore", "FreeCAD", "line width before Shaded")
    try:
        if on:
            if not v.SWLineWidthBefore:
                v.SWLineWidthBefore = float(vo.LineWidth)
            vo.LineWidth = 0.05
        elif v.SWLineWidthBefore:
            vo.LineWidth = v.SWLineWidthBefore
            v.SWLineWidthBefore = 0.0
    except Exception as _fw_err:
        _fw_log("drawshade.py:193", _fw_err)


def _under(page, pic, v):
    """The picture under the view's lines (TechDraw's Stack Order didn't move it: it covered half of each edge
    of a Shaded With Edges view, vd112, 11-20): before the view on the sheet, so it is drawn first when the
    sheet opens, and sunk on the open sheet now."""
    try:
        views = list(page.Views)
        if pic in views and v in views and views.index(pic) > views.index(v):
            views.remove(pic)
            views.insert(views.index(v), pic)
            page.Views = views
    except Exception as _fw_err:
        _fw_log("drawshade under", _fw_err)
    from PySide import QtCore
    QtCore.QTimer.singleShot(0, lambda d=pic.Document.Name, n=pic.Name: sink(d, n))


def sink(doc_name, name):
    """The open sheet's item for picture name drawn under the views."""
    try:
        import FreeCADGui as Gui
        from PySide import QtWidgets
        if Gui.getDocument(doc_name) is None:
            return
        for gv in Gui.getMainWindow().findChildren(QtWidgets.QGraphicsView):
            sc = gv.scene()
            if sc is None:
                continue
            for it in sc.items():
                if it.data(0) == "QGIV" and it.data(1) == name and it.zValue() > -1:
                    it.setZValue(-1)
    except Exception as _fw_err:
        _fw_log("drawshade sink", _fw_err)


def apply(v, style):
    """The view's picture for a shaded display style; none for the other styles."""
    page, pic = picture_of(v)
    if page is None:
        return None
    doc = v.Document
    if style not in SHADED:
        if pic is not None:
            doc.removeObject(pic.Name)
        _faint(v, False)
        return None
    try:
        doc.recompute([v])
    except Exception as _fw_err:
        _fw_log("drawshade.py:210", _fw_err)
    path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "shaded", "%s_%s.png" % (doc.Name, v.Name))
    try:
        from . import drawdocprops
        ppm = drawdocprops.shaded_ppm(doc)       # Document Properties > Image Quality
    except Exception:
        ppm = PPM
    size = render(v, path, ppm)
    if size is None:
        return None
    if pic is None:
        pic = doc.addObject("TechDraw::DrawViewImage", "Shading")
        page.addView(pic)
        pic.addProperty("App::PropertyString", "SWShadeOf", "FreeCAD", "the view it shades")
        pic.SWShadeOf = v.Name
        pic.Label = v.Label + " shading"
        for prop in ("X", "Y"):
            try:
                pic.setExpression(prop, "%s.%s" % (v.Name, prop))
            except Exception as _fw_err:
                _fw_log("drawshade.py:230", _fw_err)
    pic.ImageFile = path
    pic.Width, pic.Height = size
    try:
        pic.ScaleType = "Custom"
        pic.Scale = REZ / LAST_PPM.get((v.Document.Name, v.Name), ppm)      # the picture at its size on the sheet
    except Exception as _fw_err:
        _fw_log("drawshade.py:237", _fw_err)
    pic.X, pic.Y = v.X, v.Y
    try:
        pic.Rotation = float(getattr(v, "Rotation", 0) or 0)     # a rotated view: its picture turns with it
    except Exception as _fw_err:
        _fw_log("drawshade rotation", _fw_err)
    try:
        pic.LockPosition = True
    except Exception as _fw_err:
        _fw_log("drawshade.py:242", _fw_err)
    try:
        pic.ViewObject.StackOrder = getattr(v.ViewObject, "StackOrder", 0) - 1     # under the view's lines
    except Exception as _fw_err:
        _fw_log("drawshade.py:246", _fw_err)
    _under(page, pic, v)
    try:
        if getattr(pic.ViewObject, "KeepLabel", None) is not None:
            pic.ViewObject.KeepLabel = False
    except Exception as _fw_err:
        _fw_log("drawshade.py:251", _fw_err)
    _faint(v, style == "Shaded")
    return pic


# --------------------------------------------------------------------------- reduced display data
OPTION = "save_tess"      # Document Properties > Detailing: Save tessellated data for drawings with shaded and
DROPPED = {}


def saves_display_data(doc):
    try:
        from . import drawdocprops as DP
        return bool(DP.prop(doc, OPTION))
    except Exception:
        return True


def pictures(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawViewImage" and getattr(o, "SWShadeOf", "")]


def drop_for_save(doc):
    """Reduced display data: with the option off, the shaded views' pictures are left out of the file (a smaller
    file; they are made again when it opens). Returns the pictures left out."""
    if saves_display_data(doc):
        return []
    out = []
    for pic in pictures(doc):
        path = getattr(pic, "ImageFile", "") or ""
        if not path:
            continue
        keep = os.path.join(App.getUserAppDataDir(), "FreeWorks", "shaded", "%s_%s.png" % (doc.Name, pic.SWShadeOf))
        try:
            if os.path.abspath(path) != os.path.abspath(keep):
                import shutil
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                shutil.copyfile(path, keep)
            # TechDraw keeps a copy of the picture inside the file (ImageIncluded) and won't take an empty one:
            # a 1 x 1 placeholder takes its place, marked so that opening makes the picture again
            pic.ImageFile = _placeholder()
            _mark(pic, True)
            out.append((pic.Name, keep))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: reduced display data: %s\n" % error)
    DROPPED[doc.Name] = out
    return out


def _placeholder():
    path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "shaded", "no_display_data.png")
    if not os.path.isfile(path):
        from PySide import QtGui
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = QtGui.QImage(1, 1, QtGui.QImage.Format_ARGB32)
        img.fill(0)
        img.save(path, "PNG")
    return path


def _mark(pic, on):
    if "SWNoDisplayData" not in pic.PropertiesList:
        pic.addProperty("App::PropertyBool", "SWNoDisplayData", "FreeCAD",
                        "saved without its picture (made again on open)")
    pic.SWNoDisplayData = on


def put_back(doc):
    """After the save: the pictures shown again as before (no rebuild)."""
    for name, path in DROPPED.pop(doc.Name, []):
        pic = doc.getObject(name)
        if pic is None:
            continue
        try:
            _mark(pic, False)
            if os.path.isfile(path):
                pic.ImageFile = path
            else:
                v = doc.getObject(pic.SWShadeOf)
                if v is not None:
                    refresh(v)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: reduced display data: %s\n" % error)
    try:
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("drawshade.py:337", _fw_err)
    try:
        import FreeCADGui as Gui
        Gui.getDocument(doc.Name).Modified = False    # put back as saved: nothing to save
    except Exception as _fw_err:
        _fw_log("drawshade.py:342", _fw_err)


def remake_missing(doc):
    """On open: a file saved without its display data gets its shaded pictures made again."""
    done = []
    for pic in pictures(doc):
        if getattr(pic, "ImageFile", "") and not getattr(pic, "SWNoDisplayData", False):
            continue
        v = doc.getObject(pic.SWShadeOf)
        if v is not None and refresh(v) is not None:
            _mark(pic, False)
            done.append(v.Name)
    if done:
        try:
            doc.recompute()
        except Exception as _fw_err:
            _fw_log("drawshade.py:359", _fw_err)
    return done


def refresh(v):
    """Update View / a changed scale or direction: a shaded view's picture made again."""
    style = getattr(v, "SWDisplayStyle", "")
    if style in SHADED:
        return apply(v, style)
    return None


def refresh_for(obj):
    """The shaded views of obj's model drawn again (a decal added, changed or taken off). Returns how many."""
    done = 0
    for doc in App.listDocuments().values():
        for v in doc.Objects:
            if getattr(v, "SWDisplayStyle", "") not in SHADED:
                continue
            try:
                names = set()
                for o, _sh in _shapes(v):
                    names.add(o.Name)
                    names.update(x.Name for x in o.OutListRecursive)
                if obj.Name in names and obj.Document is v.Document:
                    refresh(v)
                    done += 1
            except Exception as _fw_err:
                _fw_log("drawshade.py:refresh-for", _fw_err)
    return done


class _Follow(object):
    """A shaded view's picture made again when its scale or direction changes."""

    def __init__(self):
        self.busy = False

    def slotChangedObject(self, obj, prop):
        if self.busy or prop not in ("Scale", "Direction", "XDirection", "Rotation"):
            return
        if getattr(obj, "SWDisplayStyle", "") not in SHADED:
            return
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda o=obj: self.redo(o))

    def redo(self, obj):
        self.busy = True
        try:
            refresh(obj)
            obj.Document.recompute()
        except Exception as _fw_err:
            _fw_log("drawshade.py:391", _fw_err)
        finally:
            self.busy = False


_FOLLOW = []


def register():
    if not _FOLLOW:
        f = _Follow()
        App.addDocumentObserver(f)
        _FOLLOW.append(f)
