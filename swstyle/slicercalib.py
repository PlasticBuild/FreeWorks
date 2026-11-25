"""Calibration: the slicers' Calibration menu (Temperature, Flow rate, Pressure advance, Max flowrate, VFA).

Each test puts the add-on's own test model on the plate (a new plate when the current one has objects) and sets what
the test changes, in the slicers' own files, so the slicer's program writes it into the G-code:
- Temperature: a tower of 10 mm blocks, one temperature each (per-layer G-code at each block).
- Pressure advance: a square tower, one pressure advance value per mm of height (per-layer G-code).
- Flow rate: a row of blocks, each with its own flow ratio (the objects' own setting).
- Tolerance test: a plate with six hexagonal holes 0 to 0.3 mm wider than a key printed with it.
- Max flowrate and VFA: a single-wall cup, the outer wall speed going up with the height (height ranges; the slicers
  refuse a spiral vase with height ranges, so it is a cup with one wall).
The test's changes show in bold in the settings tabs; Reset there takes them back."""
import math
import os

import FreeCAD as App
from PySide import QtWidgets

from . import slicer as backend
from . import slicercodes


TESTS = (("temp", "Temperature"), ("flow1", "Flow rate: Pass 1"), ("flow2", "Flow rate: Pass 2"),
         ("pa", "Pressure advance"), ("volspeed", "Max flowrate"), ("vfa", "VFA"), ("tolerance", "Tolerance test"))

# the slicers' temperature tower ranges by filament type: (start, end)
TEMPS = (("PLA", 230, 190), ("ABS/ASA", 270, 230), ("PETG", 250, 230), ("TPU", 240, 210),
         ("PA-CF", 320, 280), ("PET-CF", 320, 280))
FLOW_PASSES = {"flow1": (-20, -15, -10, -5, 0, 5, 10, 15, 20), "flow2": (-9, -8, -7, -6, -5, -4, -3, -2, -1, 0)}
BLOCK = 10.0           # temperature tower block height (mm)
VFA_BAND = 5.0         # VFA: one speed per 5 mm


# ---------------------------------------------------------------------------------------------- the panel's values
def _first(v, default=None):
    v = backend._first(v)
    return default if v in (None, "") else v


def values(panel, kind):
    """The preset of kind ("process", "filament", "machine") with the panel's changes on top."""
    name = panel.choice.get({"machine": "printer"}.get(kind, kind)) or ""
    data = dict(panel.slicer.resolve(kind, name)) if name else {}
    data.update(panel.choice.get({"process": "overrides", "filament": "filament_overrides",
                                  "machine": "printer_overrides"}[kind]) or {})
    return data


def nozzle(panel):
    try:
        return float(_first(values(panel, "machine").get("nozzle_diameter"), 0.4))
    except (TypeError, ValueError):
        return 0.4


def flavour(panel):
    if panel.slicer.is_bambu_printer(panel.choice.get("printer") or ""):
        return "bbl"
    return str(_first(values(panel, "machine").get("gcode_flavor"), "marlin")).lower()


def pa_gcode(k, flav):
    """The slicers' pressure advance command for the printer's firmware."""
    if flav == "bbl":
        return "M900 K%.4g L1000 M10" % k
    if flav == "klipper":
        return "SET_PRESSURE_ADVANCE ADVANCE=%.4g" % k
    if flav == "reprapfirmware":
        return "M572 D0 S%.4g" % k
    if flav == "repetier":
        return "M233 X%.4g Y%.4g" % (k, k)
    return "M900 K%.4g" % k


def temp_gcode(t, flav):
    return ("G10 P0 S%d" if flav == "reprapfirmware" else "M104 S%d") % int(round(t))


def layers(panel, item=None):
    """(first layer height, layer height) of the print (the object's own layer height first)."""
    proc = values(panel, "process")
    lh = (item.settings.get("layer_height") if item is not None else None) or _first(proc.get("layer_height"), 0.2)
    first = _first(proc.get("initial_layer_print_height"), lh)
    return float(first), float(lh)


def layer_z(h, first, lh):
    """The top of the first layer printed above height h: where a per-layer G-code for h goes."""
    if h < first - 1e-6:
        return round(first, 4)
    n = int(math.floor((h - first) / lh + 1e-6)) + 1
    return round(first + n * lh, 4)


def steps(start, end, step):
    """start, start + step, ... up to end (either way)."""
    if step <= 0:
        return [start]
    n = int(math.floor(abs(end - start) / step + 1e-6))
    sign = 1 if end >= start else -1
    return [round(start + sign * i * step, 6) for i in range(n + 1)]


# ---------------------------------------------------------------------------------------------------- the models
def font():
    path = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Resources", "fonts", "osifont-lgpl3fe.ttf")
    return path if os.path.isfile(path) else None


def text_solid(text, size, depth):
    """Raised text in the XY plane from z = 0 up to depth (None without the font)."""
    import Part
    path = font()
    if not path:
        return None
    try:
        chars = Part.makeWireString(text, os.path.dirname(path) + os.sep, os.path.basename(path), size, 0)
        faces = [Part.makeFace(w, "Part::FaceMakerBullseye") for w in chars if w]
        return Part.makeCompound(faces).extrude(App.Vector(0, 0, depth)) if faces else None
    except Exception:
        return None


def _put(solid, x, y, z, rot=None):
    s = solid.copy()
    if rot is not None:
        s.rotate(App.Vector(0, 0, 0), *rot)
    s.translate(App.Vector(x, y, z))
    return s


def temp_tower(temps):
    """Blocks of 10 mm, a bridge and the temperature engraved on the front of each."""
    import Part
    solid = None
    for i, t in enumerate(temps):
        z = i * BLOCK
        b = Part.makeBox(30, 10, BLOCK, App.Vector(0, 0, z))
        b = b.cut(Part.makeBox(12, 10.2, 4, App.Vector(16, -0.1, z + 2)))      # the bridge
        txt = text_solid("%d" % t, 5.0, 0.6)
        if txt is not None:
            bb = txt.BoundBox
            # lying on the front face (y = 0): x along the face, the text's y up the tower, cut 0.6 mm in
            txt = _put(txt, 0, 0, 0, (App.Vector(1, 0, 0), 90))
            txt.translate(App.Vector(8 - (bb.XMin + bb.XMax) / 2, 0.6 - 0.0, z + BLOCK / 2 - (bb.YMin + bb.YMax) / 2))
            b = b.cut(txt)
        solid = b if solid is None else solid.fuse(b)
    return solid.removeSplitter()


def pa_tower(height, start, step, wall=2.4, side=50.0):
    """A square tube; the value at each 5 mm engraved on the front."""
    import Part
    tube = Part.makeBox(side, side, height).cut(
        Part.makeBox(side - 2 * wall, side - 2 * wall, height + 1, App.Vector(wall, wall, -0.5)))
    for h in range(5, int(height), 5):
        txt = text_solid("%.3f" % (start + step * h), 3.0, 0.6)
        if txt is None:
            break
        bb = txt.BoundBox
        txt = _put(txt, 0, 0, 0, (App.Vector(1, 0, 0), 90))
        txt.translate(App.Vector(side / 2 - (bb.XMin + bb.XMax) / 2, 0.6, h - 1.5 - bb.YMin))
        tube = tube.cut(txt)
    return tube.removeSplitter()


def flow_block(modifier):
    """A 20 x 20 block to judge the top surface by; its flow change engraved at the back of the top."""
    import Part
    b = Part.makeBox(20, 20, 3.0)
    txt = text_solid("%+d" % modifier if modifier else "0", 3.5, 1.0)
    if txt is not None:
        bb = txt.BoundBox
        b = b.cut(_put(txt, 10 - (bb.XMin + bb.XMax) / 2, 15.5 - bb.YMin, 2.4)).removeSplitter()
    return b


TOLERANCES = (0.0, 0.05, 0.1, 0.15, 0.2, 0.3)
HEX = 10.0             # the tolerance test's hexagon, across the flats (mm)


def hexagon(across, height):
    """A hexagonal prism standing on z = 0, centred on the origin, flats parallel to X."""
    import Part
    r = across / math.sqrt(3.0)          # the corner radius
    pts = [App.Vector(r * math.cos(math.radians(60 * k)), r * math.sin(math.radians(60 * k)), 0) for k in range(7)]
    return Part.Face(Part.makePolygon(pts)).extrude(App.Vector(0, 0, height))


def tolerance_plate():
    """A plate with six hexagonal holes, each wider than the key by its tolerance (engraved under it)."""
    import Part
    pitch = 16.0
    plate = Part.makeBox(pitch * len(TOLERANCES) + 4, 24, 6, App.Vector(0, 0, 0))
    for k, tol in enumerate(TOLERANCES):
        x = 2 + pitch * (k + 0.5)
        hole = hexagon(HEX + 2 * tol, 8)
        hole.translate(App.Vector(x, 10, -1))
        plate = plate.cut(hole)
        txt = text_solid("%g" % tol, 3.0, 0.6)
        if txt is not None:
            bb = txt.BoundBox
            plate = plate.cut(_put(txt, x - (bb.XMin + bb.XMax) / 2, 19.5 - bb.YMin, 5.4))
    return plate.removeSplitter()


def tolerance_key():
    """The key: a hexagon the size of the holes' nominal, with a grip."""
    import Part
    key = hexagon(HEX, 14)
    grip = Part.makeCylinder(9, 3)
    return key.fuse(grip).removeSplitter()


def vase(height, radius=25.0):
    """A cylinder: sliced with one wall, no top and no infill, it prints as a cup."""
    import Part
    return Part.makeCylinder(radius, height)


# -------------------------------------------------------------------------------------------------- the dialogs
class Dialog(QtWidgets.QDialog):
    """Start / End / Step, and a filament type for the temperature tower."""

    def __init__(self, title, fields, note="", types=None, parent=None):
        super().__init__(parent or QtWidgets.QApplication.activeWindow())
        self.setObjectName("SWStyle_SlicerCalibDialog")
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.fields = {}
        self.types = None
        if types:
            self.types = QtWidgets.QComboBox()
            self.types.setObjectName("SWStyle_SlicerCalibType")
            for name, a, b in types:
                self.types.addItem(name, (a, b))
            self.types.currentIndexChanged.connect(self._type)
            form.addRow("Filament type", self.types)
        for key, label, value, lo, hi, decimals, single in fields:
            f = QtWidgets.QDoubleSpinBox()
            f.setObjectName("SWStyle_SlicerCalib_" + key)
            f.setDecimals(decimals)
            f.setRange(lo, hi)
            f.setSingleStep(single)
            f.setValue(value)
            form.addRow(label, f)
            self.fields[key] = f
        lay.addLayout(form)
        if note:
            n = QtWidgets.QLabel(note)
            n.setWordWrap(True)
            n.setObjectName("SWStyle_SlicerCalibNote")
            lay.addWidget(n)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWStyle_SlicerCalibError")
        self.error.setStyleSheet("color:#e53935;")
        self.error.hide()
        lay.addWidget(self.error)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.button(QtWidgets.QDialogButtonBox.Ok).setText("OK")
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.check = None

    def _type(self, _i=None):
        a, b = self.types.currentData()
        self.fields["start"].setValue(a)
        self.fields["end"].setValue(b)

    def value(self, key):
        return self.fields[key].value()

    def _ok(self):
        msg = self.check(self) if self.check else ""
        if msg:
            self.error.setText(msg)
            self.error.show()
            return
        self.accept()


def _ask(dlg):
    """Shows the dialog; a check may answer it instead (SWSTYLE_CALIB_ANSWER = "accept")."""
    Dialog.last = dlg
    if os.environ.get("SWSTYLE_CALIB_ANSWER") == "accept":
        dlg._ok()
        return dlg.result() == QtWidgets.QDialog.Accepted
    return dlg.exec() == QtWidgets.QDialog.Accepted


def dialog(panel, test):
    """The test's dialog (None for the flow passes, which have no values)."""
    if test == "temp":
        d = Dialog("Temperature calibration",
                   [("start", "Start temp (°C)", 230, 150, 350, 0, 5), ("end", "End temp (°C)", 190, 150, 350, 0, 5),
                    ("step", "Temp step (°C)", 5, 1, 20, 0, 1)],
                   "The tower prints one 10 mm block per temperature, the start temperature at the bottom. Pick the "
                   "block that looks best.", TEMPS)
        d.check = lambda x: "" if x.value("start") > x.value("end") else "The start temperature must be above the end."
        return d
    if test == "pa":
        bbl = flavour(panel) == "bbl"
        d = Dialog("Pressure advance calibration",
                   [("start", "Start PA", 0.0, 0, 2, 3, 0.001), ("end", "End PA", 0.06 if bbl else 0.1, 0, 2, 3, 0.001),
                    ("step", "PA step", 0.002, 0.001, 0.5, 3, 0.001)],
                   "The pressure advance goes up by the step every 1 mm of the tower. Measure the height where the "
                   "corners look best: PA = start + step × height (mm).")
        d.check = lambda x: "" if x.value("end") > x.value("start") else "The end must be above the start."
        return d
    if test == "volspeed":
        d = Dialog("Max flowrate calibration",
                   [("start", "Start volumetric speed (mm³/s)", 5, 0.5, 100, 1, 0.5),
                    ("end", "End volumetric speed (mm³/s)", 20, 0.5, 100, 1, 0.5),
                    ("step", "Step (mm³/s)", 0.5, 0.1, 10, 1, 0.1)],
                   "The cup's volumetric speed goes up by the step every 1 mm. Measure the height where the wall "
                   "starts to fail: max flowrate = start + step × height (mm).")
        d.check = lambda x: "" if x.value("end") > x.value("start") else "The end must be above the start."
        return d
    if test == "vfa":
        d = Dialog("VFA test",
                   [("start", "Start speed (mm/s)", 40, 10, 1000, 0, 10), ("end", "End speed (mm/s)", 200, 10, 1000, 0, 10),
                    ("step", "Step (mm/s)", 10, 1, 100, 0, 5)],
                   "The cup's outer wall speed goes up by the step every 5 mm. Speeds with vertical fine artifacts on "
                   "the wall are the ones to avoid.")
        d.check = lambda x: "" if x.value("end") > x.value("start") else "The end must be above the start."
        return d
    return None


# --------------------------------------------------------------------------------------------------- the tests
def _plate(panel):
    """A plate for the test: the current one when it is empty, else a new one."""
    bed = panel.bed
    if any(it.plate == bed.current for it in bed.items):
        bed.add_plate()
    slicercodes.clear(panel)
    return bed.current


def _add(panel, name, shape):
    from . import slicerplate
    bed = panel.bed
    it = slicerplate.Item(name, shape, slicerplate.mesh_of(shape), None)
    it.plate = bed.current
    it.pinned = True
    bed.items.append(it)
    return it


def _done(panel, items, message):
    bed = panel.bed
    prep = getattr(panel, "mode_buttons", {}).get("prepare")
    if prep is not None and not prep.isChecked():
        prep.click()
    bed.selected = {bed.items.index(items[0])} if items else set()
    bed._pack()
    bed._redraw()
    bed._changed()
    panel._show_values()
    panel._stale()
    status(panel, message)


def status(panel, message):
    panel.calib_status = message
    lab = getattr(panel, "status", None)
    try:
        if lab is not None and hasattr(lab, "setText"):
            lab.setText(message)
    except Exception:
        pass


def _too_tall(panel, height):
    tall = float(getattr(panel.bed, "height", 250.0) or 250.0)
    return height > tall - 1


def run(panel, test, answer=None):
    """Sets the test up on the plate. Returns the test's items ([] when it was cancelled or cannot be made)."""
    d = dialog(panel, test)
    if d is not None:
        if answer:
            for k, v in answer.items():
                if k == "type":
                    d.types.setCurrentIndex(max(0, d.types.findText(v)))
                else:
                    d.fields[k].setValue(v)
        if not _ask(d):
            return []
    flav = flavour(panel)
    if test == "temp":
        temps = steps(d.value("start"), d.value("end"), d.value("step"))
        if _too_tall(panel, len(temps) * BLOCK):
            QtWidgets.QMessageBox.warning(None, "Temperature calibration", "The tower is taller than the printer.")
            return []
        _plate(panel)
        it = _add(panel, "Temperature tower", temp_tower(temps))
        first, lh = layers(panel, it)
        for i, t in enumerate(temps):
            slicercodes.add(panel, layer_z(i * BLOCK, first, lh), slicercodes.CUSTOM, 1, "", temp_gcode(t, flav))
        fo = panel.choice.setdefault("filament_overrides", {})
        fo["nozzle_temperature"] = "%d" % int(temps[0])
        fo["nozzle_temperature_initial_layer"] = "%d" % int(temps[0])
        _done(panel, [it], "Temperature tower %d–%d °C on the plate." % (temps[0], temps[-1]))
        return [it]
    if test == "pa":
        start, step = d.value("start"), d.value("step")
        ks = steps(start, d.value("end"), step)
        height = max(5.0, float(len(ks)))
        if _too_tall(panel, height):
            QtWidgets.QMessageBox.warning(None, "Pressure advance calibration", "The tower is taller than the printer.")
            return []
        _plate(panel)
        it = _add(panel, "Pressure advance tower", pa_tower(height, start, step))
        first, lh = layers(panel, it)
        last = None
        for h, k in enumerate(ks):
            z = layer_z(float(h), first, lh) if h else round(first, 4)
            if z != last:
                slicercodes.add(panel, z, slicercodes.CUSTOM, 1, "", pa_gcode(k, flav))
                last = z
        fo = panel.choice.setdefault("filament_overrides", {})
        fo["enable_pressure_advance"] = "0"   # the tower's own values only
        fo["adaptive_pressure_advance"] = "0"
        _done(panel, [it], "Pressure advance tower %.3f–%.3f on the plate." % (ks[0], ks[-1]))
        return [it]
    if test in FLOW_PASSES:
        _plate(panel)
        items = []
        for m in FLOW_PASSES[test]:
            it = _add(panel, "Flow %+d" % m if m else "Flow 0", flow_block(m))
            it.settings["print_flow_ratio"] = "%.2f" % (1 + m / 100.0)
            items.append(it)
        _done(panel, items, "Flow rate %s on the plate: pick the smoothest top, then multiply the filament's flow "
              "ratio by (100 + its number) / 100." % ("pass 1" if test == "flow1" else "pass 2"))
        return items
    if test == "tolerance":
        _plate(panel)
        items = [_add(panel, "Tolerance plate", tolerance_plate()), _add(panel, "Tolerance key", tolerance_key())]
        _done(panel, items, "Tolerance test on the plate: the key fits the holes from the tolerance engraved under "
              "the first one it goes into (0 to 0.3 mm).")
        return items
    if test in ("volspeed", "vfa"):
        n = nozzle(panel)
        if test == "volspeed":
            lh, lw = round(n * 0.8, 2), round(n * 1.75, 2)
            vals = steps(d.value("start"), d.value("end"), d.value("step"))
            band = 1.0
            speeds = [v / (lw * lh) for v in vals]
        else:
            lh, lw = None, None
            vals = steps(d.value("start"), d.value("end"), d.value("step"))
            band = VFA_BAND
            speeds = vals
        height = max(10.0, len(vals) * band)
        if _too_tall(panel, height):
            QtWidgets.QMessageBox.warning(None, d.windowTitle(), "The cup is taller than the printer.")
            return []
        _plate(panel)
        it = _add(panel, "Max flowrate cup" if test == "volspeed" else "VFA cup", vase(height))
        if lh:
            it.settings["layer_height"] = "%g" % lh
            it.settings["outer_wall_line_width"] = "%g" % lw
        it.settings.update({"wall_loops": "1", "top_shell_layers": "0", "bottom_shell_layers": "1",
                            "sparse_infill_density": "0%"})
        # (a height range always carries its layer height, as the slicers' own: without it their program crashes)
        rlh = "%g" % (lh or layers(panel, it)[1])
        it.ranges = [{"min_z": round(i * band, 3), "max_z": round((i + 1) * band, 3),
                      "params": {"layer_height": rlh, "outer_wall_speed": "%.1f" % s}} for i, s in enumerate(speeds)]
        panel.choice.setdefault("overrides", {})
        fo = panel.choice.setdefault("filament_overrides", {})
        fo["filament_max_volumetric_speed"] = "200"   # the slicer would cap the speeds
        fo["slow_down_layer_time"] = "0"
        if lh:
            panel.choice["overrides"]["initial_layer_print_height"] = "%g" % lh
        _done(panel, [it], "%s cup %g–%g %s on the plate." % (
            "Max flowrate" if test == "volspeed" else "VFA", vals[0], vals[-1],
            "mm³/s" if test == "volspeed" else "mm/s"))
        return [it]
    return []


def menu(panel, parent=None):
    """The Calibration menu."""
    m = QtWidgets.QMenu(parent)
    m.setObjectName("SWStyle_SlicerCalibMenu")
    flow = None
    for key, text in TESTS:
        if key.startswith("flow"):
            if flow is None:
                flow = m.addMenu("Flow rate")
                flow.setObjectName("SWStyle_SlicerCalibFlow")
            a = flow.addAction(text.split(": ", 1)[1])
        else:
            a = m.addAction(text)
        a.setObjectName("SWStyle_SlicerCalib_" + key)
        a.setData(key)
        a.triggered.connect(lambda _=False, k=key: run(panel, k))
    return m
