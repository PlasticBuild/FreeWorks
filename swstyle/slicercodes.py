"""Color change, pause, filament change and custom G-code at a layer: the slicers' right-click on the Preview's layer
slider. They go to the slicer in the plate's 3MF (Metadata/custom_gcode_per_layer.xml, the slicers' own file), so a
plate with them is sliced by the slicer's program; the slicer writes them into the G-code."""
from xml.sax.saxutils import quoteattr

from PySide import QtCore, QtGui, QtWidgets

# the slicers' CustomGCode types
COLOR_CHANGE, PAUSE, TOOL_CHANGE, CUSTOM = 0, 1, 2, 4
TITLES = {COLOR_CHANGE: "Color change", PAUSE: "Pause", TOOL_CHANGE: "Filament change", CUSTOM: "Custom G-code"}
MARK_COLOURS = {COLOR_CHANGE: "#e53935", PAUSE: "#f9a825", TOOL_CHANGE: "#1f6fb2", CUSTOM: "#8e24aa"}


def codes(panel, plate=None):
    """The codes of a plate (default: the current one): [{"z", "type", "extruder", "color", "extra"}] by height."""
    store = getattr(panel, "layer_codes", None)
    if store is None:
        store = panel.layer_codes = {}
    p = panel.bed.current if plate is None else plate
    return store.setdefault(p, [])


def add(panel, z, kind, extruder=1, color="", extra=""):
    lst = codes(panel)
    lst[:] = [c for c in lst if not (abs(c["z"] - z) < 1e-6 and c["type"] == kind)]
    lst.append({"z": round(float(z), 4), "type": kind, "extruder": int(extruder), "color": color, "extra": extra})
    lst.sort(key=lambda c: c["z"])
    panel._stale()
    return lst


def remove_at(panel, z):
    lst = codes(panel)
    n = len(lst)
    lst[:] = [c for c in lst if abs(c["z"] - z) >= 1e-6]
    if len(lst) != n:
        panel._stale()
    return n - len(lst)


def clear(panel):
    lst = codes(panel)
    if lst:
        lst[:] = []
        panel._stale()


def xml(items, filaments=1):
    """Metadata/custom_gcode_per_layer.xml for one plate (the slicers' format)."""
    gcode = {COLOR_CHANGE: "M600", PAUSE: "M601", TOOL_CHANGE: "tool_change"}
    rows = ['<?xml version="1.0" encoding="utf-8"?>', "<custom_gcodes_per_layer>", "<plate>", '<plate_info id="1"/>']
    for c in items:
        rows.append('<layer top_z="%g" type="%d" extruder="%d" color=%s extra=%s gcode=%s/>' % (
            c["z"], c["type"], c["extruder"], quoteattr(c.get("color") or ""), quoteattr(c.get("extra") or ""),
            quoteattr(gcode.get(c["type"], c.get("extra") or ""))))
    rows.append('<mode value="%s"/>' % ("SingleExtruder" if filaments <= 1 else "MultiAsSingle"))
    rows += ["</plate>", "</custom_gcodes_per_layer>"]
    return "\n".join(rows) + "\n"


def xml_plates(by_plate, filaments=1):
    """The file for several plates: by_plate = [(plate number 1-based, items)]."""
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<custom_gcodes_per_layer>"]
    for number, items in by_plate:
        one = xml(items, filaments).splitlines()
        body = one[3:-2]                                   # inside <plate>: plate_info, layers, mode
        body[0] = '<plate_info id="%d"/>' % number
        out += ["<plate>"] + body + ["</plate>"]
    out.append("</custom_gcodes_per_layer>")
    return "\n".join(out) + "\n"


def color_change_gcode(panel):
    """The printer's color change G-code ("" when its profile has none: then the slicer writes nothing for it)."""
    try:
        m = dict(panel.slicer.resolve("machine", panel.choice["printer"]))
        m.update(panel.choice.get("printer_overrides") or {})
        v = m.get("color_change_gcode", "")
        return (v[0] if isinstance(v, list) and v else v) or ""
    except Exception:
        return ""


def menu(panel, slider, layer_index, pos):
    """The right-click menu of the layer slider at a layer (1-based)."""
    pv = panel.preview
    if not (0 < layer_index <= len(pv.layers)):
        return None
    z = pv.raw_layers[layer_index - 1] if getattr(pv, "raw_layers", None) else pv.layers[layer_index - 1]
    m = QtWidgets.QMenu(slider)
    m.setObjectName("SWStyle_SlicerLayerMenu")
    m.addSection("Layer %d  (%.2f mm)" % (layer_index, z))     # a heading, not a greyed item
    colours = list(getattr(panel.slots, "colours", []) or [])
    if len(colours) > 1:
        sub = m.addMenu("Change filament")
        sub.setObjectName("SWStyle_SlicerLayerFilament")
        for i, c in enumerate(colours, 1):
            a = sub.addAction("Filament %d" % i)
            pix = QtGui.QPixmap(12, 12)
            pix.fill(QtGui.QColor(c))
            a.setIcon(QtGui.QIcon(pix))
            a.triggered.connect(lambda _=False, i=i, c=c: _done(panel, slider, add(panel, z, TOOL_CHANGE, i, c)))
    cc = m.addAction("Add color change")
    have = color_change_gcode(panel)
    cc.setToolTip("The print stops for a new filament (the printer's color change G-code: %s)" % (have or "none"))
    cc.triggered.connect(lambda: _color_change(panel, slider, z, have))
    pa = m.addAction("Add pause")
    pa.setToolTip("The printer pauses after this layer (to put in a magnet or a nut, say)")
    pa.triggered.connect(lambda: _done(panel, slider, add(panel, z, PAUSE, 1, "", "Paused at %.2f mm" % z)))
    cu = m.addAction("Add custom G-code...")
    cu.triggered.connect(lambda: _custom(panel, slider, z))
    here = [c for c in codes(panel) if abs(c["z"] - z) < 1e-6]
    if here:
        m.addSeparator()
        d = m.addAction("Delete %s here" % ", ".join(TITLES[c["type"]].lower() for c in here))
        d.triggered.connect(lambda: _done(panel, slider, remove_at(panel, z)))
    if codes(panel):
        da = m.addAction("Delete all")
        da.triggered.connect(lambda: _done(panel, slider, clear(panel)))
    panel._layer_menu = m
    m.popup(pos)
    return m


def _done(panel, slider, _result=None):
    slider.update()
    panel._say("Slice again to put the changes at a layer into the G-code.")


def _color_change(panel, slider, z, have):
    if not have:
        panel._say("This printer's profile has no color change G-code, so the slicer would write nothing there. "
                   "Use Add pause, or Change filament with two filaments.")
        return
    _done(panel, slider, add(panel, z, COLOR_CHANGE, 1, "#ffffff"))


def _custom(panel, slider, z):
    text, ok = QtWidgets.QInputDialog.getMultiLineText(slider, "Custom G-code", "G-code to run after the layer at "
                                                       "%.2f mm:" % z, "")
    if ok and text.strip():
        _done(panel, slider, add(panel, z, CUSTOM, 1, "", text.strip()))


def marks(panel):
    """(layer index 1-based, colour) for the slider's ticks."""
    pv = panel.preview
    raw = getattr(pv, "raw_layers", None) or pv.layers
    out = []
    for c in codes(panel):
        for i, z in enumerate(raw, 1):
            if abs(z - c["z"]) < 1e-4:
                colour = c.get("color") if c["type"] == TOOL_CHANGE and c.get("color") else MARK_COLOURS.get(c["type"], "#888888")
                out.append((i, colour))
                break
    return out
