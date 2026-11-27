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
import os
import random

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

PROP = "SWAppearanceImage"
KEYED = "SWAppearanceImages"     # a face's or a feature's own image/mapping/finish: key (appearance.key_of) -> json
MAPPINGS = ("Automatic", "Projection", "Spherical", "Cylindrical", "Surface")
DIRECTIONS = ("XY", "YZ", "ZX")
FINISHES = ("None", "Bumps", "Knurl", "Sandblast", "Rough", "Brushed", "Cast")
DEFAULTS = {"image": "", "mapping": "Automatic", "direction": "XY", "width": "100", "height": "100",
            "angle": "0", "mirror_h": "0", "mirror_v": "0", "finish": "None", "finish_scale": "100", "bump": "",
            "hloc": "0", "vloc": "0"}     # Horizontal / Vertical location (mm): where the image sits on the faces

_nodes = {}         # (doc, tip name) -> (root, [nodes])
_overlays = {}      # (doc, tip name) -> [(parent, overlay switch, face index)]
_files = {}         # pattern cache: (finish, image, size) -> png path


def settings(body):
    out = dict(DEFAULTS)
    out.update(getattr(body, PROP, {}) or {})
    return out


def store(body, values):
    if PROP not in body.PropertiesList:
        body.addProperty("App::PropertyMap", PROP, "FreeCAD", "Appearance image, mapping and surface finish")
        body.setEditorMode(PROP, 2)
    kept = {k: str(v) for k, v in values.items() if str(v) != DEFAULTS.get(k, "")}
    setattr(body, PROP, kept)


def active(body):
    s = settings(body)
    return bool(s["image"]) or s["finish"] != "None"


def _on(s):
    return bool(s.get("image")) or s.get("finish", "None") != "None"


def keyed(body):
    ""

    import json
    out = {}
    for k, v in (getattr(body, KEYED, {}) or {}).items():
        try:
            d = dict(DEFAULTS)
            d.update(json.loads(v))
            out[k] = d
        except Exception as _fw_err:
            _fw_log("appeartex.py:keyed", _fw_err)
    return out


def settings_for(body, key):
    """The image settings of one target: a face's or feature's own, else the body's."""
    if key and key.startswith(("face:", "feature:")):
        return keyed(body).get(key) or dict(DEFAULTS)
    return settings(body)


def store_for(body, key, values):
    """Keeps a target's image settings: on the body for the body or part, in KEYED for a face or feature
    (an empty or default set takes the face's or feature's own away)."""
    import json
    if not (key and key.startswith(("face:", "feature:"))):
        store(body, values)
        return
    kept = {k: str(v) for k, v in (values or {}).items() if str(v) != DEFAULTS.get(k, "")}
    current = dict(getattr(body, KEYED, {}) or {})
    if kept and _on(dict(DEFAULTS, **kept)):
        current[key] = json.dumps(kept, sort_keys=True)
    elif key in current:
        del current[key]
    else:
        return
    if KEYED not in body.PropertiesList:
        body.addProperty("App::PropertyMap", KEYED, "FreeCAD", "Appearance images of faces and features")
        body.setEditorMode(KEYED, 2)
    setattr(body, KEYED, current)


# --------------------------------------------------------------------------- patterns
def _pattern_image(finish, size=256, seed=7):
    """A grey pattern for a surface finish: multiplied over the colour it darkens its grooves."""
    img = QtGui.QImage(size, size, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(255, 255, 255))
    p = QtGui.QPainter(img)
    rnd = random.Random(seed)
    if finish == "Knurl":
        p.setPen(QtGui.QPen(QtGui.QColor(120, 120, 120), 3))
        step = size // 8
        for i in range(-size, 2 * size, step):
            p.drawLine(i, 0, i + size, size)
            p.drawLine(i, size, i + size, 0)
    elif finish == "Sandblast":
        for _ in range(size * size // 3):
            x, y = rnd.randrange(size), rnd.randrange(size)
            g = rnd.randrange(150, 255)
            img.setPixel(x, y, QtGui.qRgb(g, g, g))
    elif finish == "Rough":
        p.setPen(QtCore.Qt.NoPen)
        for _ in range(size * 3):
            g = rnd.randrange(120, 240)
            p.setBrush(QtGui.QColor(g, g, g))
            r = rnd.randrange(4, 14)
            p.drawEllipse(QtCore.QPoint(rnd.randrange(size), rnd.randrange(size)), r, r)
    elif finish == "Brushed":
        for y in range(size):
            g = rnd.randrange(170, 255)
            p.setPen(QtGui.QColor(g, g, g))
            p.drawLine(0, y, size, y)
    elif finish == "Cast":
        p.setPen(QtCore.Qt.NoPen)
        for _ in range(size * 8):
            g = rnd.randrange(140, 230)
            p.setBrush(QtGui.QColor(g, g, g))
            r = rnd.randrange(2, 6)
            p.drawEllipse(QtCore.QPoint(rnd.randrange(size), rnd.randrange(size)), r, r)
    elif finish == "Bumps":
        p.setPen(QtCore.Qt.NoPen)
        step = size // 6
        for yy in range(0, size, step):
            for xx in range(0, size, step):
                grad = QtGui.QRadialGradient(xx + step / 2, yy + step / 2, step / 2)
                grad.setColorAt(0.0, QtGui.QColor(255, 255, 255))
                grad.setColorAt(1.0, QtGui.QColor(150, 150, 150))
                p.setBrush(QtGui.QBrush(grad))
                p.drawEllipse(xx, yy, step, step)
    p.end()
    return img


def _combined_png(image_path, finish, bump_path):
    """The file the texture reads: the image, the finish pattern, or the two multiplied."""
    key = (image_path, finish, bump_path)
    if key in _files and os.path.exists(_files[key]):
        return _files[key]
    base = None
    if image_path and os.path.exists(image_path):
        base = QtGui.QImage(image_path).convertToFormat(QtGui.QImage.Format_RGB32)
        if base.isNull():
            base = None
    pattern = None
    if finish == "Bumps" and bump_path and os.path.exists(bump_path):
        pattern = QtGui.QImage(bump_path).convertToFormat(QtGui.QImage.Format_RGB32)
    elif finish != "None":
        pattern = _pattern_image(finish)
    if base is None and pattern is None:
        return None
    if base is not None and pattern is not None:
        # the picture times the grey pattern, done by Qt (a pixel-by-pixel loop froze FreeCAD for seconds on a photo)
        pattern = pattern.scaled(base.width(), base.height())
        p = QtGui.QPainter(base)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_Multiply)
        p.drawImage(0, 0, pattern)
        p.end()
        out = base
    else:
        out = base if base is not None else pattern
    folder = os.path.join(App.getUserCachePath() if hasattr(App, "getUserCachePath") else App.getUserAppDataDir(), "FreeWorks", "textures")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "tex_%08x.png" % (abs(hash(key)) & 0xffffffff))
    out.save(path, "PNG")
    _files[key] = path
    return path


# --------------------------------------------------------------------------- the scene nodes
def _tip(body):
    if body.TypeId == "PartDesign::Body":
        return body.Tip
    return body


def _bound(obj):
    try:
        return obj.Shape.BoundBox
    except Exception:
        return None


def _coordinate_node(s, obj):
    from pivy import coin
    mapping = s["mapping"]
    if mapping in ("Spherical", "Cylindrical"):
        # wrapped round the faces in the model's own space, so the image turns with the part (an environment
        # map slid over the faces whenever the view turned)
        try:
            return coin.SoTextureCoordinateSphere() if mapping == "Spherical" else coin.SoTextureCoordinateCylinder()
        except AttributeError:
            return coin.SoTextureCoordinateEnvironment()
    # Automatic, Projection and Surface: a plane projection (Part shapes carry no texture coordinates)
    node = coin.SoTextureCoordinatePlane()
    try:
        w = max(float(s["width"]), 0.01)
        h = max(float(s["height"]), 0.01)
        a = math.radians(float(s["angle"]))
    except ValueError:
        w, h, a = 100.0, 100.0, 0.0
    axes = {"XY": ((1, 0, 0), (0, 1, 0)), "YZ": ((0, 1, 0), (0, 0, 1)), "ZX": ((0, 0, 1), (1, 0, 0))}[s["direction"]]
    u, v = axes
    ca, sa = math.cos(a), math.sin(a)
    su = tuple(ca * ui - sa * vi for ui, vi in zip(u, v))
    tv = tuple(sa * ui + ca * vi for ui, vi in zip(u, v))
    if s["mirror_h"] == "1":
        su = tuple(-x for x in su)
    if s["mirror_v"] == "1":
        tv = tuple(-x for x in tv)
    if mapping == "Automatic":

        box = _bound(obj)
        if box is not None and box.isValid():
            w = max(box.XLength, box.YLength, box.ZLength, 0.01)
            h = w
    node.directionS.setValue(coin.SbVec3f(*[x / w for x in su]))
    node.directionT.setValue(coin.SbVec3f(*[x / h for x in tv]))
    return node


def _plane_size(s, obj):
    """(width, height) in mm of one repeat of the image, as _coordinate_node lays it."""
    try:
        w, h = max(float(s["width"]), 0.01), max(float(s["height"]), 0.01)
    except ValueError:
        w, h = 100.0, 100.0
    if s["mapping"] == "Automatic":
        box = _bound(obj)
        if box is not None and box.isValid():
            w = h = max(box.XLength, box.YLength, box.ZLength, 0.01)
    return w, h


def _shift(node, s, obj):
    """Horizontal / Vertical location: the image slid along the faces (plane mappings), on the texture
    transform node."""
    from pivy import coin
    if s.get("mapping") in ("Spherical", "Cylindrical") or not s.get("image"):
        return
    try:
        dh, dv = float(s.get("hloc", "0")), float(s.get("vloc", "0"))
    except ValueError:
        return
    if not dh and not dv:
        return
    w, h = _plane_size(s, obj)
    node.translation.setValue(coin.SbVec2f(-dh / w, -dv / h))


def remove(body):
    """Takes the drawn image off the body: off its last feature, and off a feature that was last before (a feature
    added at the end of the body becomes the tip; the one before kept the texture)."""
    tip = _tip(body)
    if tip is None:
        return
    names = {tip.Name}
    if body.TypeId == "PartDesign::Body":
        names |= {o.Name for o in body.Group}
    for key in [k for k in _nodes if k[0] == tip.Document.Name and k[1] in names]:
        root, nodes = _nodes.pop(key)
        for n in nodes:
            try:
                root.removeChild(n)
            except Exception as _fw_err:
                _fw_log("appeartex.py:205", _fw_err)
    for key in [k for k in _overlays if k[0] == tip.Document.Name and k[1] in names]:
        for parent, node, _i in _overlays.pop(key):
            try:
                parent.removeChild(node)
            except Exception as _fw_err:
                _fw_log("appeartex.py:overlay", _fw_err)
    if not _overlays:
        _watch(False)


def _texture_from_file(tex, path):
    """The picture put in the texture as pixels read with Qt, as decalpm and scenebg do: Coin reads a file
    named in SoTexture2.filename only through simage, which FreeCAD's Windows build may lack, and the
    texture then draws nothing (a textured appearance showed in plain colour). Falls back to the file name."""
    from pivy import coin
    image = QtGui.QImage(path)
    if image.isNull():
        tex.filename.setValue(path)
        return False
    image = image.convertToFormat(QtGui.QImage.Format_RGBA8888).mirrored(False, True)     # Coin: bottom row first
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    tex.filename.setValue("")
    tex.image.setValue(coin.SbVec2s(w, h), 4, b"".join(raw[y * stride:y * stride + 4 * w] for y in range(h)))
    return True


def apply(body):
    """Draws the body's image, mapping and finish (or takes them away when there are none)."""
    if not App.GuiUp or body is None:
        return False
    tip = _tip(body)
    if tip is None or tip.ViewObject is None:
        return False
    remove(body)
    s = settings(body)
    if not active(body):
        _keyed_overlays(body, tip)
        return False
    try:
        from pivy import coin
        path = _combined_png(s["image"], s["finish"], s["bump"])
        if path is None:
            return False
        root = tip.ViewObject.RootNode
        tex = coin.SoTexture2()
        _texture_from_file(tex, path)
        tex.model = coin.SoTexture2.MODULATE
        tex.wrapS = coin.SoTexture2.REPEAT
        tex.wrapT = coin.SoTexture2.REPEAT
        coords = _coordinate_node(s, tip)
        scale = coin.SoTexture2Transform()
        try:
            k = max(float(s["finish_scale"]), 1.0) / 100.0
        except ValueError:
            k = 1.0
        if s["finish"] != "None" and not s["image"]:
            scale.scaleFactor.setValue(coin.SbVec2f(4.0 / k, 4.0 / k))
        _shift(scale, s, tip)
        nodes = [tex, coords, scale]
        for i, n in enumerate(nodes):
            root.insertChild(n, i)
        _nodes[(tip.Document.Name, tip.Name)] = (root, nodes)
        _own_faces(body, tip)
        _keyed_overlays(body, tip)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: appearance image not drawn: %s\n" % error)
        return False


# --------------------------------------------------------------------------- faces with their own look
def _shown_face_sets(root):
    """(parent, face set) for each shaded face set of the tip: the Flat Lines copy and the Shaded one."""
    from pivy import coin
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoBrepFaceSet"))
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(root)
    out = []
    for path in search.getPaths():
        nodes = [path.getNode(i) for i in range(path.getLength())]
        offset = None
        for depth in range(len(nodes) - 1):           # the polygon offset the face set draws with
            parent, at = nodes[depth], path.getIndex(depth + 1)
            for i in range(at):
                n = parent.getChild(i)
                if n.isOfType(coin.SoPolygonOffset.getClassTypeId()):
                    offset = (n.factor.getValue(), n.units.getValue(), n.on.getValue())
        out.append((nodes[-2], nodes[-1], offset))
    return out


def _overlay(face_set, index, material, offset):
    """The face drawn again, untextured, in its own appearance, one step in front of the textured one
    (still behind the edges drawn over it)."""
    from pivy import coin
    parts = list(face_set.partIndex.getValues())
    if index >= len(parts) or parts[index] <= 0:
        return None
    start = sum(parts[:index]) * 4
    ids = list(face_set.coordIndex.getValues())[start:start + parts[index] * 4]
    if len(ids) != parts[index] * 4:
        return None
    switch = coin.SoSwitch()
    sep = coin.SoSeparator()
    sep.addChild(coin.SoTexture2())               # no image: no texture on this face
    pull = coin.SoPolygonOffset()
    factor, units, on = offset if offset is not None else (0.0, 0.0, False)
    if not on:
        factor, units = 0.0, 0.0
    pull.factor = factor
    pull.units = units - 1.0
    sep.addChild(pull)
    binding = coin.SoMaterialBinding()
    binding.value = coin.SoMaterialBinding.OVERALL
    sep.addChild(binding)
    look = coin.SoMaterial()
    look.diffuseColor.setValue(*material.DiffuseColor[:3])
    look.ambientColor.setValue(*material.AmbientColor[:3])
    look.specularColor.setValue(*material.SpecularColor[:3])
    look.emissiveColor.setValue(*material.EmissiveColor[:3])
    look.shininess = material.Shininess
    look.transparency = material.Transparency
    sep.addChild(look)
    faces = coin.SoIndexedFaceSet()
    faces.coordIndex.setValues(0, len(ids), ids)
    sep.addChild(faces)
    switch.addChild(sep)
    switch.whichChild = 0
    return switch


def _textured_overlay(face_set, indices, material, offset, s, shape_box):
    """The faces (indices of the tip) drawn again with their own image, mapping and finish, a step in
    front of what the body draws there."""
    from pivy import coin
    parts = list(face_set.partIndex.getValues())
    all_ids = list(face_set.coordIndex.getValues())
    ids = []
    for index in indices:
        if index >= len(parts) or parts[index] <= 0:
            continue
        start = sum(parts[:index]) * 4
        chunk = all_ids[start:start + parts[index] * 4]
        if len(chunk) == parts[index] * 4:
            ids += chunk
    if not ids:
        return None
    path = _combined_png(s["image"], s["finish"], s["bump"])
    if path is None:
        return None
    switch = coin.SoSwitch()
    sep = coin.SoSeparator()
    tex = coin.SoTexture2()
    _texture_from_file(tex, path)
    tex.model = coin.SoTexture2.MODULATE
    tex.wrapS = coin.SoTexture2.REPEAT
    tex.wrapT = coin.SoTexture2.REPEAT
    sep.addChild(tex)
    sep.addChild(_coordinate_node(s, _BoxOnly(shape_box)))
    scale = coin.SoTexture2Transform()
    try:
        k = max(float(s["finish_scale"]), 1.0) / 100.0
    except ValueError:
        k = 1.0
    if s["finish"] != "None" and not s["image"]:
        scale.scaleFactor.setValue(coin.SbVec2f(4.0 / k, 4.0 / k))
    _shift(scale, s, _BoxOnly(shape_box))
    sep.addChild(scale)
    pull = coin.SoPolygonOffset()
    factor, units, on = offset if offset is not None else (0.0, 0.0, False)
    if not on:
        factor, units = 0.0, 0.0
    pull.factor = factor
    pull.units = units - 2.0          # in front of a colour-only cover (units - 1)
    sep.addChild(pull)
    binding = coin.SoMaterialBinding()
    binding.value = coin.SoMaterialBinding.OVERALL
    sep.addChild(binding)
    look = coin.SoMaterial()
    look.diffuseColor.setValue(*material.DiffuseColor[:3])
    look.ambientColor.setValue(*material.AmbientColor[:3])
    look.specularColor.setValue(*material.SpecularColor[:3])
    look.emissiveColor.setValue(*material.EmissiveColor[:3])
    look.shininess = material.Shininess
    look.transparency = material.Transparency
    sep.addChild(look)
    faces = coin.SoIndexedFaceSet()
    faces.coordIndex.setValues(0, len(ids), ids)
    sep.addChild(faces)
    switch.addChild(sep)
    switch.whichChild = 0
    return switch


class _BoxOnly:
    """Stands in for an object in _coordinate_node: Automatic fits the image to these faces' box."""

    def __init__(self, box):
        self.box = box

    @property
    def Shape(self):
        return self

    @property
    def BoundBox(self):
        return self.box


def _keyed_overlays(body, tip):
    """Draws the faces and features that have an image or finish of their own."""
    try:
        if body.TypeId != "PartDesign::Body":
            return
        own = keyed(body)
        if not own:
            return
        from . import appearance
        looks = tip.ViewObject.ShapeAppearance
        faces = tip.Shape.Faces
        made = list(_overlays.get((tip.Document.Name, tip.Name), []))
        for key, s in sorted(own.items(), key=lambda kv: kv[0].startswith("face:")):   # faces over features
            indices = appearance.tip_faces(body, key)
            if not indices:
                continue
            box = App.BoundBox()
            for i in indices:
                box.add(faces[i].BoundBox)
            for parent, face_set, offset in _shown_face_sets(tip.ViewObject.RootNode):
                material = looks[indices[0]] if indices[0] < len(looks) else looks[0]
                node = _textured_overlay(face_set, indices, material, offset, s, box)
                if node is None:
                    continue
                parent.insertChild(node, parent.findChild(face_set) + 1)
                for i in indices:
                    made.append((parent, node, i))
        if made:
            _overlays[(tip.Document.Name, tip.Name)] = made
            _watch(True)
            _highlighted()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: face or feature image: %s\n" % error)


def _own_faces(body, tip):
    """Covers the texture on the faces that have their own appearance."""
    try:
        from . import appearance
        own = set()
        appearance.face_colours(body, own)
        if not own:
            return
        looks = tip.ViewObject.ShapeAppearance
        made = []
        for parent, face_set, offset in _shown_face_sets(tip.ViewObject.RootNode):
            at = parent.findChild(face_set)
            for i in sorted(own):
                if i >= len(looks):
                    continue
                node = _overlay(face_set, i, looks[i], offset)
                if node is None:
                    continue
                at += 1
                parent.insertChild(node, at)
                made.append((parent, node, i))
        if made:
            _overlays[(tip.Document.Name, tip.Name)] = made
            _watch(True)
            _highlighted()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: own face appearance over the image: %s\n" % error)


def _picked_faces():
    """{(doc, object): {face index}} of the faces now highlighted or selected."""
    out = {}

    def add(obj, sub):
        if obj is None or not sub:
            return
        try:
            leaf = obj.getSubObject(sub, 1)
        except Exception:
            leaf = obj
        element = sub.split(".")[-1]
        if leaf is not None and element.startswith("Face") and element[4:].isdigit():
            out.setdefault((leaf.Document.Name, leaf.Name), set()).add(int(element[4:]) - 1)
    try:
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames:
                add(sel.Object, sub)
        pre = Gui.Selection.getPreselection()
        if pre is not None and pre.Object is not None:
            for sub in pre.SubElementNames:
                add(pre.Object, sub)
    except Exception as _fw_err:
        _fw_log("appeartex.py:picked", _fw_err)
    return out


def _highlighted():
    picked = _picked_faces()
    for key, made in _overlays.items():
        faces = picked.get(key, set())
        for _parent, node, i in made:
            want = -1 if i in faces else 0
            if node.whichChild.getValue() != want:
                node.whichChild = want


class _SelectionWatch:
    """Lets a highlighted or selected face show the highlight instead of its covering copy."""
    def __init__(self):
        self.queued = False

    def _later(self, *_args):
        if not self.queued:
            self.queued = True
            QtCore.QTimer.singleShot(0, self._run)

    def _run(self):
        self.queued = False
        _highlighted()

    addSelection = removeSelection = setSelection = clearSelection = _later
    setPreselection = removePreselection = _later


_watcher = []


def _watch(on):
    try:
        if on and not _watcher:
            _watcher.append(_SelectionWatch())
            Gui.Selection.addObserver(_watcher[0], 0)
        elif not on and _watcher:
            Gui.Selection.removeObserver(_watcher.pop())
    except Exception as _fw_err:
        _fw_log("appeartex.py:watch", _fw_err)


def refresh_document(doc):
    for obj in doc.Objects:
        if PROP in obj.PropertiesList or KEYED in obj.PropertiesList:
            apply(obj)
