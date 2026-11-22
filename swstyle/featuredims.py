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
import FreeCADGui as Gui

NODE = "FWFeatureDims"
ROW = "Feature dimensions"
DATUMS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
BLUE = (0.0, 0.25, 0.85)


def on(doc):
    try:
        from . import treevirtual
        return treevirtual.value(doc, ROW)
    except Exception:
        return False


def _geo_point(sk, geo, pos):
    try:
        if pos in (1, 2, 3):
            return sk.getPoint(geo, pos)
        g = sk.Geometry[geo]
        if hasattr(g, "StartPoint") and hasattr(g, "EndPoint") and not hasattr(g, "Radius"):
            return (g.StartPoint + g.EndPoint) * 0.5
        if hasattr(g, "Center") and hasattr(g, "Radius"):
            a = getattr(g, "FirstParameter", 0.0)
            b = getattr(g, "LastParameter", 2 * math.pi)
            m = (a + b) / 2 if b - a < 2 * math.pi - 1e-6 else math.pi / 4
            return g.Center + App.Vector(math.cos(m), math.sin(m), 0) * g.Radius
    except Exception as _fw_err:
        _fw_log("featuredims.py:54", _fw_err)
    return None


def _short(text):
    ""
    t = text.strip()
    if t.endswith(" mm"):
        t = t[:-3]
        if "." in t:
            t = t.rstrip("0").rstrip(".")
    return t


def _off(sk, p, gap=4.0):
    """A little out from the sketch's middle, off the edge it measures (as a dimension line stands off)."""
    try:
        bb = sk.Shape.BoundBox
        c = sk.getGlobalPlacement().inverse().multVec(bb.Center)
        d = App.Vector(p.x - c.x, p.y - c.y, 0)
        if d.Length > 1e-6:
            d.normalize()
            return p + d * gap
    except Exception as _fw_err:
        _fw_log("featuredims.py:78", _fw_err)
    return p


def _styled_value(doc, value, kind, fallback, prefix=""):
    """Document Properties > Dimensions style (docstyle.dim_text), else FreeCAD's text shortened."""
    try:
        from . import docstyle
        return docstyle.dim_text(doc, value, kind, prefix)
    except Exception:
        return prefix + _short(fallback)


def _styled(doc, sk, i, c):
    prefix = "R" if c.Type == "Radius" else ("⌀" if c.Type == "Diameter" else "")
    value = math.degrees(c.Value) if c.Type == "Angle" else c.Value
    try:
        fallback = sk.getDatum(i).UserString
    except Exception:
        fallback = "%g" % c.Value
    return _styled_value(doc, value, c.Type, fallback, prefix)


def _named(obj, path, text):
    """System Options > General > Show dimension names: the name above the value (two lines)."""
    try:
        from .featuredimshow import names_on
        if names_on():
            from . import equations
            name = equations.sw_name(obj, path)
            if name:
                return name + "\n" + text
    except Exception as _fw_err:
        _fw_log("featuredims.py:111", _fw_err)
    return text


def labels(doc):
    """[(text, global point)] for the part's feature dimensions."""
    return [(t, p) for t, p, _r in labels_in_planes(doc)]


def flat_to_screen():
    ""

    try:
        from . import optionspages
        return bool(optionspages.stored("Fixed", "Display dimensions flat to screen", False))
    except Exception:
        return True


def labels_in_planes(doc):
    """[(text, global point, rotation of the plane the dimension lies in)]."""
    out = []
    if doc is None:
        return out
    used = set()
    for o in doc.Objects:
        if o.isDerivedFrom("PartDesign::Feature"):
            prof = getattr(o, "Profile", None)
            if prof:
                used.add(prof[0].Name if isinstance(prof, (tuple, list)) else prof.Name)
    for sk in doc.Objects:
        if not sk.isDerivedFrom("Sketcher::SketchObject") or sk.Name not in used:
            continue
        pl = sk.getGlobalPlacement()
        for i, c in enumerate(sk.Constraints):
            if c.Type not in DATUMS or not getattr(c, "Driving", True) or c.First < 0:
                continue
            if c.Type in ("Distance", "DistanceX", "DistanceY") and c.Second >= 0 and c.Second != c.First:
                a, b = _geo_point(sk, c.First, c.FirstPos), _geo_point(sk, c.Second, c.SecondPos)
                p = (a + b) * 0.5 if a is not None and b is not None else a or b
            elif c.Type in ("Distance", "DistanceX", "DistanceY") and c.FirstPos and c.Second >= 0:
                p = _geo_point(sk, c.First, c.FirstPos)
            else:
                p = _geo_point(sk, c.First, 0)
            if p is None:
                continue
            p = _off(sk, p)
            text = _named(sk, "Constraints[%d]" % i, _styled(doc, sk, i, c))
            out.append((text, pl.multVec(p), pl.Rotation))
    for o in doc.Objects:
        if o.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket") or not getattr(o, "Profile", None):
            continue
        sk = o.Profile[0]
        try:
            shape = sk.Shape
            centre = shape.BoundBox.Center
            n = sk.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            if o.TypeId == "PartDesign::Pocket" or getattr(o, "Reversed", False):
                n = n * -1
            depth = o.Length.Value
            # the depth lies in a plane through the extrusion direction (the sketch plane turned up)
            rot = sk.getGlobalPlacement().Rotation.multiply(App.Rotation(App.Vector(1, 0, 0), 90))
            out.append((_named(o, "Length", _styled_value(doc, o.Length.Value, "Distance", o.Length.UserString)),
                        centre + n * (depth / 2.0), rot))
        except Exception:
            continue
    return out


def _model_text_size(doc):
    """Dimension text in the model: about 1/30 of the part's size, 2 to 12 mm."""
    diag = 0.0
    for o in doc.Objects:
        try:
            if o.isDerivedFrom("PartDesign::Body") and not o.Shape.isNull():
                diag = max(diag, o.Shape.BoundBox.DiagonalLength)
        except Exception as _fw_err:
            _fw_log("featuredims.py:188", _fw_err)
    return max(2.0, min(12.0, diag / 30.0 if diag else 3.5))


def _root(gdoc):
    try:
        return gdoc.ActiveView.getSceneGraph()
    except Exception:
        return None


def _remove(gdoc):
    root = _root(gdoc)
    if root is None:
        return
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == NODE:
            root.removeChild(i)


def refresh(doc=None):
    """Draw (or take away) the feature dimensions of the document as its setting says."""
    from pivy import coin
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    shown = 0
    for d in docs:
        try:
            gdoc = Gui.getDocument(d.Name)
        except Exception:
            continue
        _remove(gdoc)
        if not on(d):
            continue
        root = _root(gdoc)
        if root is None:
            continue
        sep = coin.SoAnnotation()             # drawn after the part, over it
        sep.setName(NODE)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        sep.addChild(pick)
        try:
            depth = coin.SoDepthBuffer()
            depth.test = False
            sep.addChild(depth)
        except Exception as _fw_err:
            _fw_log("featuredims.py:234", _fw_err)
        col = coin.SoBaseColor()
        try:    # the Options colour scheme's Dimensions, Imported (Driving)
            from .featuredimshow import driving_color
            col.rgb = driving_color()
        except Exception:
            col.rgb = BLUE
        sep.addChild(col)
        font = coin.SoFont()
        font.size = 14
        sep.addChild(font)
        flat = flat_to_screen()
        if not flat:
            size = _model_text_size(d)
            font3 = coin.SoFont()
            font3.size = size
        for text, p, rot in labels_in_planes(d):
            s = coin.SoSeparator()
            t = coin.SoTranslation()
            t.translation = (p.x, p.y, p.z)
            s.addChild(t)
            if flat:
                txt = coin.SoText2()
                txt.string.setValues(0, len(text.split("\n")), text.split("\n"))
                txt.justification = coin.SoText2.CENTER
            else:
                r = coin.SoRotation()
                r.rotation.setValue(*rot.Q)
                s.addChild(r)
                s.addChild(font3)
                txt = coin.SoAsciiText()
                txt.string.setValues(0, len(text.split("\n")), text.split("\n"))
                txt.justification = coin.SoAsciiText.CENTER
            s.addChild(txt)
            sep.addChild(s)
            shown += 1
        root.addChild(sep)
    return shown


class _Watch:
    def slotRecomputedDocument(self, doc):
        if on(doc):
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda name=doc.Name: _later(name))

    def slotFinishRestoreDocument(self, doc):
        from PySide import QtCore
        QtCore.QTimer.singleShot(600, lambda name=doc.Name: _later(name))


def _later(name):
    try:
        if name in App.listDocuments():
            refresh(App.getDocument(name))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: feature dimensions: %s\n" % error)


_watch = []


def install():
    if not _watch:
        _watch.append(_Watch())
        App.addDocumentObserver(_watch[0])
        # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
        from . import restorehook
        restorehook.on_restored(_watch[0].slotFinishRestoreDocument)
