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

from .widgets import alive

Qt = QtCore.Qt
MIME = "application/x-freeworks-appearance"
ROLE = Qt.UserRole + 1

# (folder, [(name, (r, g, b), transparency)])
PALETTE = (
    ("Plastic", (("Glossy Black Plastic", (0.05, 0.05, 0.05), 0.0), ("Glossy White Plastic", (0.95, 0.95, 0.95), 0.0),
                 ("Red Plastic", (0.80, 0.08, 0.08), 0.0), ("Blue Plastic", (0.10, 0.25, 0.75), 0.0),
                 ("Yellow Plastic", (0.95, 0.80, 0.10), 0.0), ("Green Plastic", (0.10, 0.55, 0.20), 0.0),
                 ("Clear Plastic", (0.85, 0.90, 0.95), 0.7))),
    ("Metal", (("Polished Steel", (0.78, 0.79, 0.80), 0.0), ("Brushed Aluminium", (0.72, 0.74, 0.76), 0.0),
               ("Cast Iron", (0.33, 0.33, 0.34), 0.0), ("Brass", (0.80, 0.66, 0.30), 0.0),
               ("Copper", (0.72, 0.45, 0.20), 0.0), ("Chrome", (0.88, 0.89, 0.91), 0.0),
               ("Gold", (0.85, 0.68, 0.22), 0.0))),
    ("Painted", (("Gloss Red Paint", (0.70, 0.05, 0.05), 0.0), ("Gloss Blue Paint", (0.05, 0.20, 0.60), 0.0),
                 ("Gloss Black Paint", (0.08, 0.08, 0.08), 0.0), ("Matte White Paint", (0.90, 0.90, 0.88), 0.0),
                 ("Safety Orange Paint", (0.95, 0.40, 0.05), 0.0), ("Grey Primer", (0.55, 0.56, 0.57), 0.0))),
    ("Rubber", (("Black Rubber", (0.10, 0.10, 0.10), 0.0), ("Grey Rubber", (0.40, 0.40, 0.40), 0.0),
                ("Red Rubber", (0.55, 0.12, 0.10), 0.0))),
    ("Glass", (("Clear Glass", (0.90, 0.95, 0.97), 0.8), ("Blue Glass", (0.45, 0.60, 0.80), 0.6),
               ("Green Glass", (0.45, 0.70, 0.55), 0.6), ("Frosted Glass", (0.92, 0.93, 0.94), 0.4))),


    ("Light", (("White Light", (1.00, 1.00, 0.96), 0.0), ("Warm Light", (1.00, 0.86, 0.60), 0.0),
               ("Red Light", (0.95, 0.12, 0.10), 0.0), ("Green Light", (0.15, 0.85, 0.25), 0.0),
               ("Blue Light", (0.20, 0.45, 1.00), 0.0), ("Amber Light", (1.00, 0.62, 0.05), 0.0))),
    ("Fabric", (("White Cotton", (0.93, 0.92, 0.89), 0.0), ("Canvas", (0.76, 0.70, 0.56), 0.0),
                ("Denim", (0.20, 0.30, 0.50), 0.0), ("Grey Felt", (0.50, 0.50, 0.50), 0.0),
                ("Brown Leather", (0.42, 0.26, 0.15), 0.0), ("Black Nylon", (0.12, 0.12, 0.13), 0.0))),
    ("Organic", (("Oak", (0.72, 0.56, 0.36), 0.0), ("Maple", (0.86, 0.73, 0.53), 0.0),
                 ("Walnut", (0.40, 0.27, 0.18), 0.0), ("Cherry", (0.62, 0.33, 0.20), 0.0),
                 ("Pine", (0.88, 0.76, 0.52), 0.0), ("Cork", (0.71, 0.56, 0.40), 0.0),
                 ("Bamboo", (0.85, 0.75, 0.48), 0.0))),
    ("Stone", (("Granite", (0.45, 0.44, 0.43), 0.0), ("Marble", (0.90, 0.89, 0.86), 0.0),
               ("Concrete", (0.62, 0.61, 0.58), 0.0))),
    ("Miscellaneous", (("Carbon Fiber", (0.13, 0.13, 0.14), 0.0), ("Matte Black", (0.06, 0.06, 0.06), 0.0),
                       ("Satin White", (0.94, 0.94, 0.93), 0.0), ("Sand", (0.83, 0.76, 0.60), 0.0),
                       ("Clay", (0.70, 0.45, 0.32), 0.0), ("Wax", (0.92, 0.88, 0.75), 0.25))),
)


_METALS = (("Steel", (0.70, 0.71, 0.72)), ("Chrome", (0.86, 0.87, 0.89)), ("Aluminum", (0.76, 0.77, 0.78)),
           ("Bronze", (0.62, 0.45, 0.25)), ("Brass", (0.80, 0.66, 0.30)), ("Copper", (0.72, 0.45, 0.20)),
           ("Nickel", (0.66, 0.62, 0.55)), ("Zinc", (0.68, 0.70, 0.72)), ("Magnesium", (0.74, 0.74, 0.73)),
           ("Iron", (0.42, 0.42, 0.43)), ("Titanium", (0.56, 0.56, 0.58)), ("Gold", (0.85, 0.68, 0.22)),
           ("Silver", (0.82, 0.82, 0.83)))
_FINISHES = (("polished", 1.12), ("brushed", 0.96), ("satin finish", 1.02), ("matte", 0.86))


def _shade(rgb, k):
    return tuple(min(1.0, round(c * k, 4)) for c in rgb)



_EXTRAS = {
    "Aluminum": (("sandblasted aluminum", (0.70, 0.71, 0.72)), ("burnished aluminum", (0.80, 0.80, 0.79)),
                 ("cast aluminum", (0.63, 0.64, 0.65)),
                 ("blue anodized aluminum", (0.16, 0.36, 0.72)), ("red anodized aluminum", (0.70, 0.12, 0.14)),
                 ("black anodized aluminum", (0.12, 0.12, 0.13)), ("gold anodized aluminum", (0.80, 0.64, 0.25)),
                 ("green anodized aluminum", (0.18, 0.52, 0.28)), ("purple anodized aluminum", (0.45, 0.20, 0.60)),
                 ("orange anodized aluminum", (0.88, 0.42, 0.10)), ("silver anodized aluminum", (0.78, 0.79, 0.81))),
    "Iron": (("cast iron", (0.33, 0.33, 0.34)), ("wrought iron", (0.30, 0.29, 0.28)),
             ("sandblasted iron", (0.40, 0.40, 0.41))),
    "Steel": (("sandblasted steel", (0.62, 0.63, 0.64)), ("cast steel", (0.50, 0.51, 0.52))),
}

METAL_SUBFOLDERS = tuple((name, tuple(("%s %s" % (finish, name.lower()), _shade(rgb, k), 0.0)
                                      for finish, k in _FINISHES)
                          + tuple((label, colour, 0.0) for label, colour in _EXTRAS.get(name, ())))
                         for name, rgb in _METALS)




# viewdisplay/appearance-library-1126.md)
_COLOURS = (("black", (0.05, 0.05, 0.05)), ("white", (0.94, 0.94, 0.93)), ("red", (0.78, 0.07, 0.07)),
            ("blue", (0.08, 0.24, 0.72)), ("green", (0.10, 0.52, 0.20)), ("yellow", (0.95, 0.78, 0.10)),
            ("grey", (0.50, 0.51, 0.52)))


def _named(pattern, colours, k=1.0, tr=0.0):
    return tuple((pattern % name, _shade(rgb, k), tr) for name, rgb in colours)


SUBFOLDERS = {
    "Plastic": (("High Gloss", _named("%s high gloss plastic", _COLOURS)),
                ("Medium Gloss", _named("%s medium gloss plastic", _COLOURS)),
                ("Low Gloss", _named("%s low gloss plastic", _COLOURS)),
                ("Textured", _named("%s textured plastic", _COLOURS[:2] + _COLOURS[-1:], 0.95)),
                ("Transparent", (("clear plastic", (0.85, 0.90, 0.95), 0.7),
                                 ("blue transparent plastic", (0.35, 0.55, 0.85), 0.6),
                                 ("red transparent plastic", (0.85, 0.25, 0.25), 0.6),
                                 ("smoke transparent plastic", (0.30, 0.30, 0.32), 0.5)))),
    "Painted": (("Car", _named("%s car paint", (("red", (0.70, 0.05, 0.06)), ("blue", (0.06, 0.18, 0.55)),
                                                ("black", (0.04, 0.04, 0.05)), ("silver", (0.72, 0.73, 0.75)),
                                                ("white", (0.93, 0.93, 0.92))))),
                ("Powder Coat", _named("%s powder coat", _COLOURS[:4] + _COLOURS[-1:])),
                ("Sprayed", _named("%s sprayed paint", _COLOURS[:3] + _COLOURS[-1:]))),
    "Rubber": (("Matte", _named("%s matte rubber", (("black", (0.09, 0.09, 0.09)), ("grey", (0.40, 0.40, 0.40))))),
               ("Textured", _named("%s textured rubber", (("black", (0.10, 0.10, 0.10)), ("grey", (0.42, 0.42, 0.42)))))),
    "Glass": (("Gloss", (("clear glass", (0.90, 0.95, 0.97), 0.8), ("blue glass", (0.45, 0.60, 0.80), 0.6),
                         ("green glass", (0.45, 0.70, 0.55), 0.6), ("smoke glass", (0.30, 0.31, 0.33), 0.5))),
              ("Textured", (("frosted glass", (0.92, 0.93, 0.94), 0.4), ("textured glass", (0.88, 0.92, 0.94), 0.5)))),
    "Organic": (("Wood", (("oak", (0.72, 0.56, 0.36), 0.0), ("maple", (0.86, 0.73, 0.53), 0.0),
                          ("walnut", (0.40, 0.27, 0.18), 0.0), ("cherry", (0.62, 0.33, 0.20), 0.0),
                          ("pine", (0.88, 0.76, 0.52), 0.0), ("beech", (0.80, 0.62, 0.42), 0.0),
                          ("mahogany", (0.45, 0.20, 0.13), 0.0))),),
}



# (diffuse, specular, spread, reflection, blurry, luminous). RealView shows the difference
# (a metal reflects the studio in its own colour, glass turns mirror-like at a grazing angle).
_LIGHTS = (
    (("high gloss", "car paint"), (0.8, 0.7, 0.1, 0.3, 0.0, 0.0)),
    (("medium gloss", "powder coat"), (0.8, 0.4, 0.3, 0.12, 0.1, 0.0)),
    (("low gloss", "sprayed", "textured", "matte rubber"), (0.8, 0.1, 0.7, 0.03, 0.5, 0.0)),
    (("smoke glass", "textured glass"), (0.3, 0.8, 0.1, 0.4, 0.3, 0.0)),
    (("transparent plastic",), (0.8, 0.6, 0.15, 0.3, 0.0, 0.0)),
    (("beech", "mahogany"), (0.8, 0.05, 0.9, 0.0, 0.8, 0.0)),
    (("white light", "warm light", "red light", "green light", "blue light", "amber light"),
     (0.8, 0.1, 0.5, 0.0, 0.0, 1.0)),
    (("leather", "nylon", "wax"), (0.8, 0.3, 0.4, 0.1, 0.3, 0.0)),
    (("cotton", "canvas", "denim", "felt", "oak", "maple", "walnut", "cherry", "pine", "cork", "bamboo",
      "sand", "clay", "carbon"), (0.8, 0.05, 0.9, 0.0, 0.8, 0.0)),
    (("frosted",), (0.3, 0.6, 0.3, 0.3, 0.7, 0.0)),
    (("glass",), (0.3, 1.0, 0.02, 0.5, 0.0, 0.0)),
    (("clear plastic",), (0.8, 0.6, 0.15, 0.3, 0.0, 0.0)),
    (("plastic",), (0.8, 0.45, 0.25, 0.15, 0.0, 0.0)),
    (("matte white paint", "primer"), (0.8, 0.08, 0.7, 0.05, 0.5, 0.0)),
    (("paint",), (0.8, 0.5, 0.2, 0.2, 0.0, 0.0)),
    (("rubber", "concrete"), (0.8, 0.03, 0.9, 0.0, 0.8, 0.0)),
    (("granite",), (0.8, 0.3, 0.4, 0.15, 0.3, 0.0)),
    (("marble",), (0.8, 0.35, 0.3, 0.2, 0.2, 0.0)),
    (("anodized", "satin"), (0.6, 0.75, 0.3, 0.6, 0.3, 0.0)),
    (("brushed",), (0.6, 0.6, 0.5, 0.5, 0.6, 0.0)),
    (("matte", "sandblasted", "cast", "wrought"), (0.6, 0.4, 0.6, 0.45, 0.6, 0.0)),
    (("polished", "burnished", "chrome", "gold", "brass", "copper"), (0.6, 1.0, 0.05, 0.7, 0.0, 0.0)),
)


def light_of(label):
    """The illumination values of a library swatch, from its name (None = the plain defaults)."""
    low = label.lower()
    for words, light in _LIGHTS:
        if any(w in low for w in words):
            return light
    return None


def payload_of(label, rgb, tr):
    """The drag / double-click payload of a swatch: r, g, b, transparency and its illumination."""
    light = light_of(label)
    return "appearance:" + ",".join("%.4f" % v for v in tuple(rgb) + (tr,) + tuple(light or ()))




SCENE_FOLDERS = (
    ("Basic Scenes", ("3 Point Beige", "3 Point Blue", "3 Point Faded", "3 Point Green", "3 Point Orange",
                      "Backdrop - Ambient White", "Backdrop - Black with Fill Lights",
                      "Backdrop - Grey with Overhead Light", "Backdrop - Lightbox Studio", "Backdrop - Studio Room",
                      "Backdrop - Studio with Fill Lights", "Soft Box", "Soft Spotlight")),
    ("Studio Scenes", ("Plain White", "Reflective Floor Black", "Studio Dark", "Black")),
    ("Presentation Scenes", ("Rooftop", "Courtyard Background", "Urban 5 Background", "Urban 5 Image 6",
                             "Landscape 2 Image 4", "Retail Store", "Villa Interior", "Warehouse",
                             "Factory Background", "Modern Garage", "Fall Street")),
)


def scenes_of(group, order):
    """The scene numbers a Scenes folder shows (every one for Scenes itself), in order."""
    if not group:
        return list(order)
    from . import style
    names = dict(SCENE_FOLDERS).get(group, ())
    by_name = {style.SCENES[i][0]: i for i in order}
    return [by_name[n] for n in names if n in by_name]


def entries_of(folder):
    """The swatches of one folder ("Metal", "Metal/Steel"), or of every folder (None)."""
    out = []
    for name, entries in PALETTE:
        if folder is None or folder == name or folder.startswith(name + "/"):
            if folder is None or folder == name:
                out.extend(entries)
            for sub, more in subfolders(name):
                if folder in (None, name, name + "/" + sub):
                    out.extend(more)
    return out


def subfolders(name):
    """A top folder's subfolders: ((name, swatches), ...)."""
    return METAL_SUBFOLDERS if name == "Metal" else SUBFOLDERS.get(name, ())


def folder_of(label):
    """Where a swatch lives in the library ("Plastic/High Gloss"), or None."""
    for name, entries in PALETTE:
        if any(e[0] == label for e in entries):
            return name
        for sub, more in subfolders(name):
            if any(e[0] == label for e in more):
                return name + "/" + sub
    return None


def tooltip(label):
    """A swatch's tooltip: its name, then where it lives in the library."""
    folder = folder_of(label)
    return "%s\nAppearances(color) > %s" % (label, " > ".join(folder.split("/"))) if folder else label


def scene_icon(index, size=40):
    ""


    from . import hidpi as _hidpi
    from . import style
    _label, colours, graded = style.SCENES[index]
    top_c, mid_c, low_c = (QtGui.QColor((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255) for v in colours)
    pix = _hidpi.canvas(size, size)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    frame = QtCore.QRectF(1.5, 1.5, size - 3, size - 3)
    horizon = size * 0.62
    if index in getattr(style, "RADIAL_SCENES", ()):
        back = QtGui.QRadialGradient(size * 0.5, size * 0.45, size * 0.7)
        back.setColorAt(0, top_c)
        back.setColorAt(1, low_c)
    elif graded:
        back = QtGui.QLinearGradient(0, 0, 0, size)
        back.setColorAt(0, top_c)
        back.setColorAt(horizon / size, mid_c)
        back.setColorAt(1, low_c)
    else:
        back = top_c
    p.setPen(QtGui.QPen(QtGui.QColor(150, 150, 150), 1))
    p.setBrush(QtGui.QBrush(back))
    p.drawRoundedRect(frame, size * 0.06, size * 0.06)
    ball = size * 0.34
    cx, floor = size * 0.5, horizon + size * 0.12
    shade = QtGui.QRadialGradient(cx, floor, ball * 0.75)
    dark = 90 if top_c.lightness() > 90 else 160
    shade.setColorAt(0, QtGui.QColor(0, 0, 0, dark))
    shade.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QBrush(shade))
    p.drawEllipse(QtCore.QRectF(cx - ball * 0.75, floor - ball * 0.18, ball * 1.5, ball * 0.36))
    lit = QtGui.QRadialGradient(cx - ball * 0.18, floor - ball * 0.7, ball * 0.65)
    lit.setColorAt(0, QtGui.QColor(235, 237, 242))
    lit.setColorAt(1, QtGui.QColor(110, 114, 124))
    p.setBrush(QtGui.QBrush(lit))
    p.drawEllipse(QtCore.QRectF(cx - ball / 2, floor - ball, ball, ball))
    p.end()
    return QtGui.QIcon(pix)


def swatch_icon(rgb, size=40, transparency=0.0):
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(size, size)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grad = QtGui.QRadialGradient(size * 0.35, size * 0.35, size * 0.7)
    c = QtGui.QColor.fromRgbF(*rgb)
    grad.setColorAt(0, c.lighter(160))
    grad.setColorAt(1, c.darker(130))
    p.setBrush(QtGui.QBrush(grad))
    p.setPen(Qt.NoPen)
    p.setOpacity(1.0 - 0.6 * transparency)
    p.drawEllipse(2, 2, size - 4, size - 4)
    # a lit ball even when the colour is near black: the light's highlight and the room seen in the rim
    p.setOpacity(1.0)
    rim = QtGui.QRadialGradient(size * 0.5, size * 0.5, size * 0.5)
    deep = c.lightnessF() < 0.25
    # look-audit TP-4 (BB22): a near-black ball shows its round edge on the dark list too (a brighter rim and
    # a thin grey outline); lighter colours keep the soft rim
    rim.setColorAt(0.70 if deep else 0.78, QtGui.QColor(255, 255, 255, 0))
    rim.setColorAt(0.98, QtGui.QColor(255, 255, 255, 120 if deep else 60))
    p.setBrush(QtGui.QBrush(rim))
    if deep:
        p.setPen(QtGui.QPen(QtGui.QColor(128, 128, 128, 170), max(1.0, size / 80.0)))
    p.drawEllipse(2, 2, size - 4, size - 4)
    p.setPen(Qt.NoPen)
    shine = QtGui.QRadialGradient(size * 0.33, size * 0.3, size * 0.22)
    shine.setColorAt(0, QtGui.QColor(255, 255, 255, 200))
    shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(QtGui.QBrush(shine))
    p.drawEllipse(QtCore.QRectF(size * 0.1, size * 0.08, size * 0.46, size * 0.46))
    p.end()
    return QtGui.QIcon(pix)


# --------------------------------------------------------------------------- applying
def _info_at(view, pos):
    try:
        gl = gl_widget(view)
        dpr = gl.devicePixelRatioF() if gl is not None else 1.0
        h = gl.height() if gl is not None else view.height()
        return Gui.ActiveDocument.ActiveView.getObjectInfo((int(pos.x() * dpr), int((h - pos.y()) * dpr)))
    except Exception:
        return None


def component_at(view, pos):
    """The assembly component under a point of the 3D view, else None."""
    info = _info_at(view, pos)
    parent, sub = (info or {}).get("ParentObject"), (info or {}).get("SubName")
    if parent is None or not sub:
        return None
    return _component(parent.Document, parent, sub)


def _component(doc, root, sub=""):
    """The top assembly's component named by a pick (root + sub), or root itself when it is one."""
    try:
        from . import asmcore
        asm = asmcore.assembly_of(doc)
        if asm is None:
            return None
        comps = list(asmcore.components(asm))
        if root in comps:
            return root
        ref = asmcore.reference(asm, root, sub) if sub else None
        return ref[0] if ref and ref[0] in comps else None
    except Exception as _fw_err:
        _fw_log("appearpane.py:component", _fw_err)
        return None


def picks_at(view, pos):
    """(document object, sub-element) under a point of the 3D view widget (Qt pixels)."""
    info = _info_at(view, pos)
    if not info:
        return None
    doc = App.getDocument(info["Document"])
    obj = doc.getObject(info["Object"])
    sub = info.get("Component", "")
    try:
        from . import refplane
        obj, sub = refplane.resolve(obj, sub)
    except Exception as _fw_err:
        _fw_log("appearpane.py:138", _fw_err)
    return obj, sub


def gl_widget(view):
    if view is None:
        return None
    if view.inherits("QOpenGLWidget"):
        return view
    for c in view.findChildren(QtWidgets.QWidget):
        if c.inherits("QOpenGLWidget") and c.width() > 200:
            return c
    return None


def apply_to(level, obj, sub, rgbt):
    from . import appearance
    t = appearance.target_for(level, obj, sub)
    if t is None:
        return False
    doc = obj.Document
    doc.openTransaction("Appearance")
    try:
        appearance.apply([t], rgbt)
    finally:
        doc.commitTransaction()
    try:
        from . import displaymanager
        displaymanager.refresh_all()
    except Exception as _fw_err:
        _fw_log("appearpane.py:168", _fw_err)
    return True


def drop_menu(obj, sub, rgbt, parent=None, comp=None):
    ""

    from . import appearance
    levels = ["face", "feature", "body", "part"] if sub.startswith("Face") else ["feature", "body", "part"]
    menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
    menu.setObjectName("SWAppearanceDrop")
    for level in levels:
        t = appearance.target_for(level, obj, sub) if obj is not None else None
        if t is None:
            continue
        label = appearance.menu_label(t)        # as the Appearances drop-down names them (Face<1>@Cut-Extrude1 ...)
        act = menu.addAction(appearance._swatch(appearance.current_colour(t)), label)
        act.setObjectName("SWAppearanceDrop_" + level)
        act.setToolTip("Apply the appearance to %s" % label)
        act.triggered.connect(lambda _c=False, lv=level: apply_to(lv, obj, sub, rgbt))
    if comp is not None:
        try:
            from . import asmappearance
            label = "Component (%s)" % comp.Label
            act = menu.addAction(appearance._swatch(asmappearance.colour_of(comp)[:4]), label)
            act.setObjectName("SWAppearanceDrop_component")
            act.setToolTip("Apply the appearance to this component only, in this assembly")
            act.triggered.connect(lambda _c=False: apply_to_component(comp, rgbt))
        except Exception as _fw_err:
            _fw_log("appearpane.py:drop-component", _fw_err)
    return menu


def apply_to_component(comp, rgbt):
    """The component level of a drop: an override on this instance (asmappearance), with Undo."""
    from . import asmappearance
    doc = comp.Document
    doc.openTransaction("Appearance")
    try:
        asmappearance.set_colour(comp, tuple(rgbt))
    finally:
        doc.commitTransaction()
    return True


def drop(view, pos, payload):
    """What a drop of a swatch on the 3D view does. payload: ('appearance', rgbt) or ('scene', index)."""
    kind, value = payload
    if kind == "scene":
        from . import style
        style.apply_scene(int(value))
        return True
    hit = picks_at(view, pos)
    if hit is None:
        return None
    obj, sub = hit
    comp = component_at(view, pos) if kind == "appearance" else None
    if kind == "decal":
        # a decal dropped on a face (flat or curved): the Decals PropertyManager opens on it there
        from . import decalpm
        try:
            # on an assembly component: the component's own face, where that copy stands (as Edit Decal
            # does, vd112); the part's face put the decal on the part's file position, on the first copy
            info = _info_at(view, pos) or {}
            if info.get("ParentObject") is not None and info.get("SubName"):
                found = decalpm._component_face(info["ParentObject"], info["SubName"])
                if found is not None:
                    obj, sub = found
        except Exception as _fw_err:
            _fw_log("appearpane.py:decal-component", _fw_err)
        try:
            flat = sub.startswith("Face") and obj.Shape.getElement(sub).ShapeType == "Face"
        except Exception:
            flat = False
        return decalpm.apply_from_library(value, (obj, sub)) if flat else None
    from . import appearance
    # a surface body (or a solid outside any Body) takes a drop too: its faces, feature and body
    own = appearance.body_of(obj) is not None or appearance.own_body(obj)
    if not own and comp is None:
        return None
    if QtWidgets.QApplication.keyboardModifiers() & Qt.AltModifier and own:
        return edit_at_once(obj, sub, tuple(value))
    menu = drop_menu(obj if own else None, sub, tuple(value), comp=comp)
    if not menu.actions():
        return None
    menu.popup(view.mapToGlobal(pos))
    return menu


def edit_at_once(obj, sub, rgbt):
    """Alt+drag: the appearance goes on the item itself (the face, else its feature or body) and the
    Appearances PropertyManager opens on it."""
    from . import appearance
    level = appearance.natural(obj, sub) or "body"
    if not apply_to(level, obj, sub, rgbt):
        return None
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj, sub) if sub else Gui.Selection.addSelection(obj)
    except Exception as _fw_err:
        _fw_log("appearpane.py:alt-select", _fw_err)
    return appearance.open_page(obj.Document, level, [(obj, sub)])


def tree_drop(obj, rgbt, global_pos):
    """An appearance dropped on a FeatureManager tree row: the same pop-up, for that item."""
    from . import appearance
    comp = _component(obj.Document, obj) if obj is not None else None
    if comp is not None:
        # a component's tree row: its part's levels (the part file), then Component (<name>)
        src = getattr(comp, "LinkedObject", None)
        part_obj = appearance.body_of(src) or (appearance.bodies(src.Document) or [None])[0] if src is not None else None
        menu = drop_menu(part_obj, "", rgbt, comp=comp)
        menu.popup(global_pos)
        return menu
    if obj is None or appearance.body_of(obj) is None:
        return None
    if QtWidgets.QApplication.keyboardModifiers() & Qt.AltModifier:
        return edit_at_once(obj, "", rgbt)
    menu = drop_menu(obj, "", rgbt)
    if not menu.actions():
        return None
    menu.popup(global_pos)
    return menu


def apply_selected(rgbt):
    """A double-click on a swatch: the selection (its faces, else its features), else the part."""
    from . import appearance
    doc = App.ActiveDocument
    if doc is None:
        return False
    done = False
    for entry in Gui.Selection.getSelectionEx(doc.Name):
        for sub in (entry.SubElementNames or ("",)):
            obj, s = entry.Object, sub
            try:
                from . import refplane
                obj, s = refplane.resolve(obj, sub)
            except Exception as _fw_err:
                _fw_log("appearpane.py:233", _fw_err)
            level = "face" if s.startswith("Face") else ("body" if obj.TypeId == "PartDesign::Body" else "feature")
            done = apply_to(level, obj, s, rgbt) or done
    if not done:
        bs = appearance.bodies(doc)
        if bs:
            done = apply_to("part", bs[0], "", rgbt)
    return done


def _payload(data):
    try:
        kind, text = bytes(data).decode().split(":", 1)
        if kind == "decal":
            return (kind, text)
        return (kind, int(text)) if kind == "scene" else (kind, tuple(float(x) for x in text.split(",")))
    except Exception:
        return None


class _Dropper(QtCore.QObject):
    """Takes swatch drops on the 3D views."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove):
            if event.mimeData().hasFormat(MIME):
                event.acceptProposedAction()
                return True
        elif t == QtCore.QEvent.Drop and event.mimeData().hasFormat(MIME):
            payload = _payload(event.mimeData().data(MIME))
            if obj.property("swAppearanceTreeDrops"):
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if payload is not None and payload[0] == "appearance":
                    hit = _tree_object(obj, pos)
                    at = obj.mapToGlobal(pos)
                    QtCore.QTimer.singleShot(0, lambda h=hit, v=payload[1], a=at: tree_drop(h, tuple(v), a))
                event.acceptProposedAction()
                return True
            if payload is not None:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                QtCore.QTimer.singleShot(0, lambda o=obj, p=pos, pl=payload: alive(o) and drop(o, p, pl))
            event.acceptProposedAction()
            return True
        return False


_dropper = None


def _tree_object(viewport, pos):
    """The document object of the FeatureManager row under a point of the tree's viewport."""
    try:
        view = viewport.parentWidget()
        index = view.indexAt(pos)
        node = view.model().node(index) if index.isValid() else None
        return getattr(node, "obj", None)
    except Exception as _fw_err:
        _fw_log("appearpane.py:tree-object", _fw_err)
        return None


def watch_views():
    global _dropper
    if _dropper is None:
        _dropper = _Dropper(Gui.getMainWindow())
    for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
        if w.inherits("QOpenGLWidget") and w.width() > 200 and not w.property("swAppearanceDrops"):
            w.setAcceptDrops(True)
            w.installEventFilter(_dropper)
            w.setProperty("swAppearanceDrops", True)

    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeView, "SWFeatureTree"):
        port = tree.viewport()
        if not port.property("swAppearanceTreeDrops"):
            port.setAcceptDrops(True)
            port.installEventFilter(_dropper)
            port.setProperty("swAppearanceTreeDrops", True)


# --------------------------------------------------------------------------- the page
SWATCH = 104


def _folder_icon(kind="appearance", size=16):
    """A folder with what it holds in front of it (our own drawing): a coloured ball for
    appearances, a little floor and sky for scenes, a picture for decals; kind "root" is the ball alone."""
    from . import hidpi as _hidpi
    pix = _hidpi.canvas(size, size)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    k = size / 16.0
    if kind != "root":
        p.setPen(QtGui.QPen(QtGui.QColor("#7d7a6f"), max(1.0, 0.8 * k)))
        p.setBrush(QtGui.QColor("#d9d4c0"))
        back = QtGui.QPainterPath()
        back.moveTo(1 * k, 3 * k)
        back.lineTo(6 * k, 3 * k)
        back.lineTo(7.5 * k, 4.5 * k)
        back.lineTo(14.5 * k, 4.5 * k)
        back.lineTo(14.5 * k, 13.5 * k)
        back.lineTo(1 * k, 13.5 * k)
        back.closeSubpath()
        p.drawPath(back)
        p.setBrush(QtGui.QColor("#ece8d8"))
        p.drawRect(QtCore.QRectF(1 * k, 6 * k, 13.5 * k, 7.5 * k))
    ball = QtCore.QRectF(6.5 * k, 6.5 * k, 9 * k, 9 * k) if kind != "root" else QtCore.QRectF(1 * k, 1 * k, 14 * k, 14 * k)
    p.setPen(QtGui.QPen(QtGui.QColor("#505050"), max(0.6, 0.5 * k)))
    if kind == "scene":
        grad = QtGui.QLinearGradient(ball.topLeft(), ball.bottomLeft())
        grad.setColorAt(0, QtGui.QColor("#9cc3ec"))
        grad.setColorAt(0.55, QtGui.QColor("#f2f2f2"))
        grad.setColorAt(1, QtGui.QColor("#9a9a9a"))
        p.setBrush(QtGui.QBrush(grad))
        p.drawRect(ball)
    elif kind == "decal":
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawRect(ball)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#3c8d3c"))
        tri = QtGui.QPolygonF([QtCore.QPointF(ball.left() + 1 * k, ball.bottom() - 1 * k),
                               QtCore.QPointF(ball.center().x(), ball.top() + 2.5 * k),
                               QtCore.QPointF(ball.right() - 1 * k, ball.bottom() - 1 * k)])
        p.drawPolygon(tri)
    else:
        # three colours round the ball, lit from the upper left
        for start, colour in ((90, "#d83a2e"), (210, "#2e8b3a"), (330, "#2f63c8")):
            p.setBrush(QtGui.QColor(colour))
            p.drawPie(ball, start * 16, 120 * 16)
        shine = QtGui.QRadialGradient(ball.left() + ball.width() * 0.35, ball.top() + ball.height() * 0.35, ball.width() * 0.5)
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 170))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setBrush(QtGui.QBrush(shine))
        p.setPen(Qt.NoPen)
        p.drawEllipse(ball)
    p.end()
    return QtGui.QIcon(pix)


def _line_icon(kind, size=16):
    """Refresh (a round arrow) and Up One Level (an arrow up), in our own drawing."""
    from . import hidpi as _hidpi
    pix = _hidpi.canvas(size, size)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    k = size / 16.0
    blue = QtGui.QColor("#2a6fc9")
    p.setPen(QtGui.QPen(blue, 2.0 * k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    if kind == "refresh":
        p.drawArc(QtCore.QRectF(2.5 * k, 2.5 * k, 11 * k, 11 * k), 30 * 16, 280 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(14.5 * k, 1.5 * k), QtCore.QPointF(14.5 * k, 7 * k),
                                       QtCore.QPointF(9 * k, 6 * k)]))
    else:
        p.drawLine(QtCore.QPointF(8 * k, 14 * k), QtCore.QPointF(8 * k, 3.5 * k))
        p.setPen(Qt.NoPen)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(8 * k, 1 * k), QtCore.QPointF(13 * k, 7 * k),
                                       QtCore.QPointF(3 * k, 7 * k)]))
    p.end()
    return QtGui.QIcon(pix)


NOTE = "Drag appearances onto the model or the FeatureManager tree. Alt+drag to edit one at once."
NOTES = {
    "folder": NOTE,
    "scenes": "Drag a scene into the graphics area, or double-click it, to apply it.",
    "decals": "Drag decals onto the model, or double-click one to place it.",
}


class Swatches(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWAppearanceSwatches")

        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setFlow(QtWidgets.QListView.TopToBottom)
        self.setWrapping(False)
        self.setIconSize(QtCore.QSize(SWATCH, SWATCH))
        self.setGridSize(QtCore.QSize(SWATCH + 60, SWATCH + 34))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setWordWrap(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items:
            data.setData(MIME, QtCore.QByteArray(items[0].data(ROLE).encode()))
        return data

    def mimeTypes(self):
        return [MIME]

    def startDrag(self, actions):
        watch_views()
        from . import taskpane
        done = taskpane.shut_on_drag_out(self)
        try:
            super().startDrag(actions)
        finally:
            done()


def page(pane):
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneAppearances")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    bar = QtWidgets.QHBoxLayout()
    bar.setContentsMargins(4, 2, 4, 2)
    bar.setSpacing(2)
    lay.addLayout(bar)
    split = QtWidgets.QSplitter(Qt.Vertical, w)
    tree = QtWidgets.QTreeWidget()
    tree.setObjectName("SWAppearanceFolders")
    tree.setHeaderHidden(True)

    tree.setStyleSheet("QTreeView#SWAppearanceFolders::item:selected { background: #cce4f7; color: #000000; }"
                       "QTreeView#SWAppearanceFolders::item:hover:!selected { background: #e5f1fb; }")
    folder, root_icon = _folder_icon("appearance"), _folder_icon("root")
    top = QtWidgets.QTreeWidgetItem(["Appearances(color)"])
    top.setIcon(0, root_icon)
    top.setData(0, ROLE, ("folder", None))
    for name, entries in PALETTE:
        it = QtWidgets.QTreeWidgetItem([name])
        it.setIcon(0, folder)
        it.setData(0, ROLE, ("folder", name))
        top.addChild(it)
        if subfolders(name):
            for sub, more in subfolders(name):
                child = QtWidgets.QTreeWidgetItem([sub])
                child.setIcon(0, folder)
                child.setData(0, ROLE, ("folder", name + "/" + sub))
                it.addChild(child)
    tree.addTopLevelItem(top)
    scene_folder = _folder_icon("scene")
    scenes = QtWidgets.QTreeWidgetItem(["Scenes"])
    scenes.setIcon(0, scene_folder)
    scenes.setData(0, ROLE, ("scenes", None))
    for group, _members in SCENE_FOLDERS:
        sub = QtWidgets.QTreeWidgetItem([group])
        sub.setIcon(0, scene_folder)
        sub.setData(0, ROLE, ("scenes", group))
        scenes.addChild(sub)
    tree.addTopLevelItem(scenes)
    decals = QtWidgets.QTreeWidgetItem(["Decals"])
    decals.setIcon(0, _folder_icon("decal"))
    decals.setData(0, ROLE, ("decals", None))
    tree.addTopLevelItem(decals)
    tree.expandAll()
    sw = Swatches()
    upper = QtWidgets.QWidget()
    upper_lay = QtWidgets.QVBoxLayout(upper)
    upper_lay.setContentsMargins(0, 0, 0, 0)
    upper_lay.setSpacing(2)
    upper_lay.addWidget(tree, 1)
    default = QtWidgets.QLabel("Default Appearance: color")
    default.setObjectName("SWAppearanceDefault")
    default.setContentsMargins(4, 2, 4, 0)
    upper_lay.addWidget(default)
    note = QtWidgets.QLabel(NOTE)
    note.setObjectName("SWAppearanceNote")
    note.setWordWrap(True)
    note.setAlignment(Qt.AlignCenter)
    note.setStyleSheet("QLabel#SWAppearanceNote { background: #fbf39b; color: #000000; border: 1px solid #b7ab3a;"
                       " padding: 4px; margin: 0px 3px 3px 3px; }")
    upper_lay.addWidget(note)
    split.addWidget(upper)
    split.addWidget(sw)
    split.setSizes([300, 320])
    lay.addWidget(split, 1)
    w.tree, w.swatches, w.note, w.default = tree, sw, note, default

    # the toolbar row: Back, Forward (with the list of the folders ahead), Edit Appearance, Refresh,
    # Up One Level; Back and Forward keep their place but show only while they have somewhere to go
    history = {"items": [], "at": -1, "moving": False}

    def tool(name, tip, icon, run):
        b = QtWidgets.QToolButton(w)
        b.setObjectName(name)
        b.setAutoRaise(True)
        b.setToolTip(tip)
        b.setIcon(icon)
        b.setIconSize(QtCore.QSize(16, 16))
        b.clicked.connect(lambda checked=False: run())
        policy = b.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        b.setSizePolicy(policy)
        bar.addWidget(b)
        return b

    def go(step):
        at = history["at"] + step
        if 0 <= at < len(history["items"]):
            item = history["items"][at]
            history["at"] = at
            history["moving"] = True
            try:
                tree.setCurrentItem(item)
            finally:
                history["moving"] = False
            arrows()

    def forward_menu(menu):
        menu.clear()
        for at in range(history["at"] + 1, len(history["items"])):
            item = history["items"][at]
            act = menu.addAction(item.text(0))
            act.triggered.connect(lambda checked=False, d=at - history["at"]: go(d))

    def edit():
        try:
            from . import shell
            shell.shell().binding("EditAppearance").run()
        except Exception as _fw_err:
            _fw_log("appearpane.py:edit", _fw_err)

    def refresh_list():
        show(tree.currentItem())

    def up():
        item = tree.currentItem()
        if item is not None and item.parent() is not None:
            tree.setCurrentItem(item.parent())

    from . import icons as _icons
    back = tool("SWAppearanceBack", "Back", _icons.family("ARROW_BACK"), lambda: go(-1))
    fwd = tool("SWAppearanceForward", "Forward", _icons.family("ARROW_FORWARD"), lambda: go(1))
    fwd.setPopupMode(QtWidgets.QToolButton.MenuButtonPopup)
    fwd_menu = QtWidgets.QMenu(fwd)
    fwd_menu.aboutToShow.connect(lambda: forward_menu(fwd_menu))
    fwd.setMenu(fwd_menu)
    ball = _icons.family("DISPMGR_APPEAR")
    tool("SWAppearanceEdit", "Edit Appearance", ball if not ball.isNull() else _folder_icon("root"), edit)
    tool("SWAppearanceRefresh", "Refresh", _line_icon("refresh"), refresh_list)
    upb = tool("SWAppearanceUp", "Up One Level", _line_icon("up"), up)
    bar.addStretch(1)
    w.toolbar = {"back": back, "forward": fwd, "up": upb}

    def arrows():
        back.setVisible(history["at"] > 0)
        fwd.setVisible(history["at"] < len(history["items"]) - 1)
        item = tree.currentItem()
        upb.setVisible(item is not None and item.parent() is not None)

    def remember(item):
        if history["moving"] or item is None:
            return
        del history["items"][history["at"] + 1:]
        if not history["items"] or history["items"][-1] is not item:
            history["items"].append(item)
        history["at"] = len(history["items"]) - 1
        arrows()
    tree.currentItemChanged.connect(lambda cur, prev: remember(cur))

    def show(item, *args):
        kind, name = item.data(0, ROLE) if item is not None else ("folder", None)
        sw.clear()

        note.setText(NOTES.get(kind, NOTE))
        default.setVisible(kind == "folder")
        if kind == "folder":
            for label, rgb, tr in entries_of(name):
                s = QtWidgets.QListWidgetItem(swatch_icon(rgb, SWATCH, tr), label)
                s.setData(ROLE, payload_of(label, rgb, tr))
                s.setToolTip(tooltip(label))
                sw.addItem(s)
        elif kind == "scenes":
            from . import style
            for i in scenes_of(name, tuple(style.SCENE_MENU) + tuple(style.SCENE_EXTRAS)):
                label = style.SCENES[i][0]
                s = QtWidgets.QListWidgetItem(scene_icon(i, SWATCH), label)
                s.setData(ROLE, "scene:%d" % i)
                s.setToolTip(label)
                sw.addItem(s)
        else:

            from . import decalpm
            for label, picture, saved in decalpm.library():
                s = QtWidgets.QListWidgetItem(QtGui.QIcon(picture), label)
                s.setData(ROLE, "decal:" + (saved or picture))
                s.setToolTip(label)
                sw.addItem(s)
    def fit_names():
        # the whole name under each swatch, whatever the font (Windows display scaling and UI fonts differ)
        metrics = QtGui.QFontMetrics(sw.font())
        widest = max([metrics.horizontalAdvance(sw.item(i).text()) for i in range(sw.count())] or [0])
        sw.setGridSize(QtCore.QSize(max(SWATCH + 60, widest + 16), SWATCH + 16 + 2 * metrics.height()))
    tree.currentItemChanged.connect(lambda cur, prev: (show(cur), fit_names()))
    tree.setCurrentItem(top.child(0))

    def activated(item):
        p = _payload(QtCore.QByteArray((item.data(ROLE) or "").encode()))
        if p is None:
            return False
        if p[0] == "scene":
            from . import style
            return style.apply_scene(p[1]) or True
        if p[0] == "decal":
            from . import decalpm
            return decalpm.apply_from_library(p[1]) is not None
        return apply_selected(p[1])
    sw.itemDoubleClicked.connect(activated)
    w.activated = activated
    w.refresh = watch_views
    watch_views()
    return w
