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
import os

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except Exception:   # pragma: no cover
    Gui = None

FOLDER = "Power Transmission"
KINDS = {   # key: (sub-folder, name)
    "spur-gear": ("Gears", "Spur Gear"),
    "internal-gear": ("Gears", "Internal Gear"),
    "chain-sprocket": ("Chain Sprockets", "Sprocket"),
    "shaft-wizard": ("Shafts", "Shaft Wizard"),
}
PROP = "FwPowerTransmission"     # "<kind>;<spec>" on the part's body
PRESSURE_ANGLES = (14.5, 20.0, 25.0)
HUB_STYLES = ("None", "One Side", "Both Sides")
KEYWAYS = ("None", "Rectangular (1)")
# DIN 6885 parallel keys: shaft over (mm) -> (width, hub depth t2)
KEYS = ((6, 2, 1.0), (8, 3, 1.4), (10, 4, 1.8), (12, 5, 2.3), (17, 6, 2.8), (22, 8, 3.3), (30, 10, 3.3),
        (38, 12, 3.3), (44, 14, 3.8), (50, 16, 4.3), (58, 18, 4.4), (65, 20, 4.9), (75, 22, 5.4))


def handles(url):
    from . import toolbox
    return toolbox.is_toolbox(url) and kind_of(url) is not None


def kind_of(url):
    key = url.rstrip("/").rsplit("/", 1)[-1]
    return key if key in KINDS and ("/" + FOLDER + "/") in url else None


def folders(url_std):
    """[(path, label)] of the Power Transmission folder under one standard's Toolbox folder."""
    out = [(url_std + "/" + FOLDER, FOLDER)]
    seen = []
    for sub, _n in KINDS.values():
        if sub not in seen:
            seen.append(sub)
            out.append((url_std + "/" + FOLDER + "/" + sub, sub))
    return out


def items(url_std, rel):
    """The items of a Power Transmission sub-folder: [(url, name)]."""
    if not rel.startswith(FOLDER + "/"):
        return []
    sub = rel[len(FOLDER) + 1:]
    return [(url_std + "/" + FOLDER + "/" + sub + "/" + key, name) for key, (s, name) in KINDS.items() if s == sub]


def key_for(shaft):
    """(width, hub depth) of the DIN 6885 key for a shaft diameter."""
    pick = KEYS[0]
    for over, b, t2 in KEYS:
        if shaft > over - 1e-9:
            pick = (over, b, t2)
    return pick[1], pick[2]


# --------------------------------------------------------------------------- specs
def default_spec(kind, std="ISO"):
    if kind == "chain-sprocket":
        return {"kind": kind, "chain": 1, "teeth": 18, "bore": 12.0, "keyway": KEYWAYS[0],
                "hub": HUB_STYLES[0], "std": std}
    inch = std == "ANSI Inch"
    return {"kind": kind, "module": 25.4 / 24 if inch else 2.0, "teeth": 24 if kind == "spur-gear" else 48,
            "pressure": 20.0, "face": 0.375 * 25.4 if inch else 15.0, "bore": 12.0,
            "keyway": KEYWAYS[0], "hub": HUB_STYLES[0], "std": std}


def sprocket_table():
    try:
        import SprocketFeature
        return SprocketFeature.Sprocket.SprocketReferenceRollerTable
    except Exception:
        return {1: [0.375, 0.200, 0.168, "ANSI 35"]}


def title(spec):
    k = spec["kind"]
    if k == "chain-sprocket":
        chain = sprocket_table().get(spec["chain"], [0, 0, 0, "Chain"])[3]
        return "Sprocket %s %dT" % (chain, spec["teeth"])
    name = KINDS[k][1]
    if spec.get("std") == "ANSI Inch":
        return "%s %gDP %dT %gPA %gFW" % (name, round(25.4 / spec["module"], 3), spec["teeth"], spec["pressure"],
                                         round(spec["face"] / 25.4, 4))
    return "%s %gM %dT %gPA %gFW" % (name, spec["module"], spec["teeth"], spec["pressure"], spec["face"])


def pitch_diameter(spec):
    if spec["kind"] == "chain-sprocket":
        p = sprocket_table()[spec["chain"]][0] * 25.4
        return p / math.sin(math.pi / spec["teeth"])
    return spec["module"] * spec["teeth"]


# --------------------------------------------------------------------------- building
def _bore_wire(r, keyway, top=None):
    import Part
    V = App.Vector
    if keyway == KEYWAYS[0] or r <= 0:
        return Part.Wire(Part.Circle(V(), V(0, 0, 1), r).toShape())
    b, t2 = key_for(2 * r)
    b = min(b, 1.6 * r)
    yc = math.sqrt(max(r * r - (b / 2) ** 2, 0.0))
    ytop = r + t2 if top is None else top
    th = math.atan2(yc, b / 2)
    arc = Part.ArcOfCircle(Part.Circle(V(), V(0, 0, 1), r), math.pi - th, 2 * math.pi + th).toShape()
    lines = [Part.LineSegment(V(b / 2, yc, 0), V(b / 2, ytop, 0)).toShape(),
             Part.LineSegment(V(b / 2, ytop, 0), V(-b / 2, ytop, 0)).toShape(),
             Part.LineSegment(V(-b / 2, ytop, 0), V(-b / 2, yc, 0)).toShape()]
    return Part.Wire(Part.__sortEdges__([arc] + lines))


def _sketch_of_wire(body, name, wire, z=0.0):
    import Part
    sk = body.newObject("Sketcher::SketchObject", name)
    xy = [f for f in body.Origin.OriginFeatures if getattr(f, "Role", "") == "XY_Plane"][0]
    sk.AttachmentSupport = [(xy, "")]
    sk.MapMode = "FlatFace"
    if z:
        sk.AttachmentOffset = App.Placement(App.Vector(0, 0, z), App.Rotation())
    for e in wire.Edges:
        c = e.Curve
        if isinstance(c, Part.Circle) and e.isClosed():
            sk.addGeometry(Part.Circle(c.Center, App.Vector(0, 0, 1), c.Radius))
        elif isinstance(c, Part.Circle):
            sk.addGeometry(Part.ArcOfCircle(Part.Circle(c.Center, App.Vector(0, 0, 1), c.Radius),
                                            e.FirstParameter, e.LastParameter))
        else:
            sk.addGeometry(Part.LineSegment(e.Vertexes[0].Point, e.Vertexes[-1].Point))
    return sk


def build(doc, spec):
    """The gear or sprocket as a PartDesign body in doc. Returns the body."""
    body = doc.addObject("PartDesign::Body", "Body")
    kind = spec["kind"]
    if kind == "chain-sprocket":
        import SprocketFeature
        prof = doc.addObject("Part::Part2DObjectPython", "Sprocket")
        SprocketFeature.Sprocket(prof)
        if App.GuiUp:
            SprocketFeature.ViewProviderSprocket(prof.ViewObject)
        row = sprocket_table()[spec["chain"]]
        prof.Pitch = row[0] * 25.4
        prof.RollerDiameter = row[1] * 25.4
        prof.Thickness = row[2] * 25.4
        try:
            prof.SprocketReference = int(spec["chain"])
        except Exception as _fw_err:
            _fw_log("powertrans.py:188", _fw_err)
        prof.NumberOfTeeth = int(spec["teeth"])
        width = row[2] * 25.4
    else:
        import InvoluteGearFeature
        prof = doc.addObject("Part::Part2DObjectPython", "InvoluteGear")
        InvoluteGearFeature._InvoluteGear(prof)
        if App.GuiUp:
            InvoluteGearFeature._ViewProviderInvoluteGear(prof.ViewObject)
        prof.Modules = spec["module"]
        prof.NumberOfTeeth = int(spec["teeth"])
        prof.PressureAngle = spec["pressure"]
        prof.ExternalGear = kind == "spur-gear"
        if kind == "internal-gear":
            prof.AddendumCoefficient = 0.6
        width = spec["face"]
    body.addObject(prof)
    doc.recompute()
    if kind == "internal-gear":
        # the ring: a rim round the internal teeth, its outer edge 2.5 modules past the roots
        import Part
        rim = (spec["module"] * spec["teeth"]) / 2.0 + 2.5 * spec["module"] + 1.25 * spec["module"]
        ring = _sketch_of_wire(body, "Rim", Part.Wire(Part.Circle(App.Vector(), App.Vector(0, 0, 1), rim).toShape()))
        doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Rim")
        pad.Profile = ring
        pad.Length = width
        doc.recompute()
        cut = body.newObject("PartDesign::Pocket", "Teeth")
        cut.Profile = prof
        cut.Type = "ThroughAll"
        cut.Midplane = True
        doc.recompute()
        last = cut
    else:
        pad = body.newObject("PartDesign::Pad", "Teeth")
        pad.Profile = prof
        pad.Length = width
        doc.recompute()
        last = pad
        hub = spec.get("hub", HUB_STYLES[0])
        bore = float(spec.get("bore", 0.0))
        if hub != HUB_STYLES[0]:
            hub_d = max(1.8 * bore, bore + 8.0)
            root = pitch_diameter(spec) - 2.5 * spec.get("module", 2.0)
            hub_d = min(hub_d, max(root - 2.0, bore + 2.0))
            import Part
            for i, z in enumerate((width,) if hub == "One Side" else (width, 0.0)):
                hs = _sketch_of_wire(body, "Hub", Part.Wire(Part.Circle(App.Vector(), App.Vector(0, 0, 1), hub_d / 2).toShape()), z)
                doc.recompute()
                hp = body.newObject("PartDesign::Pad", "Hub")
                hp.Profile = hs
                hp.Length = max(0.5 * width, 3.0)
                hp.Reversed = z == 0.0 and i == 1
                doc.recompute()
                last = hp
        if bore > 0:
            bs = _sketch_of_wire(body, "Bore", _bore_wire(bore / 2.0, spec.get("keyway", KEYWAYS[0])))
            doc.recompute()
            cut = body.newObject("PartDesign::Pocket", "Bore")
            cut.Profile = bs
            cut.Type = "ThroughAll"
            cut.Midplane = True
            doc.recompute()
            last = cut
    body.Tip = last
    doc.recompute()
    body.addProperty("App::PropertyString", PROP, "Toolbox", "Toolbox power transmission part")
    setattr(body, PROP, "%s;%s" % (kind, repr(sorted(spec.items()))))
    body.Label = title(spec)
    return body


def part_file(spec):
    """The part file for this size, made the first time it is asked for (as Toolbox fasteners)."""
    from . import toolbox
    folder = os.path.join(toolbox.library_folder(spec.get("std", "ISO")), FOLDER, KINDS[spec["kind"]][0])
    os.makedirs(folder, exist_ok=True)
    name = title(spec)
    extra = "" if spec.get("bore", 0) <= 0 else " %gB" % spec["bore"]
    extra += "" if spec.get("keyway", KEYWAYS[0]) == KEYWAYS[0] else " K"
    extra += "" if spec.get("hub", HUB_STYLES[0]) == HUB_STYLES[0] else " H%d" % HUB_STYLES.index(spec["hub"])
    path = os.path.join(folder, (name + extra).replace(" ", "_").replace("/", "_") + ".FCStd")
    if os.path.isfile(path):
        return path
    keep = App.ActiveDocument
    try:
        doc = App.newDocument("Toolbox", hidden=True, temp=True)
    except TypeError:
        doc = App.newDocument("Toolbox")
    try:
        build(doc, spec)
        doc.saveAs(path)
    finally:
        App.closeDocument(doc.Name)
        if keep is not None and keep.Name in App.listDocuments():
            from . import designlib
            designlib._front(keep)
    return path


def place(spec, doc=None, point=None):
    """Puts the part in: a component of doc's assembly at point, else its own new part document.
    Returns the component or the body."""
    from . import asmcore, toolbox
    asm = asmcore.assembly_of(doc) if doc is not None and asmcore.is_assembly(doc) else None
    if asm is None:
        from . import newdoc
        try:
            new = newdoc.make("Part")
        except Exception:
            new = App.newDocument("Part")
        for o in list(new.Objects):
            if o.TypeId == "PartDesign::Body" and not o.Group:
                new.removeObject(o.Name)     # the empty body a new part starts with
        body = build(new, spec)
        if App.GuiUp:
            try:
                Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
                Gui.SendMsgToActiveView("ViewFit")
            except Exception as _fw_err:
                _fw_log("powertrans.py:309", _fw_err)
        return body
    path = part_file(spec)
    doc.openTransaction("Insert Toolbox Component")
    try:
        link, _t = toolbox._insert_part(asm, path, App.Placement(point or App.Vector(), App.Rotation()))
    finally:
        doc.commitTransaction()
    doc.recompute()
    return link


def shaft_wizard(doc=None):
    """FreeCAD's Shaft Wizard, in a new part when none is open."""
    if App.ActiveDocument is None or doc is None:
        from . import newdoc
        try:
            newdoc.make("Part")
        except Exception:
            App.newDocument("Part")
    try:
        import PartDesignGui  # noqa: F401  (the PartDesign commands)
    except Exception as _fw_err:
        _fw_log("powertrans.py:332", _fw_err)
    try:
        from WizardShaft import WizardShaft  # noqa: F401  (registers PartDesign_WizardShaft)
    except Exception as _fw_err:
        _fw_log("powertrans.py:336", _fw_err)
    mw = Gui.getMainWindow()
    if QtWidgets.QApplication.activeWindow() is None:
        mw.activateWindow()     # FreeCAD's wizard looks for its window through the active one
        QtWidgets.QApplication.setActiveWindow(mw)
    Gui.runCommand("PartDesign_WizardShaft", 0)
    return True


def drop(url, doc=None, point=None):
    """A Power Transmission item dropped or double-clicked: its PropertyManager, then the part."""
    from . import toolbox
    kind = kind_of(url)
    if kind is None:
        return None
    if kind == "shaft-wizard":
        return shaft_wizard(doc)
    spec = default_spec(kind, toolbox.std_of_url(url))
    from . import asmcore
    if App.GuiUp and doc is not None and asmcore.is_assembly(doc):
        from . import designlib
        if not designlib._saved(doc):
            return None         # components link saved files: the assembly is saved first
    if not App.GuiUp:
        return place(spec, doc, point)
    panel = Panel(spec, doc, point)
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    Gui.Control.showDialog(panel)
    return panel


# --------------------------------------------------------------------------- PropertyManager
if Gui is not None:
    class Panel:
        ""

        def __init__(self, spec, doc, point):
            self.spec, self.doc, self.point, self.made = dict(spec), doc, point, None
            self.form = QtWidgets.QWidget()
            self.form.setObjectName("SWPowerTransmission")
            self.form.setWindowTitle(KINDS[spec["kind"]][1])
            lay = QtWidgets.QVBoxLayout(self.form)
            box = QtWidgets.QGroupBox("Properties", self.form)
            lay.addWidget(box)
            f = QtWidgets.QFormLayout(box)
            self.w = {}
            inch = spec.get("std") == "ANSI Inch"

            def num(key, label, lo, hi, dec, value, suffix=""):
                s = QtWidgets.QDoubleSpinBox(box) if dec else QtWidgets.QSpinBox(box)
                s.setRange(lo, hi)
                if dec:
                    s.setDecimals(dec)
                s.setValue(value)
                if suffix:
                    s.setSuffix(suffix)
                s.setObjectName("SWPT_" + key)
                f.addRow(label, s)
                self.w[key] = s
                return s

            def combo(key, label, values, current):
                c = QtWidgets.QComboBox(box)
                c.addItems([str(v) for v in values])
                c.setCurrentText(str(current))
                c.setObjectName("SWPT_" + key)
                f.addRow(label, c)
                self.w[key] = c
                return c

            if spec["kind"] == "chain-sprocket":
                table = sprocket_table()
                c = combo("chain", "Chain", [table[k][3] for k in sorted(table)], table[spec["chain"]][3])
                c.setCurrentIndex(sorted(table).index(spec["chain"]))
                num("teeth", "Number of Teeth", 6, 200, 0, spec["teeth"])
            else:
                if inch:
                    num("dp", "Diametral Pitch", 1, 200, 2, 25.4 / spec["module"])
                else:
                    num("module", "Module", 0.2, 50, 3, spec["module"], " mm")
                num("teeth", "Number of Teeth", 6 if spec["kind"] == "spur-gear" else 12, 400, 0, spec["teeth"])
                combo("pressure", "Pressure Angle", ["%g" % a for a in PRESSURE_ANGLES], "%g" % spec["pressure"])
                num("face", "Face Width", 0.5, 1000, 3, spec["face"], " mm")
            if spec["kind"] != "internal-gear":
                combo("hub", "Hub Style", HUB_STYLES, spec["hub"])
                num("bore", "Nominal Shaft Diameter", 0, 1000, 3, spec["bore"], " mm")
                combo("keyway", "Keyway", KEYWAYS, spec["keyway"])
            self.info = QtWidgets.QLabel(self.form)
            self.info.setObjectName("SWPT_info")
            lay.addWidget(self.info)
            lay.addStretch(1)
            for s in self.w.values():
                (s.currentIndexChanged if isinstance(s, QtWidgets.QComboBox) else s.valueChanged).connect(
                    lambda *_: self._read())
            self._read()

        def _read(self):
            s, w = self.spec, self.w
            if s["kind"] == "chain-sprocket":
                s["chain"] = sorted(sprocket_table())[w["chain"].currentIndex()]
                s["teeth"] = int(w["teeth"].value())
            else:
                s["module"] = 25.4 / w["dp"].value() if "dp" in w else w["module"].value()
                s["teeth"] = int(w["teeth"].value())
                s["pressure"] = float(w["pressure"].currentText())
                s["face"] = w["face"].value()
            if "hub" in w:
                s["hub"] = w["hub"].currentText()
                s["bore"] = w["bore"].value()
                s["keyway"] = w["keyway"].currentText()
            self.info.setText("Pitch diameter: %.3f mm" % pitch_diameter(s))

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def accept(self):
            self._read()
            Gui.Control.closeDialog()
            try:
                self.made = place(self.spec, self.doc, self.point)
            except Exception as error:
                App.Console.PrintError("Toolbox: %s\n" % error)
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True
