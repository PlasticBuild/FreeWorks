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

import FreeCAD as App

HATCH_ROW = "Display sketch hatch behind geometry"
PICTURE_ROW = "Display sketch pictures in drawings"
PIC_TAG = "SWSketchPictureOf"


def option(text, default):
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


# ------------------------------------------------------------------------------------------- sketch hatch
def sketch_region(view, g):
    """The closed drawing sketch entity of view around geometry point g, as a Part face (the smallest one holding
    g), else None."""
    import Part
    try:
        from . import drawsketch as SK
    except Exception as _fw_err:
        _fw_log("drawsketchopts.py:region", _fw_err)
        return None
    best = None
    for kind, _tags, pts in SK.entities(view):
        poly = SK.profile_points(kind, pts)
        if not poly or len(poly) < 3:
            continue
        try:
            ring = [App.Vector(p[0], p[1], 0) for p in poly]
            face = Part.Face(Part.makePolygon(ring + [ring[0]]))
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:face", _fw_err)
            continue
        if face.Area > 1e-9 and face.isInside(App.Vector(g[0], g[1], 0), 1e-6, True):
            if best is None or face.Area < best.Area:
                best = face
    return best


def _stack(view):
    try:
        return int(getattr(view.ViewObject, "StackOrder", 0) or 0)
    except Exception:
        return 0


def place_hatch(hatch, view):
    """A sketch hatch under (Display sketch hatch behind geometry) or over the view's lines."""
    try:
        behind = bool(option(HATCH_ROW, False))
        hatch.ViewObject.StackOrder = _stack(view) + (-1 if behind else 1)
    except Exception as _fw_err:
        _fw_log("drawsketchopts.py:stack", _fw_err)


def mark_hatch(hatch, view):
    if "SWHatchSketch" not in hatch.PropertiesList:
        hatch.addProperty("App::PropertyBool", "SWHatchSketch", "FreeCAD", "hatches a drawing sketch profile")
    hatch.SWHatchSketch = True
    place_hatch(hatch, view)
    clear_faces(view.Document)


def clear_faces(doc):
    ""


    under = set()
    if option(HATCH_ROW, False):
        under |= {getattr(o, "SWHatchView", "") for o in doc.Objects if getattr(o, "SWHatchSketch", False)}
    under |= {getattr(o, PIC_TAG, "") for o in _picture_views(doc)}
    for v in doc.Objects:
        if not v.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        vo = getattr(v, "ViewObject", None)
        if vo is None or not hasattr(vo, "FaceTransparency"):
            continue
        try:
            kept = "SWFaceTransparencyWas" in v.PropertiesList
            if v.Name in under and not kept:
                v.addProperty("App::PropertyInteger", "SWFaceTransparencyWas", "FreeCAD",
                              "face transparency before something was put under the view's lines")
                v.SWFaceTransparencyWas = int(vo.FaceTransparency)
                vo.FaceTransparency = 100
            elif v.Name not in under and kept:
                vo.FaceTransparency = int(v.SWFaceTransparencyWas)
                v.removeProperty("SWFaceTransparencyWas")
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:faces", _fw_err)


def restack(doc):
    for o in doc.Objects:
        if getattr(o, "SWHatchSketch", False):
            view = doc.getObject(getattr(o, "SWHatchView", "") or "")
            if view is not None:
                place_hatch(o, view)
    clear_faces(doc)


# ------------------------------------------------------------------------------------------- sketch pictures
def _model_docs(view):
    try:
        from . import drawviews as DV
        docs = []
        for o in DV.source_shapes(view):
            d = getattr(o, "Document", None)
            if d is not None and d not in docs:
                docs.append(d)
        return docs
    except Exception as _fw_err:
        _fw_log("drawsketchopts.py:docs", _fw_err)
        return []


def sketch_pictures(doc):
    return [o for o in doc.Objects if o.TypeId == "Image::ImagePlane" and "SWSketch" in o.PropertiesList]


def _shown_in(view, pic):
    """(sheet x, y offset from the view's centre in view units, angle in degrees, width, height) of picture pic in
    view, or None where the view does not look square at it."""
    from . import drawings as D
    from . import drawviews as DV
    pl = pic.getGlobalPlacement() if hasattr(pic, "getGlobalPlacement") else pic.Placement
    normal = pl.Rotation.multVec(App.Vector(0, 0, 1))
    d, x, y = D.view_frame(view)
    if abs(normal.dot(d)) < 0.999:
        return None
    c = DV.model_centre(view)
    rel = pl.Base - c
    u, w = rel.dot(x), rel.dot(y)
    px = pl.Rotation.multVec(App.Vector(1, 0, 0))
    angle = math.degrees(math.atan2(px.dot(y), px.dot(x)))
    return u, w, angle, float(pic.XSize), float(pic.YSize)


def _picture_views(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawViewSymbol" and getattr(o, PIC_TAG, "")]


def _svg(path, width, height, biggest=1600):
    """The picture as an SVG symbol width x height mm (the image kept inside, as a drawing keeps its pictures).
    TechDraw's image views ignore the stack order and would lie over the view's lines: a symbol keeps it."""
    import base64
    from PySide import QtCore, QtGui
    img = QtGui.QImage(path)
    if img.isNull():
        return None
    if max(img.width(), img.height()) > biggest:
        img = img.scaled(biggest, biggest, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    data = QtCore.QByteArray()
    buf = QtCore.QBuffer(data)
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    b64 = base64.b64encode(bytes(data)).decode("ascii")
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="%gmm" '
            'height="%gmm" viewBox="0 0 %g %g"><image x="0" y="0" width="%g" height="%g" preserveAspectRatio="none" '
            'xlink:href="data:image/png;base64,%s"/></svg>' % (width, height, width, height, width, height, b64))


def _page_of(view):
    try:
        p = view.findParentPage()
        if p is not None:
            return p
    except Exception as _fw_err:
        _fw_log("drawsketchopts.py:page", _fw_err)
    return next((p for p in view.InListRecursive if p.isDerivedFrom("TechDraw::DrawPage")), None)


def refresh_pictures(doc):
    """The drawing doc's sketch pictures made to match the option, the views and the models' pictures."""
    if doc is None or not any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects):
        return []
    want = {}
    if option(PICTURE_ROW, False):
        for view in doc.Objects:
            if view.TypeId not in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem") or \
                    _page_of(view) is None:
                continue
            for mdoc in _model_docs(view):
                for pic in sketch_pictures(mdoc):
                    try:
                        got = _shown_in(view, pic)
                    except Exception as _fw_err:
                        _fw_log("drawsketchopts.py:shown", _fw_err)
                        got = None
                    if got is not None:
                        want[(view.Name, mdoc.Name, pic.Name)] = (view, pic, got)
    have = {}
    for im in _picture_views(doc):
        key = (getattr(im, PIC_TAG, ""), getattr(im, "SWSketchPictureDoc", ""), getattr(im, "SWSketchPicture", ""))
        if key in want and key not in have:
            have[key] = im
        else:
            try:
                doc.removeObject(im.Name)
            except Exception as _fw_err:
                _fw_log("drawsketchopts.py:remove", _fw_err)
    made = []
    for key, (view, pic, (u, w, angle, width, height)) in want.items():
        im = have.get(key)
        if im is None:
            page = _page_of(view)
            im = doc.addObject("TechDraw::DrawViewSymbol", "SketchPicture")
            page.addView(im)
            for prop, value in ((PIC_TAG, view.Name), ("SWSketchPictureDoc", key[1]), ("SWSketchPicture", key[2])):
                im.addProperty("App::PropertyString", prop, "FreeCAD", "the sketch picture shown in a view")
                setattr(im, prop, value)
            im.Label = "%s %s" % (view.Label, pic.Label)
        try:
            import os
            path = str(pic.ImageFile or "")
            stamp = "%s|%.6g|%.6g|%s" % (path, width, height, os.path.getmtime(path) if os.path.isfile(path) else "")
            if getattr(im, "SWSketchPictureStamp", None) != stamp:
                svg = _svg(path, width, height)
                if svg:
                    im.Symbol = svg
                if "SWSketchPictureStamp" not in im.PropertiesList:
                    im.addProperty("App::PropertyString", "SWSketchPictureStamp", "FreeCAD", "the picture shown")
                im.SWSketchPictureStamp = stamp
            im.ScaleType = "Custom"
            im.setExpression("Scale", "%s.Scale" % view.Name)
            # in a projection group the view's X, Y are the group's offset: the group's place is added
            group = next((o for o in view.InList if o.TypeId == "TechDraw::DrawProjGroup"), None)
            gx = "%s.X + " % group.Name if group is not None else ""
            gy = "%s.Y + " % group.Name if group is not None else ""
            turn = float(getattr(view, "Rotation", 0) or 0)
            c, sn = math.cos(math.radians(turn)), math.sin(math.radians(turn))
            ru, rw = u * c - w * sn, u * sn + w * c         # extapps88: the offset turns with the view
            im.setExpression("X", "%s%s.X + %s.Scale * (%.9g mm)" % (gx, view.Name, view.Name, ru))
            im.setExpression("Y", "%s%s.Y + %s.Scale * (%.9g mm)" % (gy, view.Name, view.Name, rw))
            im.Rotation = angle + turn
            if im.ViewObject.StackOrder != _stack(view) - 1:
                im.ViewObject.StackOrder = _stack(view) - 1       # under the view's lines
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:set", _fw_err)
        made.append(im)
    clear_faces(doc)
    try:
        doc.recompute()
    except Exception as _fw_err:
        _fw_log("drawsketchopts.py:recompute", _fw_err)
    return made


def refresh(doc=None):
    """After the Options box is saved: every open drawing's sketch hatches restacked and sketch pictures redone."""
    for d in ([doc] if doc is not None else list(App.listDocuments().values())):
        try:
            if any(o.isDerivedFrom("TechDraw::DrawPage") for o in d.Objects):
                restack(d)
                refresh_pictures(d)
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:refresh", _fw_err)


class _Follow(object):
    """Sketch pictures made again when a view turns or gets a model, or a model's sketch picture changes."""

    VIEW_PROPS = ("Direction", "XDirection", "Source", "XSource", "Rotation")
    PIC_PROPS = ("Placement", "XSize", "YSize", "ImageFile")

    def __init__(self):
        self.busy = False
        self.pending = set()

    def slotChangedObject(self, obj, prop):
        if self.busy:
            return
        try:
            if prop in self.VIEW_PROPS and obj.isDerivedFrom("TechDraw::DrawViewPart"):
                if option(PICTURE_ROW, False) or _picture_views(obj.Document):
                    self.later(obj.Document.Name)
            elif prop in self.PIC_PROPS and obj.TypeId == "Image::ImagePlane" and "SWSketch" in obj.PropertiesList:
                for d in App.listDocuments().values():
                    if _picture_views(d) or (option(PICTURE_ROW, False) and
                                             any(o.isDerivedFrom("TechDraw::DrawPage") for o in d.Objects)):
                        self.later(d.Name)
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:follow", _fw_err)

    def later(self, name):
        if name in self.pending:
            return
        self.pending.add(name)
        from PySide import QtCore
        QtCore.QTimer.singleShot(300, lambda n=name: self.redo(n))

    def redo(self, name):
        self.pending.discard(name)
        self.busy = True
        try:
            refresh_pictures(App.getDocument(name))
        except Exception as _fw_err:
            _fw_log("drawsketchopts.py:redo", _fw_err)
        finally:
            self.busy = False


_FOLLOW = []


def register():
    if not _FOLLOW:
        f = _Follow()
        App.addDocumentObserver(f)
        _FOLLOW.append(f)
