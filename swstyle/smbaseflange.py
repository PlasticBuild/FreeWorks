# SPDX-License-Identifier: LGPL-2.1-or-later
""















from . import editobj

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
from PySide import QtCore, QtWidgets

from . import naming, paths, smflatten, smgauge

COMMAND = "SWStyle_SMBaseFlange"
TITLE = "Base Flange"
LABEL = "Base-Flange"
PARAMS = paths.PARAM_PATH + "/SheetMetal"
END_CONDITIONS = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Mid Plane")
END_CONDITIONS2 = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface")     # Direction 2: no Mid Plane
UP_TO = ("Up To Vertex", "Up To Surface", "Offset From Surface")

FROM = ("Sketch Plane", "Offset", "Vertex", "Surface/Face/Plane")
PICK_VERTEX = "Select a vertex to end the flange at."
PICK_FACE = "Select a face or plane to end the flange at."
ALLOWANCES = ("K-Factor", "Bend Table", "Bend Allowance", "Bend Deduction", "Bend Calculation")
RELIEFS = ("Rectangular", "Tear", "Obround")
NOT_YET = "Not available in FreeCAD yet."
PICK_MESSAGE = ("Select:\n1) A plane or a flat face on which to sketch the feature cross-section.\n"
                "2) An existing sketch.")
GROUP = "Sheet Metal"
# the values kept on the feature: name -> (property type, default)
SW_PROPS = {
    "SWBendAllowanceType": ("App::PropertyEnumeration", ALLOWANCES),
    "SWKFactor": ("App::PropertyFloat", 0.5),
    "SWBendAllowance": ("App::PropertyFloat", 0.0),
    "SWBendDeduction": ("App::PropertyFloat", 0.0),
    "SWBendTable": ("App::PropertyString", ""),
    "SWAutoRelief": ("App::PropertyEnumeration", RELIEFS),
    "SWUseReliefRatio": ("App::PropertyBool", True),
    "SWUseBendAllowance": ("App::PropertyBool", True),     # the Bend Allowance group's title box
    "SWUseAutoRelief": ("App::PropertyBool", True),        # the Auto Relief group's title box
    "SWReliefRatio": ("App::PropertyFloat", 0.5),
    "SWDirection2": ("App::PropertyBool", False),
    "SWDepth2": ("App::PropertyFloat", 10.0),
    "SWUseMaterial": ("App::PropertyBool", False),
    "SWUseGauge": ("App::PropertyBool", False),
    "SWGaugeTable": ("App::PropertyString", ""),
    "SWGaugeFile": ("App::PropertyString", ""),
    "SWGauge": ("App::PropertyString", ""),
    "SWOverrideThickness": ("App::PropertyBool", False),
    "SWOverrideRadius": ("App::PropertyBool", False),
    "SWEndCondition": ("App::PropertyEnumeration", END_CONDITIONS),
    "SWUpTo": ("App::PropertyLinkSubGlobal", None),
    "SWOffset": ("App::PropertyFloat", 0.0),
    "SWEndCondition2": ("App::PropertyEnumeration", END_CONDITIONS2),
    "SWUpTo2": ("App::PropertyLinkSubGlobal", None),
    "SWOffset2": ("App::PropertyFloat", 0.0),
    "SWFrom": ("App::PropertyEnumeration", FROM),
    "SWFromOffset": ("App::PropertyFloat", 0.0),
    "SWFromReverse": ("App::PropertyBool", False),
    "SWFromRef": ("App::PropertyLinkSubGlobal", None),
}


def _params():
    return App.ParamGet(PARAMS)


def _engine():
    import SheetMetalBaseCmd
    return SheetMetalBaseCmd


def is_base_flange(obj):
    proxy = getattr(obj, "Proxy", None)
    return proxy is not None and type(proxy).__name__ == "SMBaseBend"


def _is_open(sketch):
    try:
        wires = sketch.Shape.Wires
        return bool(wires) and not wires[0].isClosed()
    except Exception as _fw_err:
        _fw_log("smbaseflange.py:105", _fw_err)
        return True


def _body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def _active_body(doc):
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    return body


def _add_sw_props(obj):
    for name, (kind, default) in SW_PROPS.items():
        if name in obj.PropertiesList:
            continue
        obj.addProperty(kind, name, GROUP, "Sheet metal parameter")
        if default is not None:
            setattr(obj, name, list(default) if kind.endswith("Enumeration") else default)
    if getattr(obj, "MidPlane", False) and obj.SWEndCondition == "Blind":
        obj.SWEndCondition = "Mid Plane"


def _reference(link):
    """The vertex, face or plane an Up To end condition ends at, as a shape (or None)."""
    if not link:
        return None
    o, subs = link[0], [s for s in (link[1] or []) if s]
    try:
        if not subs:
            return o.Shape          # a datum or origin plane
        return o.Shape.getElement(subs[0])
    except Exception:
        return None


def inch_part(doc=None):
    """True when the part works in inches or feet (its own unit system, else FreeCAD's): sheet metal sizes
    then open on round inch values, otherwise on round millimetre values."""
    try:
        doc = doc if doc is not None else App.ActiveDocument
        schema = None
        if doc is not None and hasattr(doc, "UnitSystem"):
            schema = doc.getEnumerationsOfProperty("UnitSystem").index(doc.UnitSystem)
        if schema is None:
            schema = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("UserSchema", 0)
        return schema in (2, 3, 5, 7)       # US customary, Imperial decimal, Building US, Imperial for Civil Eng
    except Exception:
        return False


def reach(fp, link, offset=0.0):
    """Signed distance along the sketch normal from the sketch plane to the reference (Up To Vertex / Up To
    Surface), less the offset (Offset From Surface stops that far short of the face)."""
    ref = _reference(link)
    if ref is None:
        return None
    pl = fp.BendSketch.getGlobalPlacement()
    origin, normal = pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))
    if ref.ShapeType == "Vertex":
        d = (ref.Point - origin).dot(normal)
    else:
        face = ref.Faces[0] if ref.Faces else None
        surf = getattr(face, "Surface", None)
        if surf is not None and surf.TypeId in ("Part::GeomPlane",) and abs(face.normalAt(0, 0).dot(normal)) > 1 - 1e-9:
            d = (face.Vertexes[0].Point - origin).dot(normal) if face.Vertexes else (surf.Position - origin).dot(normal)
        else:                       # the nearest point of the face along the normal
            pts = [v.Point for v in ref.Vertexes] + [ref.CenterOfMass]
            ds = [(q - origin).dot(normal) for q in pts]
            d = min(ds, key=abs)
    if abs(offset) > 0:
        d = d - offset if d >= 0 else d + offset
    return d


def start_shift(fp):
    ""


    mode = getattr(fp, "SWFrom", "Sketch Plane")
    if mode == "Offset":
        d = float(getattr(fp, "SWFromOffset", 0.0))
        return -d if getattr(fp, "SWFromReverse", False) else d
    if mode in ("Vertex", "Surface/Face/Plane"):
        d = reach(fp, getattr(fp, "SWFromRef", None))
        return d if d is not None else 0.0
    return 0.0


def make(sketch):
    """A new Base Flange on the sketch, in its body, with the last values used. Opens a transaction
    the PropertyManager closes."""
    doc = sketch.Document
    body = _body_of(sketch) or _active_body(doc)
    engine = _engine()
    doc.openTransaction(TITLE)
    try:
        obj = doc.addObject("PartDesign::FeaturePython", "BaseBend")
        engine.SMBaseBend(obj, sketch)
        if App.GuiUp:
            engine.SMBaseViewProvider(obj.ViewObject)
        if body is not None:
            body.addObject(obj)
        _add_sw_props(obj)
        p = _params()
        obj.Thickness = p.GetFloat("Thickness", 2.0)
        obj.Radius = p.GetFloat("Radius", 1.0)
        obj.Length = p.GetFloat("Depth", 100.0)
        obj.SWBendAllowanceType = "K-Factor"
        obj.SWKFactor = p.GetFloat("KFactor", 0.5)
        obj.SWAutoRelief = p.GetString("AutoRelief", "Rectangular")
        obj.SWUseReliefRatio = p.GetBool("UseReliefRatio", True)
        obj.SWReliefRatio = p.GetFloat("ReliefRatio", 0.5)
        obj.SWUseGauge = p.GetBool("UseGauge", False)
        obj.SWGaugeTable = p.GetString("GaugeTable", "")
        obj.Label = naming.next_label(doc, LABEL)
        if _part_thickness(obj) is not None and not _is_open(sketch):

            # sheet's plane and thickness, merged into it (Merge result) or a body of its own
            obj.Label = naming.next_label(doc, "Tab")
        try:
            sketch.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:220", _fw_err)
        doc.recompute()
        if body is not None and smflatten.flat_pattern(body) is None:

            # inside the Base Flange's own transaction, so one Undo takes them all (and Cancel too)
            try:
                smflatten.ensure(body)
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:make-folders", _fw_err)
        return obj
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


def _merge_prop(obj):
    if "SWMergeResult" not in obj.PropertiesList:
        obj.addProperty("App::PropertyBool", "SWMergeResult", GROUP, "Tab / second Base Flange: merge with the part's sheet")
        obj.SWMergeResult = True
    return obj.SWMergeResult


def _with_part(fp):
    ""



    import Part
    base = getattr(fp, "BaseFeature", None)
    try:
        part = base.Shape if base is not None else None
    except Exception:
        part = None
    if part is None or part.isNull() or not part.Solids or fp.Shape.isNull():
        return
    new = fp.Shape
    if not _is_open(fp.BendSketch) and not fp.MidPlane:
        # a Tab on a face (or a plane through a face) of the sheet: in that face's thickness slab
        pl = fp.BendSketch.getGlobalPlacement()
        normal = pl.Rotation.multVec(App.Vector(0, 0, 1))
        slab = None
        for f in part.Faces:
            try:
                if f.Surface.TypeId == "Part::GeomPlane" and abs(abs(f.normalAt(0, 0).dot(normal)) - 1) < 1e-7 \
                        and abs((f.Vertexes[0].Point - pl.Base).dot(normal)) < 1e-6:
                    slab = -f.normalAt(0, 0)
                    break
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:258", _fw_err)
        if slab is not None:
            if fp.Reverse:
                slab = -slab
            tab = Part.Face(fp.BendSketch.Shape.Wires).extrude(slab * float(fp.Thickness.Value))
            if _merge_prop(fp):
                fp.Shape = part.fuse(tab).removeSplitter()
            else:
                fp.Shape = Part.makeCompound(list(part.Solids) + list(tab.Solids))
            return
    fp.Shape = Part.makeCompound(list(part.Solids) + list(new.Solids))


def _follow_k(obj, old, new):
    """The part's K-Factor changed: the flanges that use it (no Custom Bend Allowance: their K is the
    part's) follow it, so the flat pattern does not take them for custom ones."""
    if abs(old - new) < 1e-12:
        return
    body = _body_of(obj)
    for feature in (body.Group if body is not None else []):
        k = getattr(feature, "kfactor", None)
        if feature is not obj and k is not None and abs(float(k) - old) < 1e-9:
            try:
                feature.kfactor = new
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:283", _fw_err)


def _part_thickness(obj):
    """The thickness of a sheet metal part this Base Flange is added to (a second Base Flange or Tab)."""
    body = _body_of(obj)
    if body is None:
        return None
    for other in body.Group:
        if other is not obj and is_base_flange(other):
            return other.Thickness.Value
    return None


def _spin(name, value, low, high, suffix=" mm", decimals=2, step=1.0):
    spin = QtWidgets.QDoubleSpinBox()
    spin.setObjectName(name)
    spin.setRange(low, high)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setValue(value)
    return spin


def _box(title):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    QtWidgets.QFormLayout(box)
    return box


class Panel:
    """The Base Flange PropertyManager."""

    def __init__(self, obj, new):
        self.obj = obj
        self.new = new
        self.busy = True
        _add_sw_props(obj)
        sketch = obj.BendSketch
        self.open_profile = _is_open(sketch)

        start = self.start = _box("From")
        self.from_mode = QtWidgets.QComboBox()
        self.from_mode.setObjectName("SWSMFrom")
        self.from_mode.addItems(FROM)
        self.from_mode.setCurrentText(obj.SWFrom)
        self.from_mode.setToolTip("Where the flange starts")
        self.from_ref = self._ref_box("SWSMFromRef", obj.SWFromRef)
        self.from_offset = _spin("SWSMFromOffset", float(obj.SWFromOffset), 0.0, 100000.0)
        self.from_offset.setToolTip("Offset distance from the sketch plane")
        self.from_reverse = QtWidgets.QCheckBox("Reverse Direction")
        self.from_reverse.setObjectName("SWSMFromReverse")
        self.from_reverse.setChecked(bool(obj.SWFromReverse))
        start.layout().addRow(self.from_mode)
        start.layout().addRow(self.from_reverse)
        start.layout().addRow(self.from_offset)
        start.layout().addRow(self.from_ref)

        d1 = self.d1 = _box("Direction 1")
        f = d1.layout()
        self.end = QtWidgets.QComboBox()
        self.end.setObjectName("SWSMEnd")
        self.end.addItems(END_CONDITIONS)
        self.end.setCurrentText("Mid Plane" if obj.MidPlane else obj.SWEndCondition)
        self.up_to = self._ref_box("SWSMUpTo", obj.SWUpTo)
        self.offset = _spin("SWSMOffset", float(obj.SWOffset), 0.0, 100000.0)
        self.offset.setToolTip("Offset Distance")
        self.offset_label = QtWidgets.QLabel("Offset")
        self.reverse = QtWidgets.QCheckBox("Reverse Direction")
        from . import pmvalues
        self.reverse.setIcon(pmvalues.reverse_icon())
        self.reverse.setObjectName("SWSMReverse")
        self.reverse.setChecked(bool(obj.Reverse))
        self.depth = _spin("SWSMDepth", obj.Length.Value, 0.01, 100000.0)
        self.depth.setToolTip("Depth (D1)")
        f.addRow(self.end)
        f.addRow(self.reverse)
        f.addRow(self.up_to)
        f.addRow(self.offset_label, self.offset)
        self.depth_label = QtWidgets.QLabel("D1")
        f.addRow(self.depth_label, self.depth)

        d2 = _box("Direction 2")
        self.direction2 = QtWidgets.QCheckBox("Direction 2")
        self.direction2.setObjectName("SWSMDirection2")
        self.direction2.setChecked(bool(obj.SWDirection2))
        self.direction2.setToolTip("Extends the flange the other way too")
        self.end2 = QtWidgets.QComboBox()
        self.end2.setObjectName("SWSMEnd2")
        self.end2.addItems(END_CONDITIONS2)
        self.end2.setCurrentText(obj.SWEndCondition2)
        self.up_to2 = self._ref_box("SWSMUpTo2", obj.SWUpTo2)
        self.offset2 = _spin("SWSMOffset2", float(obj.SWOffset2), 0.0, 100000.0)
        self.offset2.setToolTip("Offset Distance")
        self.offset2_label = QtWidgets.QLabel("Offset")
        self.depth2 = _spin("SWSMDepth2", float(obj.SWDepth2), 0.01, 100000.0)
        self.depth2.setToolTip("Depth (D2)")
        self.depth2_label = QtWidgets.QLabel("D2")
        d2.layout().addRow(self.direction2)
        d2.layout().addRow(self.end2)
        d2.layout().addRow(self.up_to2)
        d2.layout().addRow(self.offset2_label, self.offset2)
        d2.layout().addRow(self.depth2_label, self.depth2)

        material = _box("Sheet Metal Parameters From Material")
        self.from_material = QtWidgets.QCheckBox("Use material sheet metal parameters")
        self.from_material.setObjectName("SWSMFromMaterial")
        self.from_material.setChecked(bool(obj.SWUseMaterial))
        self.from_material.setToolTip("Takes the gauge table from the part's material")
        material.layout().addRow(self.from_material)

        gauges = _box("Sheet Metal Gauges")
        f = gauges.layout()
        self.gauge = QtWidgets.QCheckBox("Use gauge table")
        self.gauge.setObjectName("SWSMGauge")
        self.gauge.setChecked(bool(obj.SWUseGauge))
        self.gauge.setToolTip("Takes the thickness, bend radius and K-Factor from a gauge table")
        if obj.SWGaugeFile and obj.SWGaugeTable not in smgauge.names():
            try:
                smgauge.load(obj.SWGaugeFile)
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:406", _fw_err)
        self.gauge_table = QtWidgets.QComboBox()
        self.gauge_table.setObjectName("SWSMGaugeTable")
        self.gauge_browse = QtWidgets.QPushButton("Browse...")
        self.gauge_browse.setObjectName("SWSMGaugeBrowse")
        self.gauge_browse.clicked.connect(self._browse_gauges)
        f.addRow(self.gauge)
        f.addRow(self.gauge_table)
        f.addRow(self.gauge_browse)
        self._fill_gauge_tables()

        params = _box("Sheet Metal Parameters")
        f = params.layout()
        self.thickness = _spin("SWSMThickness", obj.Thickness.Value, 0.01, 1000.0, decimals=3)
        self.thickness.setToolTip("Direction 1 Thickness")
        # a second Base Flange in a sheet metal part takes the part's thickness (greyed)
        self.part_thickness = _part_thickness(obj)
        if self.part_thickness is not None:
            self.thickness.setValue(self.part_thickness)
            obj.Thickness = self.part_thickness
            self.thickness.setEnabled(False)
        self.merge = QtWidgets.QCheckBox("Merge result")
        self.merge.setObjectName("SWSMMergeResult")
        self.merge.setToolTip("Merges the tab with the sheet; off, it is a body of its own")
        self.merge.setChecked(_merge_prop(obj) if self.part_thickness is not None else True)
        self.merge.setVisible(self.part_thickness is not None and not self.open_profile)
        f.addRow(self.merge)

        def merge_changed(on, obj=obj):
            obj.SWMergeResult = bool(on)
            obj.Document.recompute()
        self.merge.toggled.connect(merge_changed)
        self.flip = QtWidgets.QCheckBox("Reverse direction")
        from . import pmvalues
        self.flip.setIcon(pmvalues.reverse_icon())
        self.flip.setObjectName("SWSMThicknessReverse")
        self.flip.setToolTip("Puts the thickness on the other side of the sketch")
        self.flip.setChecked(obj.BendSide == "Inside" if self.open_profile else bool(obj.Reverse))
        self.symmetric = QtWidgets.QCheckBox("Symmetric")
        self.symmetric.setObjectName("SWSMSymmetric")
        self.symmetric.setToolTip("Puts half the thickness on each side of the sketch")
        self.symmetric.setChecked(not self.open_profile and bool(obj.MidPlane))
        self.radius = _spin("SWSMRadius", obj.Radius.Value, 0.0, 10000.0)
        self.radius.setToolTip("Bend radius (R1)")
        self.gauge_no = QtWidgets.QComboBox()
        self.gauge_no.setObjectName("SWSMGaugeNo")
        self.gauge_no.setToolTip("Gauge")
        self.override_t = QtWidgets.QCheckBox("Override thickness")
        self.override_t.setObjectName("SWSMOverrideThickness")
        self.override_t.setChecked(bool(obj.SWOverrideThickness))
        self.gauge_radius = QtWidgets.QComboBox()
        self.gauge_radius.setObjectName("SWSMGaugeRadius")
        self.gauge_radius.setToolTip("Bend radius from the gauge table")
        self.override_r = QtWidgets.QCheckBox("Override radius")
        self.override_r.setObjectName("SWSMOverrideRadius")
        self.override_r.setChecked(bool(obj.SWOverrideRadius))
        f.addRow(self.gauge_no)
        self.t1_label = QtWidgets.QLabel("T1")
        f.addRow(self.t1_label, self.thickness)
        f.addRow(self.override_t)
        f.addRow(self.flip)
        f.addRow(self.symmetric)
        self.radius_label = QtWidgets.QLabel("R1")
        f.addRow(self.gauge_radius)
        f.addRow(self.radius_label, self.radius)
        f.addRow(self.override_r)
        self._fill_gauges()

        allowance = _box("Bend Allowance")
        f = allowance.layout()
        self.allowance = QtWidgets.QComboBox()
        self.allowance.setObjectName("SWSMAllowance")
        self.allowance.addItems(ALLOWANCES)
        self.allowance.setCurrentText(obj.SWBendAllowanceType)
        self.kfactor = _spin("SWSMKFactor", obj.SWKFactor, 0.0, 1.0, suffix="", decimals=4, step=0.05)
        self.kfactor.setToolTip("K-Factor")
        self.ba = _spin("SWSMBendAllowance", obj.SWBendAllowance, 0.0, 10000.0, decimals=4)
        self.ba.setToolTip("Bend allowance")
        self.bd = _spin("SWSMBendDeduction", obj.SWBendDeduction, -10000.0, 10000.0, decimals=4)
        self.bd.setToolTip("Bend deduction")
        self.tables = QtWidgets.QComboBox()
        self.tables.setObjectName("SWSMBendTableList")
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("SWSMBendTableBrowse")
        self.browse.clicked.connect(self._browse)
        self._fill_tables()
        self.value_labels = {"K-Factor": QtWidgets.QLabel("K"), "Bend Allowance": QtWidgets.QLabel("BA"),
                             "Bend Deduction": QtWidgets.QLabel("BD")}

        self.use_allowance = QtWidgets.QCheckBox("Bend Allowance")
        self.use_allowance.setObjectName("SWSMUseAllowance")
        self.use_allowance.setChecked(bool(getattr(obj, "SWUseBendAllowance", True)))
        f.addRow(self.use_allowance)
        f.addRow(self.allowance)
        f.addRow(self.value_labels["K-Factor"], self.kfactor)
        f.addRow(self.value_labels["Bend Allowance"], self.ba)
        f.addRow(self.value_labels["Bend Deduction"], self.bd)
        f.addRow(self.tables)
        f.addRow(self.browse)

        relief = _box("Auto Relief")
        f = relief.layout()
        self.relief = QtWidgets.QComboBox()
        self.relief.setObjectName("SWSMRelief")
        self.relief.addItems(RELIEFS)
        self.relief.setCurrentText(obj.SWAutoRelief)
        self.ratio_on = QtWidgets.QCheckBox("Use relief ratio")
        self.ratio_on.setObjectName("SWSMReliefRatioOn")
        self.ratio_on.setChecked(bool(obj.SWUseReliefRatio))
        self.ratio = _spin("SWSMReliefRatio", obj.SWReliefRatio, 0.05, 2.0, suffix="", decimals=2, step=0.05)
        self.ratio.setToolTip("Relief ratio")
        self.use_relief = QtWidgets.QCheckBox("Auto Relief")
        self.use_relief.setObjectName("SWSMUseRelief")
        self.use_relief.setChecked(bool(getattr(obj, "SWUseAutoRelief", True)))
        f.addRow(self.use_relief)
        f.addRow(self.relief)
        f.addRow(self.ratio_on)
        f.addRow("Ratio", self.ratio)

        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("SWSMError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        from . import pickprompt
        pickprompt.style(self.error)     # look audit AI1: the start prompt in the yellow box
        self.error.hide()
        params.layout().addRow(self.error)

        if self.part_thickness is not None:

            boxes = ([start, d1] if self.open_profile else []) + [params]
        else:
            boxes = [material, gauges, params, allowance, relief]
            if self.open_profile:
                boxes[:0] = [start, d1, d2]
        boxes[0].setProperty("swstyle_pm_title", TITLE)
        boxes[0].setProperty("swstyle_pm_icon", "SheetMetal_AddBase")
        self.form = boxes
        self._all_boxes = [start, d1, d2, material, gauges, params, allowance, relief]   # unshown ones keep their fields alive

        # for a closed profile (a flat plate) too; a second Base Flange only bends when its profile is open
        shown = self.open_profile or self.part_thickness is None
        self.radius.setVisible(shown)
        self.radius_label.setVisible(shown)
        self.symmetric.setVisible(not self.open_profile)
        for w in (self.depth, self.thickness, self.radius, self.kfactor, self.ba, self.bd, self.ratio, self.depth2,
                  self.offset, self.offset2, self.from_offset):
            w.valueChanged.connect(self._changed)
        self.end2.currentIndexChanged.connect(self._changed)
        self.active_ref = self.up_to
        for w in (self.up_to, self.up_to2, self.from_ref):
            w.installEventFilter(self._refs)
        self.from_mode.currentIndexChanged.connect(self._from_changed)
        self.from_reverse.toggled.connect(self._changed)
        Gui.Selection.addObserver(self)
        for w in (self.gauge_table, self.gauge_no):
            w.currentIndexChanged.connect(self._gauge_changed)
        self.gauge_radius.currentIndexChanged.connect(self._changed)
        for w in (self.gauge, self.from_material, self.override_t, self.override_r):
            w.toggled.connect(self._gauge_changed)
        self.direction2.toggled.connect(self._changed)
        self.use_allowance.toggled.connect(self._use_toggled)
        self.use_relief.toggled.connect(self._use_toggled)
        self._use_toggled(changed=False)
        self.allowance.currentIndexChanged.connect(self._allowance_changed)
        for w in (self.end, self.relief, self.tables):
            w.currentIndexChanged.connect(self._changed)
        for w in (self.reverse, self.flip, self.symmetric, self.ratio_on):
            w.toggled.connect(self._changed)
        self._show()
        self.busy = False

    # ------------------------------------------------------------ Up To end conditions
    def _ref_box(self, name, link):
        ""
        if not hasattr(self, "_refs"):
            self._refs = _RefFocus(self)
        w = QtWidgets.QListWidget()
        w.setObjectName(name)
        w.setMaximumHeight(QtWidgets.QApplication.fontMetrics().height() * 2 + 8)
        w.setStyleSheet("QListWidget { background: #ffd6ec; }")
        self._show_ref(w, link)
        return w

    def _show_ref(self, w, link):
        w.clear()
        if link:
            subs = [s for s in (link[1] or []) if s]
            w.addItem("%s@%s" % (subs[0].replace("Face", "Face<").replace("Vertex", "Vertex<") + ">", link[0].Label)
                      if subs else link[0].Label)

    def addSelection(self, doc, name, sub, point):
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked(doc, name, sub), self, "end")

    def _from_changed(self, *args):
        if self.from_mode.currentText() in ("Vertex", "Surface/Face/Plane"):
            self.active_ref = self.from_ref      # the next pick says where the flange starts
        self._changed()

    def _picked_from(self, doc_name, name, sub):
        """A pick for From: a vertex (Vertex) or a face / plane (Surface/Face/Plane)."""
        o = App.getDocument(doc_name).getObject(name)
        if o is None or o is self.obj:
            return False
        vertex = self.from_mode.currentText() == "Vertex"
        plane = not sub and o.TypeId in ("App::Plane", "PartDesign::Plane")
        if (vertex and not sub.startswith("Vertex")) or (not vertex and not (sub.startswith("Face") or plane)):
            return False
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:599", _fw_err)
        link = (o, [sub] if sub else [])
        self.obj.SWFromRef = link
        self._show_ref(self.from_ref, link)
        self.active_ref = self.up_to
        self._changed()
        return True

    def _picked(self, doc_name, name, sub):
        from_live = self.open_profile and self.from_mode.currentText() in ("Vertex", "Surface/Face/Plane")
        if from_live and (self.active_ref is self.from_ref or self.from_ref.count() == 0):
            if self._picked_from(doc_name, name, sub):
                return
        boxes = [(self.up_to, self.end)] + ([(self.up_to2, self.end2)] if self.direction2.isChecked() else [])
        live = [b for b in boxes if b[1].currentText() in UP_TO]
        if not live:
            return
        box, end = next((b for b in live if b[0] is self.active_ref), live[0])
        o = App.getDocument(doc_name).getObject(name)
        if o is None or o is self.obj:
            return
        vertex = end.currentText() == "Up To Vertex"
        plane = not sub and o.TypeId in ("App::Plane", "PartDesign::Plane")
        if (vertex and not sub.startswith("Vertex")) or (not vertex and not (sub.startswith("Face") or plane)):
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:627", _fw_err)
        link = (o, [sub] if sub else [])
        if box is self.up_to:
            self.obj.SWUpTo = link
        else:
            self.obj.SWUpTo2 = link
        self._show_ref(box, link)
        if box is self.up_to and len(live) > 1:
            self.active_ref = self.up_to2   # the next pick goes to Direction 2
        self._changed()

    def _show(self):
        mode = self.from_mode.currentText()
        self.from_offset.setVisible(mode == "Offset")
        self.from_reverse.setVisible(mode == "Offset")
        self.from_ref.setVisible(mode in ("Vertex", "Surface/Face/Plane"))
        self.from_ref.setToolTip("Vertex" if mode == "Vertex" else "Face/Plane")
        end = self.end.currentText()
        self.reverse.setVisible(end in ("Blind",) + UP_TO)
        self.up_to.setVisible(end in UP_TO)
        self.up_to.setToolTip("Vertex" if end == "Up To Vertex" else "Face/Plane")
        for w in (self.offset, self.offset_label):
            w.setVisible(end == "Offset From Surface")
        for w in (self.depth, self.depth_label):
            w.setVisible(end not in UP_TO)
        two = self.direction2.isChecked() and end != "Mid Plane"
        self.direction2.setEnabled(end != "Mid Plane")
        end2 = self.end2.currentText()
        self.end2.setVisible(two)
        for w in (self.depth2, self.depth2_label):
            w.setVisible(two and end2 not in UP_TO)
        self.up_to2.setVisible(two and end2 in UP_TO)
        self.up_to2.setToolTip("Vertex" if end2 == "Up To Vertex" else "Face/Plane")
        for w in (self.offset2, self.offset2_label):
            w.setVisible(two and end2 == "Offset From Surface")
        on = self.gauge.isChecked() or self.from_material.isChecked()
        self.gauge.setEnabled(not self.from_material.isChecked())
        self.gauge_table.setVisible(on)
        self.gauge_table.setEnabled(not self.from_material.isChecked())
        self.gauge_browse.setVisible(on and not self.from_material.isChecked())
        self.gauge_no.setVisible(on)
        locked = self.part_thickness is not None
        self.override_t.setVisible(on and not locked)
        self.thickness.setEnabled(not locked and (not on or self.override_t.isChecked()))
        # a second Base Flange (Tab) takes the part's thickness: no greyed thickness box (a dead control)
        self.thickness.setVisible(not locked)
        self.t1_label.setVisible(not locked)
        self.gauge_radius.setVisible(on and (self.open_profile or self.part_thickness is None))
        self.override_r.setVisible(on and self.open_profile)
        self.radius.setEnabled(not on or self.override_r.isChecked())
        if not self.open_profile:
            self.flip.setEnabled(not self.symmetric.isChecked())
        self.ratio.setEnabled(self.ratio_on.isChecked() and self.use_relief.isChecked())
        kind = self.allowance.currentText()
        for name, w in (("K-Factor", self.kfactor), ("Bend Allowance", self.ba), ("Bend Deduction", self.bd)):
            w.setVisible(kind == name)
            self.value_labels[name].setVisible(kind == name)
        self.tables.setVisible(kind in ("Bend Table", "Bend Calculation"))
        self.browse.setVisible(kind in ("Bend Table", "Bend Calculation"))

    # -------------------------------------------------------------- gauges
    def _table_name(self):
        if self.from_material.isChecked():
            return smgauge.table_for_material(smgauge.material_of(self.obj)) or ""
        return self.gauge_table.currentText()

    def _fill_gauge_tables(self):
        self.gauge_table.blockSignals(True)
        self.gauge_table.clear()
        self.gauge_table.addItems(smgauge.names())
        current = self.obj.SWGaugeTable if self.obj.SWGaugeTable in smgauge.names() else smgauge.names()[0]
        self.gauge_table.setCurrentText(current)
        self.gauge_table.blockSignals(False)

    def _fill_gauges(self):
        """The table's gauges, and the picked gauge's radii."""
        name = self._table_name()
        if self.from_material.isChecked() and name:
            self.gauge_table.blockSignals(True)
            self.gauge_table.setCurrentText(name)
            self.gauge_table.blockSignals(False)
        self.gauge_no.blockSignals(True)
        self.gauge_no.clear()
        self.gauge_no.addItems(smgauge.gauges(name))
        g = self.obj.SWGauge if self.obj.SWGauge in smgauge.gauges(name) else smgauge.nearest(name, self.thickness.value())
        self.gauge_no.setCurrentText(g)
        self.gauge_no.blockSignals(False)
        row = smgauge.row(name, self.gauge_no.currentText())
        self.gauge_radius.blockSignals(True)
        self.gauge_radius.clear()
        for r in (row or {}).get("radii", []):
            self.gauge_radius.addItem("%g mm" % r, r)
        if row:
            i = self.gauge_radius.findData(self.radius.value())
            self.gauge_radius.setCurrentIndex(i if i >= 0 else 0)
        self.gauge_radius.blockSignals(False)

    def _browse_gauges(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), "Open Gauge Table", "", "Gauge tables (*.csv)")
        if path:
            self.add_gauge_table(path)

    def add_gauge_table(self, path):
        """Adds a gauge table from a CSV file and picks it (Browse...)."""
        try:
            name = smgauge.load(path)
        except Exception as e:
            self.error.setText(str(e))
            self.error.setVisible(True)
            return None
        self.obj.SWGaugeFile = path
        self.obj.SWGaugeTable = name
        self._fill_gauge_tables()
        self._gauge_changed()
        return name

    def _gauge_changed(self, *args):
        if self.busy:
            return
        self.busy = True
        self.obj.SWGaugeTable = self.gauge_table.currentText()
        if self.gauge_no.currentText() in smgauge.gauges(self._table_name()):
            self.obj.SWGauge = self.gauge_no.currentText()      # else the gauge nearest the thickness
        self._fill_gauges()
        self.busy = False
        self._changed()

    def _apply_gauge(self):
        """The thickness, radius and K-Factor the gauge table gives (unless overridden)."""
        on = self.gauge.isChecked() or self.from_material.isChecked()
        if not on:
            return ""
        name = self._table_name()
        if not name:
            return ("The part's material has no sheet metal parameters: give the part Steel, Stainless Steel "
                    "or Aluminum (Edit Material), or use a gauge table.")
        row = smgauge.row(name, self.gauge_no.currentText())
        if row is None:
            return "Pick a gauge."
        self.busy = True
        if not self.override_t.isChecked() and self.part_thickness is None:
            self.thickness.setValue(row["thickness"])
        if not self.override_r.isChecked() and self.gauge_radius.currentData() is not None:
            self.radius.setValue(float(self.gauge_radius.currentData()))
        if self.allowance.currentText() == "K-Factor":
            self.kfactor.setValue(row["k"])
        self.busy = False
        return ""

    def _fill_tables(self):
        """The part's bend tables, or its bend calculation tables for Bend Calculation."""
        from . import smbendtable
        calc = self.allowance.currentText() == "Bend Calculation"
        self.tables.blockSignals(True)
        self.tables.clear()
        for t in smbendtable.tables(self.obj.Document):
            if smbendtable.is_calculation(t) == calc:
                self.tables.addItem(t.Label, t.Name)
        i = self.tables.findData(self.obj.SWBendTable)
        self.tables.setCurrentIndex(i if i >= 0 else 0)
        self.tables.blockSignals(False)

    def _browse(self):
        from . import smbendtable
        calc = self.allowance.currentText() == "Bend Calculation"
        start = smbendtable.sample_calculation_path() if calc else ""
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            Gui.getMainWindow(), "Open Bend Calculation Table" if calc else "Open Bend Table", start,
            "Bend tables (*.xlsx *.csv *.xls)")
        if path:
            self.add_table(path)

    def add_table(self, path):
        """Adds the table from a file and picks it (Browse...)."""
        from . import smbendtable
        try:
            table = smbendtable.from_file(self.obj.Document, path)
        except Exception as e:
            self.error.setText(str(e))
            self.error.setVisible(True)
            return None
        self.obj.SWBendTable = table.Name
        self._fill_tables()
        self._changed()
        return table

    def _use_toggled(self, *args, changed=True):
        ""

        p = _params()
        self.busy = True
        if not self.use_allowance.isChecked():
            self.allowance.setCurrentText("K-Factor")
            self.kfactor.setValue(p.GetFloat("KFactor", 0.5))
        if not self.use_relief.isChecked():
            self.relief.setCurrentText(p.GetString("AutoRelief", "Rectangular"))
            self.ratio_on.setChecked(p.GetBool("UseReliefRatio", True))
            self.ratio.setValue(p.GetFloat("ReliefRatio", 0.5))
        self.busy = False
        for w in (self.allowance, self.kfactor, self.ba, self.bd, self.tables, self.browse):
            w.setEnabled(self.use_allowance.isChecked())
        for w in (self.relief, self.ratio_on, self.ratio):
            w.setEnabled(self.use_relief.isChecked())
        for lab in self.value_labels.values():
            lab.setEnabled(self.use_allowance.isChecked())
        if changed:
            self._changed()

    def _allowance_changed(self, *args):
        """A newly picked Bend Allowance or Bend Deduction starts from what the K-Factor gives at 90 deg."""
        if self.busy:
            return
        from . import smbendtable
        self._fill_tables()
        kind = self.allowance.currentText()
        t, r, k = self.thickness.value(), self.radius.value(), self.kfactor.value()
        ba = smbendtable.allowance_from_k(k, 90.0, r, t)
        self.busy = True
        if kind == "Bend Allowance" and self.ba.value() == 0:
            self.ba.setValue(round(ba, 4))
        if kind == "Bend Deduction" and self.bd.value() == 0:
            self.bd.setValue(round(smbendtable.deduction_from_allowance(ba, 90.0, r, t), 4))
        self.busy = False
        self._changed()

    def _changed(self, *args):
        if self.busy:
            return
        self._show()
        gauge_problem = self._apply_gauge()
        obj = self.obj
        obj.SWUseMaterial = self.from_material.isChecked()
        obj.SWUseGauge = self.gauge.isChecked()
        obj.SWGauge = self.gauge_no.currentText()
        obj.SWOverrideThickness = self.override_t.isChecked()
        obj.SWOverrideRadius = self.override_r.isChecked()
        obj.SWDirection2 = self.direction2.isChecked() and self.open_profile and self.end.currentText() != "Mid Plane"
        obj.SWDepth2 = self.depth2.value()
        obj.SWEndCondition = self.end.currentText()
        obj.SWEndCondition2 = self.end2.currentText()
        obj.SWOffset = self.offset.value()
        obj.SWOffset2 = self.offset2.value()
        obj.SWFrom = self.from_mode.currentText()
        obj.SWFromOffset = self.from_offset.value()
        obj.SWFromReverse = self.from_reverse.isChecked()
        if self.open_profile:
            obj.MidPlane = self.end.currentText() == "Mid Plane"
            obj.Reverse = self.reverse.isChecked() and not obj.MidPlane
            obj.Length = self.depth.value() + (self.depth2.value() if obj.SWDirection2 else 0.0)
            obj.BendSide = "Inside" if self.flip.isChecked() else "Outside"
        else:
            obj.MidPlane = self.symmetric.isChecked()
            obj.Reverse = self.flip.isChecked() and not obj.MidPlane
        obj.Thickness = self.thickness.value()
        if self.open_profile or self.part_thickness is None:
            obj.Radius = self.radius.value()
        _follow_k(obj, float(obj.SWKFactor), self.kfactor.value())
        obj.SWKFactor = self.kfactor.value()
        obj.SWBendAllowanceType = self.allowance.currentText()
        obj.SWBendAllowance = self.ba.value()
        obj.SWBendDeduction = self.bd.value()
        obj.SWBendTable = self.tables.currentData() or ""
        obj.SWAutoRelief = self.relief.currentText()
        obj.SWUseReliefRatio = self.ratio_on.isChecked()
        obj.SWReliefRatio = self.ratio.value()
        obj.SWUseBendAllowance = self.use_allowance.isChecked()
        obj.SWUseAutoRelief = self.use_relief.isChecked()
        obj.Document.recompute()
        self.busy = True
        if obj.SWEndCondition in UP_TO and getattr(obj, "SWDepth1", None) is not None:
            self.depth.setValue(obj.SWDepth1)
        if obj.SWDirection2 and obj.SWEndCondition2 in UP_TO:
            self.depth2.setValue(float(obj.SWDepth2))
        self.busy = False
        self.gauge_problem = gauge_problem
        self._report()

    def _report(self):
        invalid = "Invalid" in self.obj.State
        text = self.obj.getStatusString() if invalid else getattr(self, "gauge_problem", "")
        if not invalid and self.open_profile:
            for end, link in ((self.obj.SWEndCondition, self.obj.SWUpTo),
                              (self.obj.SWEndCondition2 if self.obj.SWDirection2 else "Blind", self.obj.SWUpTo2)):
                if end in UP_TO and not link:
                    text = text or (PICK_VERTEX if end == "Up To Vertex" else PICK_FACE)
        if not invalid:
            from . import smbendtable
            if self.obj.SWBendAllowanceType in ("Bend Table", "Bend Calculation") and not self.obj.SWBendTable:
                text = ("Select a bend calculation table, or Browse... for one (a sample is in Sheetmetal Bend "
                        "Tables)." if self.obj.SWBendAllowanceType == "Bend Calculation"
                        else "Select a bend table, or Browse... for one.")
            else:
                try:
                    smbendtable.k_of(self.obj, self.obj.Shape)
                except ValueError as e:
                    text = str(e)
        self.error.setText(text)
        self.error.setVisible(bool(text))
        return not text

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:907", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:913", _fw_err)

    def accept(self):
        self._changed()
        if not self._report():
            return False
        doc = self.obj.Document
        body = _body_of(self.obj)
        if self.new and body is not None:
            smflatten.ensure(body)
        doc.commitTransaction()
        p = _params()
        p.SetFloat("Thickness", self.thickness.value())
        p.SetFloat("KFactor", self.kfactor.value())
        p.SetString("AutoRelief", self.relief.currentText())
        p.SetBool("UseReliefRatio", self.ratio_on.isChecked())
        p.SetFloat("ReliefRatio", self.ratio.value())
        if self.open_profile or self.part_thickness is None:
            p.SetFloat("Radius", self.radius.value())
        if self.open_profile:
            p.SetFloat("Depth", self.depth.value())
        p.SetBool("UseGauge", self.gauge.isChecked())
        p.SetString("GaugeTable", self.gauge_table.currentText())
        try:
            self.obj.BendSketch.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:938", _fw_err)
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        sketch = self.obj.BendSketch if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if sketch is not None:
            try:
                sketch.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:951", _fw_err)
        self._close()
        return True


class _RefFocus(QtCore.QObject):
    """Clicking an Up To box makes it the one the next pick goes to."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, w, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
                self.panel.active_ref = w
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:970", _fw_err)
        return False


def edit_panel(obj):
    return Panel(obj, new=False)


def open_on(sketch):
    obj = make(sketch)
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(Panel(obj, new=True))
    return obj


# ------------------------------------------------------------------------- starting
_wait = {}


def _watch():
    """After the plane pick: the sketch opened there; when it closes, the Base Flange opens on it."""
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    sketch = editobj.of(edit) if edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject" else None
    if sketch is not None:
        _wait["sketch"] = (sketch.Document.Name, sketch.Name)
        _wait["idle"] = 0
    elif "sketch" in _wait:
        doc_name, name = _wait.pop("sketch")
        then = _wait.get("then") or open_on
        _wait.clear()
        doc = App.getDocument(doc_name) if doc_name in App.listDocuments() else None
        sketch = doc.getObject(name) if doc is not None else None
        if sketch is not None and sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: then(sketch))
        return
    else:
        picking = False
        try:
            picking = bool(Gui.Control.activeDialog())
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:1011", _fw_err)
        _wait["idle"] = 0 if picking else _wait.get("idle", 0) + 1
        if _wait["idle"] > 8:       # the pick was cancelled
            _wait.clear()
            return
    QtCore.QTimer.singleShot(250, _watch)


def _take_sketches(picker, then):
    ""

    own = picker.picked

    def picked():
        try:
            sel = Gui.Selection.getSelectionEx()
            if sel and not picker.done:
                entry = sel[-1]
                subs = [s for s in entry.SubElementNames if s]
                obj = entry.Object
                if obj.TypeId == "Sketcher::SketchObject" and obj.Geometry and \
                        not (subs and subs[-1].startswith("Face")):
                    picker._finish(lambda: then(obj))
                    return
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:take-sketch", _fw_err)
        own()
    picker.picked = picked


def _pick_plane(doc, then=None, title=TITLE, icon="SheetMetal_AddBase", message=PICK_MESSAGE):
    """Asks for a plane or face, sketches there and calls then(sketch) when the sketch closes."""
    from . import sketchstart
    body = _active_body(doc)
    if body is None:
        body = doc.addObject("PartDesign::Body", "Body")
        try:
            Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:1028", _fw_err)

    keep = False
    try:
        sel = Gui.Selection.getSelectionEx()
        if len(sel) == 1:
            subs = [s for s in sel[0].SubElementNames if s]
            obj = sel[0].Object
            keep = (not subs and obj.TypeId in sketchstart.PLANES) or \
                (len(subs) == 1 and subs[0].startswith("Face") and sketchstart._is_flat(obj, subs[0]))
    except Exception as _fw_err:
        _fw_log("smbaseflange.py:pick_plane", _fw_err)
    if not keep:
        Gui.Selection.clearSelection()
    picker = sketchstart.PlanePicker(body, title=title, icon=icon, message=message)
    _take_sketches(picker, then or open_on)
    Gui.Control.showDialog(picker)
    if keep:
        QtCore.QTimer.singleShot(0, picker.picked)
    _wait.clear()
    _wait["idle"] = 0
    if then is not None:
        _wait["then"] = then
    QtCore.QTimer.singleShot(250, _watch)


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    gdoc = Gui.ActiveDocument
    edit = gdoc.getInEdit() if gdoc is not None else None
    if edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject":
        sketch = editobj.of(edit)
        Gui.runCommand("Sketcher_LeaveSketch", 0)
        if sketch.Geometry:
            QtCore.QTimer.singleShot(0, lambda: open_on(sketch))
        else:
            QtCore.QTimer.singleShot(0, lambda: _pick_plane(doc))
        return
    picked = [s.Object for s in Gui.Selection.getSelectionEx()]
    sketches = [o for o in picked if o.TypeId == "Sketcher::SketchObject"]
    if len(sketches) == 1 and len(picked) == 1:
        open_on(sketches[0])
        return
    _pick_plane(doc)


class Command:
    def GetResources(self):
        try:
            import SheetMetalTools, os
            pixmap = os.path.join(SheetMetalTools.icons_path, "SheetMetal_AddBase.svg")
        except Exception:
            pixmap = ""
        return {"Pixmap": pixmap, "MenuText": "Base Flange/Tab",
                "ToolTip": "Makes the first sheet metal body from a sketch, or adds a tab to it."}

    def IsActive(self):
        if App.ActiveDocument is None or smflatten.blocked():
            return False
        try:
            dialog = Gui.Control.activeDialog()
            gdoc = Gui.ActiveDocument
            edit = gdoc.getInEdit() if gdoc is not None else None
            in_sketch = edit is not None and editobj.type_id(edit) == "Sketcher::SketchObject"
            return not dialog or in_sketch
        except Exception:
            return True

    def Activated(self):
        start()


_patched = {}


def _patch_execute():
    """Direction 2: the engine's wall runs D1 + D2 long; it is moved back by D2."""
    base = _engine().SMBaseBend
    if "execute" in _patched:
        return
    _patched["execute"] = base.execute

    def execute(self, fp, original=_patched["execute"]):
        _up_to(fp)
        original(self, fp)
        normal = fp.BendSketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        d0 = start_shift(fp) if "SWFrom" in fp.PropertiesList else 0.0
        if abs(d0) > 1e-9:
            m = App.Matrix()
            m.move(normal * d0)
            fp.Shape = fp.Shape.transformGeometry(m)
        if not getattr(fp, "SWDirection2", False) or fp.MidPlane or not _is_open(fp.BendSketch):
            _with_part(fp)
            return
        d2 = float(getattr(fp, "SWDepth2", 0.0))
        m = App.Matrix()
        m.move(normal * (d2 if fp.Reverse else -d2))
        fp.Shape = fp.Shape.transformGeometry(m)      # in the geometry: a PartDesign feature resets placements
        _with_part(fp)
    base.execute = execute


def _up_to(fp):
    """Up To Vertex / Up To Surface / Offset From Surface: D1 (and D2) from the picked references, before the
    engine builds the wall. Reverse follows the side the reference is on."""
    if not _is_open(fp.BendSketch) or fp.MidPlane or "SWEndCondition" not in fp.PropertiesList:
        return
    d1 = float(fp.Length.Value) - (float(fp.SWDepth2) if fp.SWDirection2 else 0.0)
    changed = False
    d0 = start_shift(fp) if "SWFrom" in fp.PropertiesList else 0.0
    if fp.SWEndCondition in UP_TO:
        d = reach(fp, fp.SWUpTo, fp.SWOffset if fp.SWEndCondition == "Offset From Surface" else 0.0)
        if d is not None:
            d = d - d0              # measured from where the flange starts
        if d is not None and abs(d) > 1e-6:
            if bool(fp.Reverse) != (d < 0):
                fp.Reverse = d < 0
            d1 = abs(d)
            changed = True
    if fp.SWDirection2 and fp.SWEndCondition2 in UP_TO:
        d = reach(fp, fp.SWUpTo2, fp.SWOffset2 if fp.SWEndCondition2 == "Offset From Surface" else 0.0)
        if d is not None and abs(d) > 1e-6:
            if abs(float(fp.SWDepth2) - abs(d)) > 1e-9:
                fp.SWDepth2 = abs(d)
            changed = True
    if "SWDepth1" not in fp.PropertiesList:
        fp.addProperty("App::PropertyFloat", "SWDepth1", GROUP, "Direction 1 depth (an Up To end condition's readout)")
        fp.setEditorMode("SWDepth1", 1)
    fp.SWDepth1 = d1
    if changed:
        total = d1 + (float(fp.SWDepth2) if fp.SWDirection2 else 0.0)
        if abs(float(fp.Length.Value) - total) > 1e-9:
            fp.Length = total


class _KWatch:
    ""

    def __init__(self):
        self.old = {}

    def slotBeforeChangeObject(self, obj, prop):
        if prop == "SWKFactor":
            try:
                self.old[(obj.Document.Name, obj.Name)] = float(obj.SWKFactor)
            except Exception as _fw_err:
                _fw_log("smbaseflange.py:1160", _fw_err)

    def slotChangedObject(self, obj, prop):
        if prop != "SWKFactor":
            return
        try:
            old = self.old.pop((obj.Document.Name, obj.Name), None)
            if old is not None and "Thickness" in obj.PropertiesList:
                _follow_k(obj, old, float(obj.SWKFactor))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: K-Factor follow: %s\n" % error)


    def slotCreatedObject(self, obj):
        ""


        try:
            doc = obj.Document
            if getattr(doc, "Restoring", False) or getattr(doc, "Transacting", False) \
                    or obj.TypeId != "PartDesign::FeaturePython":       # not on open, Undo or Redo
                return
            from PySide import QtCore
            names = (doc.Name, obj.Name)
            QtCore.QTimer.singleShot(300, lambda: _first_sheet(*names))
        except Exception as _fw_err:
            _fw_log("smbaseflange.py:created", _fw_err)


def _first_sheet(docname, name):
    try:
        doc = App.getDocument(docname)
        obj = doc.getObject(name) if doc is not None else None
        if obj is None or not is_base_flange(obj):
            return
        body = _body_of(obj)
        if body is None:
            return
        if smflatten.flat_pattern(body) is not None:
            return
        # a Base Flange made by another command (the SheetMetal workbench's own): its transaction is closed
        # by now, so the folders get a step of their own; one Undo takes them, the next the flange
        own = not doc.HasPendingTransaction
        if own:
            doc.openTransaction("Sheet Metal Folders")
        try:
            if obj.Label.startswith("BaseBend"):
                obj.Label = naming.next_label(doc, LABEL)
            smflatten.ensure(body)
        finally:
            if own:
                doc.commitTransaction()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sheet metal folders: %s\n" % error)


_K_WATCH = []


def register():
    """Adds the command and has SheetMetal's base wall open this PropertyManager when edited
    (double-click, Edit Feature)."""
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    if not _K_WATCH:
        _K_WATCH.append(_KWatch())
        App.addDocumentObserver(_K_WATCH[0])
    _patch_execute()
    view = _engine().SMBaseViewProvider
    if "setEdit" not in _patched:
        _patched["setEdit"] = view.setEdit

        def setEdit(self, vobj, mode=0, original=_patched["setEdit"]):
            if mode != 0 or not paths.params().GetBool("Enabled", True):
                return original(self, vobj, mode)
            obj = vobj.Object
            obj.Document.openTransaction("Edit " + TITLE)
            try:
                Gui.Control.showDialog(edit_panel(obj))
            except BaseException:
                try:
                    obj.Document.abortTransaction()
                except Exception:
                    pass
                raise
            return True
        view.setEdit = setEdit
