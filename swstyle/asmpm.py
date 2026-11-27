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
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac
from . import selguard
from . import asmcam
from . import asmcoupler
from . import asmpath
from . import paths

Qt = QtCore.Qt
PICK_STYLE = ("QListWidget { background: #cfe6fb; color: #000000; border: 1px solid #5a9bd5;"
              " border-left: 4px solid #3399ff; }"
              " QListWidget::item:selected, QListWidget::item:selected:!active"
              " { background: #3399ff; color: #ffffff; }")
BEGIN_MESSAGE = ("Select a component to insert, then place it in the graphics area or hit OK to "
                 "locate it at the origin.")
INSERT_MESSAGE = ("Select a part or assembly to insert and then place the component in the graphics "
                  "area. Use the push pin to insert multiple copies of the same or different components.\n\n"
                  "Hit OK button to insert a component at the origin.")
START_PARAM = "AssemblyStartInsert"
PREVIEW_PARAM = "AssemblyGraphicsPreview"
ROTATE_BAR_PARAM = "AssemblyInsertRotateBar"
POPUP_PARAM = "MateShowPopup"
MATE_PREVIEW_PARAM = "MateShowPreview"
FADE_PARAM = "MateFadeFirstOn"
FADE_LEVEL = 0.6
ICONS = {
    "Coincident": ("ASSEMBLIES_MATE_COINCIDENT", "Assembly_CreateJointDistance"),
    "Parallel": ("ASSEMBLIES_MATE_PARALLEL", "Assembly_CreateJointParallel"),
    "Perpendicular": ("ASSEMBLIES_MATE_PERPENDICULAR", "Assembly_CreateJointPerpendicular"),
    "Tangent": ("ASSEMBLIES_MATE_TANGENT", "Assembly_CreateJointDistance"),
    "Concentric": ("ASSEMBLIES_MATE_CONCENTRIC", "Assembly_CreateJointCylindrical"),
    "Lock": ("ASSEMBLIES_MATE_LOCK", "Assembly_CreateJointFixed"),
    "Distance": ("ASSEMBLIES_MATE_DISTANCE", "Assembly_CreateJointDistance"),
    "Angle": ("ASSEMBLIES_MATE_ANGLE", "Assembly_CreateJointAngle"),
    "Gear": ("ASSEMBLIES_MATE_GEAR", "Assembly_CreateJointGears"),
    "Hinge": ("ASSEMBLIES_MATE_HINGE", "Assembly_CreateJointRevolute"),
    "Rack Pinion": ("ASSEMBLIES_MATE_RACK_PINION", "Assembly_CreateJointRackPinion"),
    "Screw": ("ASSEMBLIES_MATE_SCREW", "Assembly_CreateJointScrew"),
    "Universal Joint": ("ASSEMBLIES_MATE_UNIVERSAL_JOINT", "Assembly_CreateJointBall"),
    "Slot": ("ASSEMBLIES_MATE_SLOT", "Assembly_CreateJointSlider"),
    "Cam": ("ASSEMBLIES_MATE_CAM", "Assembly_CreateJointDistance"),
    "Profile Center": ("ASSEMBLIES_MATE_PROFILE_CENTER", "Assembly_CreateJointFixed"),
    "Width": ("ASSEMBLIES_MATE_WIDTH", "Assembly_CreateJointDistance"),
    "Path Mate": ("ASSEMBLIES_MATE_PATH", "Assembly_CreateJointBall"),
    "Linear/Linear Coupler": ("ASSEMBLIES_MATE_LINEAR_COUPLER", "Assembly_CreateJointSlider"),
    "Symmetric": ("ASSEMBLIES_MATE_SYMMETRIC", "Assembly_CreateJointDistance"),
    "Distance Range": ("ASSEMBLIES_MATE_DISTANCE", "Assembly_CreateJointDistance"),
    "Angle Range": ("ASSEMBLIES_MATE_ANGLE", "Assembly_CreateJointAngle"),
    "InPlace": ("ASSEMBLIES_MATE_INPLACE", "Assembly_CreateJointFixed"),
}
WIDTH_MODES = (("Centered", "centered"), ("Free", "free"), ("Dimension", "dimension"), ("Percent", "percent"))

COUPLER_MODES = {
    "Rack Pinion": (("diameter", "Pinion pitch diameter:", "mm"), ("travel", "Rack travel/revolution:", "mm")),
    "Screw": (("revs", "Revolutions/mm:", ""), ("distance", "Distance/revolution:", "mm")),
}
COUPLER_FIRST = {"Rack Pinion": "diameter", "Screw": "distance"}


def _load_icons():
    try:
        import Assembly_rc  # noqa: F401  FreeCAD's assembly icons as Qt resources
    except Exception as _fw_err:
        _fw_log("asmpm.py:95", _fw_err)


def drawn_mate_icon(kind):
    ""
    try:
        from . import icons
        icon = icons.drawn("Mate" + "".join(ch for ch in (kind or "") if ch.isalnum()))
        return icon if icons.paints(icon) else None
    except Exception:
        return None


def mate_icon(kind):
    _load_icons()
    family, native = ICONS.get(kind, (None, "Assembly_CreateJointFixed"))
    try:
        from . import icons
        icon = icons.family(family)
        if icons.paints(icon):
            return icon
    except Exception as _fw_err:
        _fw_log("asmpm.py:107", _fw_err)
    return drawn_mate_icon(kind) or QtGui.QIcon(":/icons/%s.svg" % native)


# asmpkg371: a PM header's family the icon pack lacks -> the picture of its command (the drawn FW_<key> set),
# so the page title never shows the initials tile (Chain Pattern, Pattern Driven, Mate Controller, Replace ...)
PM_ICON_DRAWN = {"ASSEMBLIES_CHAIN_PATTERN": "FW_ChainComponentPattern",
                 "ASSEMBLIES_PATTERN_DRIVEN_PATTERN": "FW_PatternDrivenComponentPattern",
                 "ASSEMBLIES_CIRCULAR_PATTERN": "FW_CircularComponentPattern",
                 "ASSEMBLIES_CURVE_DRIVEN_PATTERN": "FW_CurveComponentPattern",
                 "ASSEMBLIES_LINEAR_PATTERN": "FW_LinearComponentPattern",
                 "ASSEMBLIES_SKETCH_DRIVEN_PATTERN": "FW_SketchComponentPattern",
                 "ASSEMBLIES_MIRROR_COMPONENTS": "FW_MirrorComponents", "ASSEMBLIES_MATE": "FW_Mate",
                 "ASSEMBLIES_COPY_WITH_MATES": "FW_CopyWithMates", "ASSEMBLIES_BELT_CHAIN": "FW_AsmBeltChain",
                 "WELDMENTS_WELD_BEAD": "WE_WELD_BEAD", "ASSEMBLIES_EXPLODE_LINE_SKETCH": "FW_ExplodeLineSketch",
                 "ASSEMBLIES_MATE_CONTROLLER": "FW_MateController",
                 "ASSEMBLIES_REPLACE_COMPONENTS": "FW_ReplaceComponents",
                 "MOTION_SPRING": "FW_MotionSpring", "MOTION_DAMPER": "FW_MotionDamper",
                 "MOTION_FORCE": "FW_MotionForce", "MOTION_CONTACT": "FW_MotionContact"}


def pm_icon(family):
    """The icon name a PM header shows for family: the pack's family, else the drawn picture of its command,
    else the Motion drawings (simicons), else family as it is."""
    if not family:
        return ""
    try:
        from . import icons
        if icons.paints(icons.family(family)):
            return family
        alt = PM_ICON_DRAWN.get(family)
        if alt and icons.paints(icons.family(alt)):
            return alt
        drawn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icons-drawn", "%s.svg" % alt) if alt else ""
        if drawn and os.path.isfile(drawn):
            return drawn        # (no icon pack: family() gives nothing, the drawn file is loaded as it is)
        from . import simicons
        path = simicons.svg(family)
        if path:
            return path
    except Exception as _fw_err:
        _fw_log("asmpm.pm_icon", _fw_err)
    return family


def _box(title, pm_title=None, icon=None):
    box = QtWidgets.QWidget()
    box.setWindowTitle(title)
    if pm_title:
        box.setProperty("swstyle_pm_title", pm_title)
        box.setProperty("swstyle_pm_icon", pm_icon(icon) or "")
    lay = QtWidgets.QVBoxLayout(box)
    lay.setContentsMargins(4, 4, 4, 4)
    lay.setSpacing(4)
    return box, lay


def _check(text, param=None, default=True, enabled=True):
    box = QtWidgets.QCheckBox(text)
    box.setChecked(paths.params().GetBool(param, default) if param else default)
    box.setEnabled(enabled)
    if param:
        box.toggled.connect(lambda on, p=param: paths.params().SetBool(p, on))
    return box


def fold(*widgets):
    ""

    for widget in widgets:
        box = widget.parentWidget()
        while box is not None and not box.metaObject().className().endswith("ActionGroup") \
                and not box.metaObject().className().endswith("TaskBox"):
            box = box.parentWidget()
        if box is not None and widget.isVisible():
            QtCore.QMetaObject.invokeMethod(box, "showHide")


OPEN = None     # the assembly PropertyManager on screen, if it is one of these


def _track(panel):
    ""

    global OPEN
    OPEN = panel
    for name in ("accept", "reject"):
        method = getattr(panel, name)

        def wrapped(*args, _m=method):
            global OPEN
            if OPEN is panel:
                OPEN = None
            return _m(*args)
        setattr(panel, name, wrapped)


def close_open():
    """Finish the open assembly PropertyManager (its check). False when another panel is open."""
    if not Gui.Control.activeDialog():
        return True
    if OPEN is None:
        return False
    OPEN.accept()
    return not Gui.Control.activeDialog()


# ============================================================================= Insert Component
def part_documents(asm):
    """Open documents that can go into this assembly: parts, and other assemblies."""
    out = []
    for doc in App.listDocuments().values():
        if doc is asm.Document or getattr(doc, "Temporary", False):
            continue
        if ac.part_object(doc) is not None:
            out.append(doc)
    return out


# ------------------------------------------------------------ a new assembly before its first Save
HELD = {}       # doc name -> holding file
CHILDREN = {}   # held doc name -> [names of documents made in it, saved in its holding folder]
_WATCH = []


class _HoldWatch:
    """The first Save of a held assembly asks where it goes (drawings' holding file). Once it is in its own
    place its links to the parts are set again and saved, so they keep the right relative paths."""

    def slotFinishSaveDocument(self, doc, path):
        held = HELD.get(doc.Name)
        if not held or os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(held)):
            return
        HELD.pop(doc.Name, None)
        QtCore.QTimer.singleShot(0, lambda n=doc.Name: relink(n))

    def slotDeletedDocument(self, doc):
        HELD.pop(doc.Name, None)


def hold_with(top, doc):
    """doc (a new subassembly or part file made in the held assembly top) moves next to top at its first Save."""
    if top.Name in HELD and doc.FileName:
        CHILDREN.setdefault(top.Name, []).append(doc.Name)


def relink(doc_name):
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return False
    folder = os.path.dirname(doc.FileName)
    for name in CHILDREN.pop(doc.Name, []):
        child = App.listDocuments().get(name)
        if child is None or not child.FileName:
            continue
        new = os.path.join(folder, os.path.basename(child.FileName))
        if os.path.exists(new):
            stem, ext = os.path.splitext(new)
            n = 2
            while os.path.exists("%s_%d%s" % (stem, n, ext)):
                n += 1
            new = "%s_%d%s" % (stem, n, ext)
        try:
            child.saveAs(new)
            relink(child.Name)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: moving %s next to %s: %s\n" % (child.Label, doc.Label, error))
    changed = False
    for o in doc.Objects:
        if o.TypeId != "App::Link":
            continue
        t = getattr(o, "LinkedObject", None)
        if t is None or t.Document is doc:
            continue
        o.LinkedObject = None
        o.LinkedObject = t
        changed = True
    if changed:
        doc.save()
        try:
            Gui.getDocument(doc.Name).Modified = False
        except Exception as _fw_err:
            _fw_log("asmpm.py:249", _fw_err)
    return changed


def hold(doc):
    """A new assembly: its holding file now, the Save As box at its first Save (as a new drawing)."""
    from . import drawings
    if doc.FileName:
        return doc.FileName
    if not _WATCH:
        _WATCH.append(_HoldWatch())
        App.addDocumentObserver(_WATCH[0])
    path = drawings.temp_save(doc)
    HELD[doc.Name] = path
    return path


class _InsertKeys(QtCore.QObject):
    """Alt+arrow keys while an inserted component follows the pointer."""
    ARROWS = (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            return False
        if event.key() not in self.ARROWS or not (event.modifiers() & Qt.AltModifier) or self.panel.preview is None:
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()
            return True
        try:
            self.panel.turn_view(event.key())
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Alt+arrow: %s\n" % error)
        return True


FIX_MODES = (("first", "Only fix first component"), ("fix", "Fix"), ("float", "Float"))
FIX_PARAM = "AsmInsertFixMode"


def fix_mode():
    mode = paths.params().GetString(FIX_PARAM, "first")
    return mode if mode in dict(FIX_MODES) else "first"


def set_fix_mode(mode):
    paths.params().SetString(FIX_PARAM, mode)


def apply_fix_mode(asm, comp, mode):
    ""

    try:
        fixed = comp in ac.grounded(asm)
        if mode == "fix" and not fixed:
            ac.fix(asm, comp)
        elif mode == "float" and fixed:
            ac.float_(asm, comp)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: insert fix/float: %s\n" % error)


def config_text(doc, name):
    """A configuration as Insert Component lists it: its name and its description."""
    try:
        from . import configs
        desc = (configs.properties(doc, name).get("description") or "").strip()
    except Exception:
        desc = ""
    return "%s (%s)" % (name, desc) if desc and desc != name else name


def _tree_rows_again():
    ""




    try:
        for view in Gui.getMainWindow().findChildren(QtWidgets.QAbstractItemView, "SWFeatureTree"):
            model = view.model()
            while model is not None and not hasattr(model, "rebuild") and hasattr(model, "sourceModel"):
                model = model.sourceModel()
            if model is not None and hasattr(model, "soon"):
                model.soon()
    except Exception as _fw_err:
        _fw_log("asmpm.py:tree rows again", _fw_err)


class InsertComponentPanel:
    def __init__(self, asm, begin=False):
        _track(self)
        self.asm = asm
        self.begin = begin
        self.preview = None
        self.placed = []
        self.callbacks = []
        self.queue = []
        self.multi_batch = False
        self.closed = False
        title = "Begin Assembly" if begin else "Insert Component"
        message, lay = _box("Message", title, "ASSEMBLIES_INSERT_COMPONENTS")
        text = QtWidgets.QLabel(BEGIN_MESSAGE if begin else INSERT_MESSAGE)
        text.setWordWrap(True)
        lay.addWidget(text)
        self.error = QtWidgets.QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c00000;")
        self.error.hide()
        lay.addWidget(self.error)

        parts, lay = _box("Part/Assembly to Insert")
        lay.addWidget(QtWidgets.QLabel("Open documents:"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_OpenDocuments")
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setMinimumHeight(90)

        # picked row), not a blue selection box
        lay.addWidget(self.list)
        self.config_row = QtWidgets.QWidget()
        # insertcomp-1121: "Configuration:" over a full-width list, Browse... centred (2025 video)
        config_lay = QtWidgets.QVBoxLayout(self.config_row)
        config_lay.setContentsMargins(0, 0, 0, 0)
        config_lay.setSpacing(2)
        config_lay.addWidget(QtWidgets.QLabel("Configuration:"))
        self.config = QtWidgets.QComboBox()
        self.config.setObjectName("FW_InsertConfiguration")
        config_lay.addWidget(self.config)
        self.config_row.hide()
        lay.addWidget(self.config_row)
        self.config.currentIndexChanged.connect(self._config_changed)
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.clicked.connect(self._browse)
        lay.addWidget(self.browse, 0, Qt.AlignHCenter)
        self._fill()

        thumb, lay = _box("Thumbnail Preview")
        self.thumb = QtWidgets.QLabel()
        self.thumb.setObjectName("FW_InsertThumbnail")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumHeight(_px(96))
        lay.addWidget(self.thumb)

        options, lay = _box("Options")
        self.start = _check("Start command when creating new assembly", START_PARAM, True)
        self.auto_browse = _check("Automatic Browse when creating new assembly", "AssemblyAutoBrowse", True)
        self.auto_browse.setObjectName("FW_InsertAutoBrowse")
        self.graphics = _check("Graphics preview", PREVIEW_PARAM, True)
        lay.addWidget(self.start)
        lay.addWidget(self.auto_browse)
        lay.addWidget(self.graphics)
        self.virtual = _check("Make virtual", None, False)
        self.virtual.setObjectName("FW_InsertVirtual")
        self.envelope = _check("Envelope", None, False)
        self.envelope.setObjectName("FW_InsertEnvelope")
        self.rotate_bar_on = _check("Show Rotate context toolbar", ROTATE_BAR_PARAM, True)
        self.rotate_bar_on.setObjectName("FW_InsertRotateToolbar")
        self.rotate_bar_on.toggled.connect(lambda on: self._bar(on and self.preview is not None))
        for w in (self.virtual, self.envelope, self.rotate_bar_on):
            lay.addWidget(w)

        self.fix_buttons = {}
        group = QtWidgets.QButtonGroup(lay.parentWidget() if lay.parentWidget() else None)
        self._fix_group = group
        fix_label = QtWidgets.QLabel("Fix / float component on insert:")      # insertcomp-1121 (2025 video)
        fix_label.setObjectName("FW_InsertFixLabel")
        lay.addWidget(fix_label)
        for key, text in FIX_MODES:
            b = QtWidgets.QRadioButton(text)
            b.setObjectName("FW_InsertFix_" + key)
            b.setChecked(fix_mode() == key)
            b.toggled.connect(lambda on, k=key: on and set_fix_mode(k))
            group.addButton(b)
            lay.addWidget(b)
            self.fix_buttons[key] = b
        self.bar = None
        self.turn = App.Rotation()
        self.pin = None
        self.form = [message, parts, thumb, options]
        self.list.itemSelectionChanged.connect(self._selection_changed)
        for wait in (0, 300, 1000):     # the PropertyManager's header row comes once the panel shows
            QtCore.QTimer.singleShot(wait, self._header)
        if self.list.count() == 1:
            self.list.setCurrentRow(0)
        if begin and self.list.count() == 0 and self.auto_browse.isChecked():
            QtCore.QTimer.singleShot(0, self._auto_browse)

    def _auto_browse(self):
        if not self.closed:
            self._browse()

    def _header(self):
        ""

        if self.pin is not None or self.closed:
            return              # the page closed before its header came: no pushpin for the next page
        try:
            view = self.list.window().findChild(QtWidgets.QWidget, "SWStyle_PMHeader")
        except RuntimeError:
            return              # the PropertyManager closed before its header came
        row = getattr(view, "row", None) if view is not None else None
        if row is None:
            return
        for old in view.findChildren(QtWidgets.QToolButton, "FW_InsertPin"):
            old.hide()                      # an earlier Insert Component's pushpin
            old.setParent(None)
            old.deleteLater()
        self.pin = QtWidgets.QToolButton(view)
        self.pin.setObjectName("FW_InsertPin")
        self.pin.setCheckable(True)
        self.pin.setChecked(False)
        self.pin.setToolTip("Keep Visible")
        try:
            from . import propertymanager as pmod
            self.pin.setIcon(pmod._drawn("PIN_NORMAL"))
            self.pin.toggled.connect(lambda on: self.pin.setIcon(pmod._drawn("PIN_ACTIVE" if on else "PIN_NORMAL")))
        except Exception:
            self.pin.setText("pin")
        self.pin.setIconSize(QtCore.QSize(_px(16), _px(16)))
        t = _tokens()
        self.pin.setStyleSheet("QToolButton { border: 1px solid transparent; background: transparent; }"
                               " QToolButton:checked { background: %s; border-color: %s; }"
                               % (t["down"], t["down_line"]))
        row.insertWidget(row.count() - 1, self.pin)
        page_owned(view, self.pin)

    def pinned(self):
        return self.pin is not None and self.pin.isChecked()

    # ------------------------------------------------------------ Rotate context toolbar
    def _bar(self, on):
        from . import asminsert
        if on and self.rotate_bar_on.isChecked():
            if self.bar is None:
                self.bar = asminsert.RotateBar(self)
            self.bar.move(QtGui.QCursor.pos() + QtCore.QPoint(24, 24))
            self.bar.show()
        elif self.bar is not None:
            self.bar.hide()

    def rotate(self, axis):
        """The Rotate context toolbar: the following component turns about the assembly's axis."""
        if self.preview is None:
            return
        v = {"X": App.Vector(1, 0, 0), "Y": App.Vector(0, 1, 0), "Z": App.Vector(0, 0, 1)}[axis]
        angle = self.bar.angle.value() if self.bar is not None else 90.0
        self.turn = App.Rotation(v, angle).multiply(self.turn)
        base = self.preview.Placement.Base
        self.preview.Placement = App.Placement(base, self.turn, self._centre_offset())

    def _centre_offset(self):
        return App.Vector(self.offset)

    def turn_view(self, key):
        ""


        if self.preview is None:
            return False
        try:
            view = self.view or Gui.ActiveDocument.ActiveView
            up = App.Vector(view.getUpDirection())
            across = App.Vector(view.getViewDirection()).cross(up)
        except Exception:
            up, across = App.Vector(0, 0, 1), App.Vector(1, 0, 0)
        angle = self.bar.angle.value() if self.bar is not None else 90.0
        axis, sign = {Qt.Key_Left: (up, -1), Qt.Key_Right: (up, 1), Qt.Key_Up: (across, -1),
                      Qt.Key_Down: (across, 1)}[key]
        self.turn = App.Rotation(axis, sign * angle).multiply(self.turn)
        base = self.preview.Placement.Base
        self.preview.Placement = App.Placement(base, self.turn, self._centre_offset())
        return True

    # ------------------------------------------------------------ list
    def _fill(self):
        blocked = self.list.blockSignals(True)
        try:
            self.list.clear()
            for doc in part_documents(self.asm):
                item = QtWidgets.QListWidgetItem(doc.Label)
                item.setData(Qt.UserRole, doc.Name)
                obj = ac.part_object(doc)
                try:
                    item.setIcon(obj.ViewObject.Icon)
                except Exception as _fw_err:
                    _fw_log("asmpm.py:518", _fw_err)
                self.list.addItem(item)
        finally:
            self.list.blockSignals(blocked)
        self.queue = []
        self.multi_batch = False

    def _selection_changed(self):
        items = sorted(self.list.selectedItems(), key=self.list.row)
        self.queue = [item.data(Qt.UserRole) for item in items]
        self.multi_batch = len(self.queue) > 1
        self._update_config()
        self._chosen()

    def _update_config(self):
        from . import asmreplacecomp
        doc = App.listDocuments().get(self.queue[0]) if len(self.queue) == 1 else None
        names = asmreplacecomp.configurations(doc) if doc is not None else []
        blocked = self.config.blockSignals(True)
        try:
            self.config.clear()
            for name in names:
                self.config.addItem(config_text(doc, name), name)
            if names:
                active = asmreplacecomp.active_configuration(doc)
                index = self.config.findData(active)
                if index >= 0:
                    self.config.setCurrentIndex(index)
        finally:
            self.config.blockSignals(blocked)
        self.config_row.setVisible(bool(names))

    def _config_changed(self, *args):
        if len(self.queue) != 1 or self.config.currentIndex() < 0:
            return
        from . import asmcfginst
        if self.preview is not None:        # the instance being placed shows it (not the part's other instances)
            asmcfginst.set_configuration(self.preview, self.config.currentData() or self.config.currentText())

    def _consume_multi(self):
        name = self.queue.pop(0)
        blocked = self.list.blockSignals(True)
        try:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole) == name:
                    item.setSelected(False)
                    break
        finally:
            self.list.blockSignals(blocked)
        if not self.queue:
            self.multi_batch = False
        self._update_config()

    def _browse(self):
        start = os.path.dirname(self.asm.Document.FileName or "") or os.path.expanduser("~")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", start,
                                                        "FreeCAD files (*.FCStd);;All files (*)")
        if not path:
            return
        doc = next((d for d in App.listDocuments().values() if d.FileName == path), None)
        if doc is None:
            active = App.ActiveDocument
            doc = App.openDocument(path, hidden=True)
            if active is not None:
                App.setActiveDocument(active.Name)
                Gui.ActiveDocument = Gui.getDocument(active.Name)
        self._drop_preview()
        self._fill()
        self._update_config()
        self._thumbnail(None)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.UserRole) == doc.Name:
                self.list.setCurrentRow(row)
                break

    def _target(self):
        doc = App.listDocuments().get(self.queue[0]) if self.queue else None
        return ac.part_object(doc) if doc is not None else None

    # ------------------------------------------------------------ preview and placing
    def _saved(self, target):
        ""

        if not self.asm.Document.FileName:
            hold(self.asm.Document)
        for doc, what in ((self.asm.Document, "assembly"), (target.Document, "part")):
            if doc.FileName:
                continue
            box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Information, "Save",
                                        "Save the %s \"%s\" first: the assembly keeps its components "
                                        "as links to their saved files." % (what, doc.Label),
                                        QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Cancel,
                                        Gui.getMainWindow())
            if box.exec() != QtWidgets.QMessageBox.Save:
                return False
            if not Gui.getDocument(doc.Name).saveAs():
                return False
        return True

    def _chosen(self, *args):
        target = self._target()
        self._drop_preview()
        self._thumbnail(target)
        if target is None:
            return
        if not self._saved(target):
            return
        if self.begin and not ac.components(self.asm):
            # the first component of a new assembly waits for OK, at the origin; a click in the

            self._watch()
            return
        if self.graphics.isChecked():
            self._start_preview(target)

    def _thumbnail(self, target):
        from . import asminsert
        pm = asminsert.thumbnail(target.Document) if target is not None else None
        if pm is None and target is not None:
            try:
                pm = target.ViewObject.Icon.pixmap(_px(64), _px(64))
            except Exception:
                pm = None
        self.thumb.setPixmap(pm if pm is not None else QtGui.QPixmap())

    def _start_preview(self, target):
        doc = self.asm.Document
        doc.openTransaction("Insert Component")
        try:
            self.preview = ac.insert(self.asm, target, App.Placement())
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        ac.PREVIEWS.add((doc.Name, self.preview.Name))
        self.offset = self.preview.Shape.BoundBox.Center if self.preview.Shape.BoundBox.isValid() else App.Vector()
        self.turn = App.Rotation()
        self._watch()
        self._bar(True)

    def _watch(self):
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is None or self.callbacks:
            return
        from pivy import coin
        self.view = view
        self.callbacks = [
            view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self._moved),
            view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._clicked),
        ]
        if getattr(self, "keys", None) is None:
            self.keys = _InsertKeys(self)
            QtWidgets.QApplication.instance().installEventFilter(self.keys)

    def _unwatch(self):
        if getattr(self, "keys", None) is not None:
            QtWidgets.QApplication.instance().removeEventFilter(self.keys)
            self.keys = None
        if not self.callbacks:
            return
        from pivy import coin
        try:
            self.view.removeEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self.callbacks[0])
            self.view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self.callbacks[1])
        except Exception as _fw_err:
            _fw_log("asmpm.py:679", _fw_err)
        self.callbacks = []

    def _point(self, pos):
        point = self.view.getPoint(pos[0], pos[1])
        return App.Vector(point) - self.offset

    def _moved(self, cb):
        if self.preview is None:
            return
        pos = cb.getEvent().getPosition().getValue()
        self.preview.Placement = App.Placement(self._point((int(pos[0]), int(pos[1]))), self.turn, self._centre_offset())
        if self.bar is not None and self.bar.isVisible():
            self.bar.move(QtGui.QCursor.pos() + QtCore.QPoint(24, 24))

    def _clicked(self, cb):
        event = cb.getEvent()
        from pivy import coin
        if self.preview is None and event.getButton() == coin.SoMouseButtonEvent.BUTTON1 \
                and event.getState() == coin.SoMouseButtonEvent.DOWN and not self.closed \
                and self.begin and self.queue and not ac.components(self.asm):
            cb.setHandled()
            QtCore.QTimer.singleShot(0, self.accept)
            return
        if self.preview is None or event.getButton() != coin.SoMouseButtonEvent.BUTTON1:
            return
        if event.getState() != coin.SoMouseButtonEvent.DOWN:
            return
        pos = event.getPosition().getValue()
        self.place(self._point((int(pos[0]), int(pos[1]))))
        cb.setHandled()

    def place(self, base):
        """Drops the previewed component at base (assembly coordinates) and closes; with the
        pushpin in, the next copy follows the pointer."""
        if self.closed:
            return
        if self.preview is None and self.multi_batch and self.queue:
            self._again()
        if self.preview is None:
            return
        self.preview.Placement = App.Placement(base, self.turn, self._centre_offset())
        self._keep()
        if self.multi_batch:
            self._consume_multi()
            if self.queue:
                QtCore.QTimer.singleShot(0, self._again)
            elif not self.pinned():
                self.closed = True
                QtCore.QTimer.singleShot(0, self._shut)
            return
        if self.pinned():
            QtCore.QTimer.singleShot(0, self._again)
            return
        self.closed = True
        QtCore.QTimer.singleShot(0, self._shut)

    def _shut(self):
        self._close_bar()           # its pushpin goes with it
        Gui.Control.closeDialog()

    def _again(self):
        """Start the next selected part, or repeat the single part when pinned."""
        if self.closed or self.preview is not None or not self.queue:
            return
        try:
            self._chosen()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: insert again: %s\n" % error)

    def _options(self, comp):
        """Make virtual and Envelope on the component just placed, and the configuration picked."""
        from . import asminsert, asmcfginst
        if not self.config_row.isHidden() and self.config.currentIndex() >= 0 \
                and (self.config.currentData() or self.config.currentText()) != asmcfginst.configuration(comp):
            asmcfginst.set_configuration(comp, self.config.currentData() or self.config.currentText(), recompute=False)
        if self.virtual.isChecked():
            asminsert.make_virtual(self.asm, comp)
        if self.envelope.isChecked():
            asminsert.make_envelope(comp)
        apply_fix_mode(self.asm, comp, fix_mode())

    def _keep(self):
        doc = self.asm.Document
        ac.PREVIEWS.discard((doc.Name, self.preview.Name))
        _tree_rows_again()      # asmpkg365: the placed component gets its FeatureManager row
        self.placed.append(self.preview)
        self._options(self.preview)
        self.preview = None
        self._unwatch()
        self._bar(False)
        doc.recompute()
        doc.commitTransaction()

    def _drop_preview(self):
        if self.preview is not None:
            try:
                ac.PREVIEWS.discard((self.asm.Document.Name, self.preview.Name))
            except Exception:
                ac.PREVIEWS.clear()
            self.preview = None
            self.asm.Document.abortTransaction()
            self._unwatch()
        self._bar(False)

    # ------------------------------------------------------------ task panel
    def accept(self):
        # Finish the current preview and each waiting selection at the origin.
        pending = list(self.queue)
        if self.preview is not None:
            self.preview.Placement = App.Placement(App.Vector(), self.turn, self._centre_offset())
            self._keep()
            if pending:
                pending.pop(0)
                if self.multi_batch:
                    self._consume_multi()
        elif self.placed and not self.multi_batch:
            # A pinned single selection has already been placed.
            pending = []
        for name in pending:
            doc = App.listDocuments().get(name)
            target = ac.part_object(doc) if doc is not None else None
            if target is None or not self._saved(target):
                return False
            assembly_doc = self.asm.Document
            assembly_doc.openTransaction("Insert Component")
            try:
                comp = ac.insert(self.asm, target, App.Placement())
                self._options(comp)
                assembly_doc.recompute()
            except BaseException:
                try:
                    assembly_doc.abortTransaction()
                except Exception:
                    pass
                raise
            assembly_doc.commitTransaction()
            self.placed.append(comp)
            if self.multi_batch:
                self._consume_multi()
        self.closed = True
        self._unwatch()
        self._close_bar()
        Gui.Control.closeDialog()
        Gui.SendMsgToActiveView("ViewFit")
        return True

    def _close_bar(self):
        if self.bar is not None:
            self.bar.hide()
            self.bar.deleteLater()
            self.bar = None
        # The header stays for the next PropertyManager: the pushpin is Insert Component's own.
        if self.pin is not None:
            try:
                self.pin.hide()
                self.pin.setParent(None)
                self.pin.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("asmpm.py:830", _fw_err)
            self.pin = None

    def reject(self):
        self.closed = True
        self._drop_preview()
        self._close_bar()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ============================================================================= Mate
DISTANCE_KINDS = ("Center to Center", "Minimum Distance", "Maximum Distance", "Custom Distance")
SIDE_KINDS = ("Center", "Minimum", "Maximum")
SIDE_SIGN = {"Center": 0.0, "Minimum": 1.0, "Maximum": -1.0}
MATE_BLUE = "#2b7ea8"
STANDARD = ("Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric", "Lock")

LATER_KINDS = ("Gear", "Hinge", "Rack Pinion", "Screw", "Distance Range", "Angle Range")
# pressed before the picks too (nothing greyed): made of the picks when they fit
PRE_PICK = LATER_KINDS + ("Profile Center", "Linear/Linear Coupler", "Cam", "Slot", "Universal Joint")
POPUP_ORDER = ("Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric", "Lock",
               "Distance", "Angle")
POPUP_MORE = ("Profile Center", "Symmetric", "Width", "Path Mate", "Linear/Linear Coupler", "Distance Range",
              "Angle Range", "Cam", "Slot", "Hinge", "Gear", "Rack Pinion", "Screw", "Universal Joint")
POPUP_OPEN = [False]

ANALYSIS_MESSAGE = "Select a mate on the Mates tab to add Motion Analysis properties."


def _tokens():
    try:
        from . import style
        return dict(style.tokens())
    except Exception as _fw_err:
        _fw_log("asmpm.py:877", _fw_err)
        return {"pane": "#f7f7f7", "base": "#ffffff", "text": "#000000", "text_disabled": "#9a9a9a",
                "line_mid": "#a9a9a9", "down": "#c8c8c8", "down_line": "#939393",
                "menu_hover": "#cce8ff", "hover_line": "#9cc8ee"}


def _glyph(kind, size=20):
    ""
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(size * 2 / 20.0, size * 2 / 20.0)
    blue = QtGui.QColor(MATE_BLUE)
    pen = QtGui.QPen(blue, 1.6)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    L = lambda x1, y1, x2, y2: p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
    if kind == "Coincident":
        L(4, 16, 10, 5); L(10, 5, 16, 16); L(10, 5, 10, 9)
    elif kind == "Parallel":
        L(4, 12, 12, 4); L(8, 16, 16, 8)
    elif kind == "Perpendicular":
        L(10, 4, 10, 15); L(4, 15, 16, 15)
    elif kind == "Tangent":
        p.drawEllipse(QtCore.QPointF(8, 12), 4, 4); L(4, 4, 16, 4)
    elif kind == "Concentric":
        p.drawEllipse(QtCore.QPointF(10, 10), 6.5, 6.5); p.drawEllipse(QtCore.QPointF(10, 10), 3, 3)
    elif kind == "Lock":
        p.drawArc(QtCore.QRectF(6, 3, 8, 9), 0, 180 * 16); L(6, 7.5, 6, 9); L(14, 7.5, 14, 9)
        p.setBrush(blue); p.drawRoundedRect(QtCore.QRectF(4.5, 9, 11, 8), 1.5, 1.5)
    elif kind == "Distance":
        L(4, 4, 4, 16); L(16, 4, 16, 16); L(5, 10, 15, 10)
        p.setBrush(blue)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(5, 10), QtCore.QPointF(8, 8), QtCore.QPointF(8, 12)]))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(15, 10), QtCore.QPointF(12, 8), QtCore.QPointF(12, 12)]))
    elif kind == "Angle":
        L(3, 16, 16, 16); L(3, 16, 11, 4); p.drawArc(QtCore.QRectF(-3, 10, 14, 12), 0, 58 * 16)
    elif kind in ("Aligned", "Anti-Aligned"):
        for x, up in ((6, True), (14, kind == "Aligned")):
            L(x, 4, x, 16)
            tip, back = (4, 8) if up else (16, 12)
            p.setBrush(blue)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, tip), QtCore.QPointF(x - 2.5, back),
                                           QtCore.QPointF(x + 2.5, back)]))
    elif kind == "FlipAlignment":
        ink = QtGui.QColor(_tokens().get("text", "#202020"))
        p.setPen(QtGui.QPen(ink, 1.6))
        L(5, 15, 14, 6)
        p.setBrush(ink)
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(15, 5), QtCore.QPointF(9.5, 6.5), QtCore.QPointF(13.5, 10.5)]))
    elif kind == "Cam":
        p.drawEllipse(QtCore.QPointF(8.5, 12), 6, 5)
        L(14, 3, 14, 8); p.setBrush(blue); p.drawEllipse(QtCore.QPointF(14, 8.5), 1.6, 1.6)
    elif kind == "Hinge":
        p.drawRect(QtCore.QRectF(3, 4, 6, 12)); p.drawRect(QtCore.QRectF(11, 4, 6, 12))
        p.drawEllipse(QtCore.QPointF(10, 10), 2.2, 2.2)
    elif kind == "Gear":
        for cx, cy, r, n in ((7, 11, 4.5, 8), (14.5, 6, 3, 6)):
            p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
            for i in range(n):
                import math as _m
                t = 2 * _m.pi * i / n
                L(cx + r * _m.cos(t), cy + r * _m.sin(t), cx + (r + 1.6) * _m.cos(t), cy + (r + 1.6) * _m.sin(t))
    elif kind == "Profile Center":
        p.drawRect(QtCore.QRectF(3.5, 3.5, 13, 13))
        p.drawEllipse(QtCore.QPointF(10, 10), 3.5, 3.5)
        L(10, 1.5, 10, 18.5); L(1.5, 10, 18.5, 10)
    elif kind == "Distance Range":
        L(3, 4, 3, 16); L(17, 4, 17, 16); L(5, 10, 15, 10)
        L(5, 10, 7.5, 8); L(5, 10, 7.5, 12); L(15, 10, 12.5, 8); L(15, 10, 12.5, 12)
        L(9, 6, 11, 6); L(9, 14, 11, 14)
    elif kind == "Angle Range":
        L(3, 16, 17, 16); L(3, 16, 13, 4)
        p.drawArc(QtCore.QRectF(-3, 10, 12, 12), 0, 50 * 16)
        L(13, 12, 17, 12)
    elif kind == "Symmetric":
        p.save(); p.setPen(QtGui.QPen(blue, 1.2, Qt.DashLine)); L(10, 2, 10, 18); p.restore()
        L(3, 6, 7, 6); L(3, 6, 3, 14); L(17, 6, 13, 6); L(17, 6, 17, 14)
    elif kind == "Linear/Linear Coupler":
        L(2.5, 6, 17.5, 6); L(2.5, 14, 17.5, 14)
        p.setBrush(blue)
        p.drawRect(QtCore.QRectF(5, 4, 4, 4)); p.drawRect(QtCore.QRectF(11, 12, 4, 4))
        L(7, 8, 13, 12)
    elif kind == "Path Mate":
        path = QtGui.QPainterPath(QtCore.QPointF(2.5, 16))
        path.cubicTo(QtCore.QPointF(7, 2), QtCore.QPointF(12, 18), QtCore.QPointF(17.5, 4))
        p.drawPath(path)
        p.setBrush(blue); p.drawEllipse(QtCore.QPointF(10, 10), 2.2, 2.2)
    elif kind == "Width":
        L(3, 4, 3, 16); L(17, 4, 17, 16)
        p.drawRect(QtCore.QRectF(7.5, 6, 5, 8))
        L(4.5, 10, 6.5, 10); L(13.5, 10, 15.5, 10)
    elif kind == "Rack Pinion":
        p.drawEllipse(QtCore.QPointF(10, 7.5), 4.5, 4.5)
        L(2.5, 15, 17.5, 15)
        for x in (4, 7.5, 11, 14.5):
            L(x, 15, x + 1.2, 13)
    elif kind == "Screw":
        p.drawRect(QtCore.QRectF(7, 3, 6, 14))
        for y in (5, 8.5, 12):
            L(7, y + 2.5, 13, y)
    elif kind == "Selection":
        p.drawRect(QtCore.QRectF(3, 3, 8, 8)); p.drawRect(QtCore.QRectF(9, 9, 8, 8))
    elif kind == "Multiple":
        p.drawRect(QtCore.QRectF(3, 6, 6, 6)); p.drawRect(QtCore.QRectF(11, 3, 6, 6)); p.drawRect(QtCore.QRectF(11, 11, 6, 6))
    p.end()
    pm.setDevicePixelRatio(2)
    return QtGui.QIcon(pm)


def sw_icon(kind):
    ""
    family = ICONS.get(kind, (None,))[0]
    if family:
        try:
            from . import icons
            icon = icons.family(family)
            if icons.paints(icon):
                return icon
        except Exception as _fw_err:
            _fw_log("asmpm.py:982", _fw_err)
    return drawn_mate_icon(kind) or _glyph(kind)


def _px(n):
    """n pixels at the bench's text size, grown with the text: on a PC with 150 % text the
    buttons and boxes grow with the labels beside them (the look's UI sizes follow the text)."""
    height = QtGui.QFontMetrics(QtWidgets.QApplication.font()).height()
    return int(round(n * max(1.0, height / 16.0)))


def _rows(widget, rows):
    return widget.fontMetrics().lineSpacing() * rows + 8


def _square_qss(size=22):
    size = _px(size)
    t = _tokens()
    return ("QToolButton { background: %(base)s; border: 1px solid %(line_mid)s; border-radius: 0px;"
            " padding: 0px; min-width: %(s)dpx; max-width: %(s)dpx; min-height: %(s)dpx; max-height: %(s)dpx; }"
            " QToolButton:hover { background: %(menu_hover)s; border-color: %(hover_line)s; }"
            " QToolButton:checked, QToolButton:pressed { background: %(down)s; border-color: %(down_line)s; }"
            " QToolButton:disabled { background: transparent; border-color: transparent; }"
            % dict(t, s=size))


def reverse_button(name):
    ""
    from . import pmvalues
    b = QtWidgets.QToolButton()
    b.setObjectName(name)
    b.setCheckable(True)
    b.setIcon(pmvalues.reverse_icon())
    b.setIconSize(QtCore.QSize(16, 16))
    b.setToolTip("Reverse Direction")
    b.setAutoRaise(False)
    return b




SHOWN = {"Distance Range": "Distance", "Angle Range": "Angle"}


def shown(kind):
    """The name the user sees for a mate kind."""
    return SHOWN.get(kind, kind)


def _square(kind, name=None, tip=None, size=22):
    b = QtWidgets.QToolButton()
    b.setIcon(sw_icon(kind))
    b.setIconSize(QtCore.QSize(_px(size - 4), _px(size - 4)))
    b.setCheckable(True)
    b.setToolTip(tip or shown(kind))
    b.setStyleSheet(_square_qss(size))
    if name:
        b.setObjectName(name)
    return b


class _Label(QtWidgets.QLabel):
    ""

    def __init__(self, text, button):
        super().__init__(text)
        self.button = button

    def mousePressEvent(self, event):
        if self.button.isEnabled():
            self.button.click()

    # asmpkg348: a mate's name stays a word ("Angle" beside the limit Angle button): the PropertyManager's
    # field-glyph pass (pmlayout) turns a lone "Angle" label into the angle glyph
    def setPixmap(self, pixmap):
        if not self.property("fw_text_only"):
            super().setPixmap(pixmap)

    def setText(self, text):
        if text or not self.property("fw_text_only"):
            super().setText(text)


class MatePopup(QtWidgets.QFrame):
    ""


    def __init__(self, panel, kinds, current):
        super().__init__(Gui.getMainWindow(), Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("FW_MatePopup")
        t = _tokens()
        self.setStyleSheet("QFrame#FW_MatePopup { background: %s; border: 1px solid %s; }"
                           % (t["pane"], t["line_mid"]))
        self.panel = panel
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(2)
        lay = QtWidgets.QHBoxLayout()
        lay.setSpacing(2)
        outer.addLayout(lay)
        self.buttons = {}
        for kind in POPUP_ORDER:
            if kind not in kinds:
                continue
            b = _square(kind, "FW_Pop_%s" % kind, size=26)
            b.setChecked(kind == current)
            b.clicked.connect(lambda _=False, k=kind: panel.choose(k))
            lay.addWidget(b)
            self.buttons[kind] = b

        self.value = QtWidgets.QDoubleSpinBox()
        self.value.setObjectName("FW_PopValue")
        self.value.setDecimals(2)
        self.value.setKeyboardTracking(False)
        self.value.setFixedWidth(_px(80))
        self.value.valueChanged.connect(self._value_typed)
        self.value.valueChanged.connect(self._fit_value)
        lay.addWidget(self.value)

        self.lock = QtWidgets.QCheckBox("Lock rotation")
        self.lock.setObjectName("FW_PopLockRotation")
        own = getattr(panel, "lock_rotation", None)
        self.lock.setChecked(bool(own is not None and own.isChecked()))
        self.lock.toggled.connect(lambda on: own.setChecked(on) if own is not None and own.isChecked() != on else None)
        self.lock.setVisible(False)
        self._value_for(current)
        lay.addSpacing(4)
        self.flip = _square("FlipAlignment", "FW_PopFlip", "Flip Mate Alignment", size=26)
        self.flip.setChecked(not panel.anti.isChecked())     # pkg308: pressed in for Aligned, as _mark_alignment sets it
        self.flip.clicked.connect(panel.flip_alignment)
        lay.addWidget(self.flip)
        from . import asmrefopts
        self.flip.setVisible(asmrefopts.customize("FlipAlignment"))
        lay.addSpacing(4)
        undo = QtWidgets.QToolButton()
        undo.setObjectName("FW_PopUndo")
        undo.setIcon(_std_icon("Std_Undo", "STANDARD_UNDO"))
        undo.setToolTip("Undo")
        undo.setStyleSheet(_square_qss(26))
        undo.setIconSize(QtCore.QSize(_px(20), _px(20)))
        undo.clicked.connect(panel.drop)
        lay.addWidget(undo)
        ok = QtWidgets.QToolButton()
        ok.setObjectName("FW_PopOK")
        ok.setIcon(_std_icon(None, "CHECK_MARK", "#38b000"))
        ok.setToolTip("Add/Finish Mate")
        ok.setStyleSheet(_square_qss(26))
        ok.setIconSize(QtCore.QSize(_px(20), _px(20)))
        ok.clicked.connect(panel.keep)
        lay.addWidget(ok)
        outer.addWidget(self.lock)

        # mates that fit the picks; it remembers whether it was open.
        extra = [k for k in POPUP_MORE if k in kinds]
        self.more = QtWidgets.QWidget()
        self.more.setObjectName("FW_PopMore")
        more = QtWidgets.QHBoxLayout(self.more)
        more.setContentsMargins(0, 0, 0, 0)
        more.setSpacing(2)
        for kind in extra:
            b = _square(kind, "FW_Pop_%s" % kind.replace(" ", "").replace("/", ""), size=26)
            b.setChecked(kind == current)
            b.clicked.connect(lambda _=False, k=kind: self._choose_more(k))
            more.addWidget(b)
            self.buttons[kind] = b
        more.addStretch(1)
        outer.addWidget(self.more)
        self.expand = QtWidgets.QToolButton()
        self.expand.setObjectName("FW_PopExpand")
        self.expand.setCheckable(True)
        self.expand.setToolTip("Expand: Advanced and Mechanical mates")
        self.expand.setAutoRaise(True)
        self.expand.setFixedSize(_px(14), _px(26))
        self.expand.toggled.connect(self._expanded)
        lay.addWidget(self.expand)
        self.expand.setVisible(bool(extra))
        self.expand.setChecked(bool(extra) and POPUP_OPEN[0])
        self._expanded(self.expand.isChecked())

    def _expanded(self, on):
        if not self.expand.isHidden():
            POPUP_OPEN[0] = bool(on)
        self.expand.setArrowType(Qt.LeftArrow if on else Qt.RightArrow)
        self.more.setVisible(bool(on) and bool(self.more.layout().count() > 1))
        self.adjustSize()

    def _choose_more(self, kind):
        ""

        panel = self.panel
        panel.choose(kind)
        QtCore.QTimer.singleShot(0, panel._close_popup)     # not from inside its own click

    def mark(self, kind):
        for k, b in self.buttons.items():
            b.setChecked(k == kind)
        self._value_for(kind)

    def _field(self, kind):
        return getattr(self.panel, {"Distance": "distance", "Angle": "angle"}.get(kind, ""), None)

    def _value_for(self, kind):
        """The value box shows for Distance and Angle, with the PropertyManager's value."""
        field = self._field(kind)
        self.kind = kind
        if getattr(self, "lock", None) is not None:
            self.lock.setVisible(kind == "Concentric" and getattr(self.panel, "lock_rotation", None) is not None)
        if field is None:
            self.value.hide()
            return
        self.value.blockSignals(True)
        self.value.setRange(field.minimum(), field.maximum())
        self.value.setSuffix(field.suffix())
        self.value.setValue(field.value())
        self.value.blockSignals(False)
        self._fit_value()
        self.value.show()
        self.adjustSize()

    def _fit_value(self, *_):
        """pkg300: wide enough for its number and unit (a fixed 80 px cut "209.47 mm" to "209.47 mr")."""
        fm = self.value.fontMetrics()
        need = fm.horizontalAdvance(self.value.text() + "0") + _px(30)
        if need > self.value.width() or self.value.width() > max(_px(80), need + _px(24)):
            self.value.setFixedWidth(max(_px(80), need))
            if self.isVisible():
                self.adjustSize()

    def _value_typed(self, v):
        field = self._field(getattr(self, "kind", None))
        if field is not None and abs(field.value() - v) > 1e-9:
            field.setValue(v)          # the PropertyManager's box: it re-solves the mate

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.panel.keep()
        elif event.key() == Qt.Key_Escape:
            self.panel.drop()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._keep_on_screen(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._keep_on_screen(False)      # the Distance/Angle value box makes it wider

    def _keep_on_screen(self, opening):
        keep_on_screen(self, opening)


def keep_on_screen(w, opening=True):
    ""


    try:
        app = QtGui.QGuiApplication
        scr = app.screenAt(w.pos()) or app.screenAt(QtGui.QCursor.pos()) \
            or Gui.getMainWindow().screen() or app.primaryScreen()
        r = scr.availableGeometry()
        x, y, ww, h = w.x(), w.y(), w.width(), w.height()
        cur = QtGui.QCursor.pos()
        if opening and r.contains(cur):
            if x + ww > r.right() + 1:
                x = cur.x() - 18 - ww
            if y + h > r.bottom() + 1:
                y = cur.y() - 18 - h
        x = max(r.left(), min(x, r.right() + 1 - ww))
        y = max(r.top(), min(y, r.bottom() + 1 - h))
        if (x, y) != (w.x(), w.y()):
            w.move(x, y)
    except Exception as _fw_err:
        _fw_log("asmpm.py:keep_on_screen", _fw_err)


def _std_icon(command, family, tint=None):
    try:
        from . import icons
        icon = icons.family(family)
        if not icon.isNull():
            return icon
    except Exception as _fw_err:
        _fw_log("asmpm.py:1177", _fw_err)
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pm = _hidpi.canvas(40, 40)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    if family == "CHECK_MARK":
        pen = QtGui.QPen(QtGui.QColor(tint or "#38b000"), 5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(8, 21), QtCore.QPointF(16, 29), QtCore.QPointF(32, 11)]))
    else:   # undo: an arrow curling back to the left
        pen = QtGui.QPen(QtGui.QColor(MATE_BLUE), 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(QtCore.QRectF(10, 10, 22, 20), -90 * 16, 220 * 16)
        p.setBrush(QtGui.QColor(MATE_BLUE))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(6, 12), QtCore.QPointF(16, 6), QtCore.QPointF(16, 18)]))
    p.end()
    pm.setDevicePixelRatio(2)
    return QtGui.QIcon(pm)


def _row(lay, button, label, indent=0):
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(indent, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(button)
    if label is not None:
        row.addWidget(label, 1)
    lay.addLayout(row)
    return row


def instance_name(label):
    ""
    import re
    return re.sub(r"<(\d+)>$", r"-\1", label)


def _midpoint_pick(doc, root, sub):
    """The middle of an edge picked by Select Midpoint (rcmenus pkg228), else None."""
    try:
        from . import rcmenus
        return rcmenus.midpoint_pick(doc, root, sub)
    except (ImportError, AttributeError):
        return None
    except Exception as _fw_err:
        _fw_log("asmpm.py:midpoint", _fw_err)
        return None


def _pick_name(label):
    ""

    return label



class _TabBlock(QtWidgets.QWidget):
    ""


    PAIRS = (("Advanced", "Analysis"), ("Standard", "Mechanical"))
    ICONS = {"Standard": "Coincident", "Advanced": "Width", "Mechanical": "Gear", "Analysis": "Multiple"}
    QSS = ("QTabBar::tab { padding: 3px 6px; border: 1px solid palette(mid); background: palette(button);"
           " margin: 0px -1px 0px 0px; font-weight: normal; }")
    QSS_ON = " QTabBar::tab:selected { background: palette(window); border-bottom-color: palette(window); }"
    QSS_OFF = " QTabBar::tab:selected { background: palette(button); }"

    def __init__(self, panel):
        super().__init__()
        self.setObjectName("FW_MateTabBlock")
        self.panel = panel
        self.lay = QtWidgets.QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.bars = []
        for pair in self.PAIRS:
            bar = QtWidgets.QTabBar()
            bar.setObjectName("FW_MateTabRow_" + pair[0])
            bar.setExpanding(True)
            bar.setDrawBase(False)
            bar.setUsesScrollButtons(False)
            bar.setStyleSheet("QTabBar::tab { padding: 3px 6px; }")
            for t in pair:
                try:
                    bar.addTab(sw_icon(self.ICONS[t]), t)
                except Exception:
                    bar.addTab(t)
                bar.setTabToolTip(bar.count() - 1, t if t == "Analysis" else "%s Mates" % t)
            bar.tabBarClicked.connect(lambda i, b=bar: self.pick(b.tabText(i)))
            self.bars.append(bar)
            self.lay.addWidget(bar)
        self.sync()

    def current(self):
        p = self.panel
        if getattr(p, "analysis_tab", False):
            return "Analysis"
        return ("Standard", "Advanced", "Mechanical")[max(0, p.type_tabs.currentIndex())]

    def pick(self, title):
        p = self.panel
        if title == "Analysis":
            p._tab(1)
        else:
            p.analysis_tab = False
            idx = ("Standard", "Advanced", "Mechanical").index(title)
            if p.type_tabs.currentIndex() != idx:
                p.type_tabs.setCurrentIndex(idx)      # its handler shows the page
            else:
                p._tab(0)
        self.sync()

    def sync(self):
        cur = self.current()
        for bar in self.bars:
            titles = [bar.tabText(i) for i in range(bar.count())]
            bar.blockSignals(True)
            if cur in titles:
                bar.setCurrentIndex(titles.index(cur))
                bar.setProperty("fw_active", True)
            else:
                bar.setProperty("fw_active", False)
            bar.blockSignals(False)

            # tab, in the page's colour and open at the bottom (joined to the page under it)
            bar.setStyleSheet(self.QSS + (self.QSS_ON if cur in titles else self.QSS_OFF))
        # the selected tab's row sits on the page (the lower row)
        active = [b for b in self.bars if b.property("fw_active")]
        if active and self.lay.indexOf(active[0]) != self.lay.count() - 1:
            self.lay.removeWidget(active[0])
            self.lay.addWidget(active[0])

def _mark_active(box, on=True):
    """pmboxes' active-box mark on a pick box that keeps its own colours (PICK_STYLE): while it is empty the
    page waits for a pick, so Enter, Esc and typed keys stay with the 3D view (asmpkg362)."""
    try:
        from . import pmboxes
        own = box.styleSheet()
        pmboxes.mark(box, on)
        if own and box.styleSheet() != own:
            box.setStyleSheet(own)
    except Exception as _fw_err:
        App.Console.PrintLog("FreeCAD asmpm._mark_active: %s\n" % _fw_err)


class MatePanel:
    def __init__(self, asm, joint=None):
        _track(self)
        self.asm = asm
        self.doc = asm.Document
        self.refs = []           # [(component, element)]
        self.mids = {}           # (component, element) of an edge picked by Select Midpoint -> its middle
        self.pending = None      # the mate shown as a preview, not kept yet
        self.editing = joint     # a kept mate opened for editing
        self.before_names = {m.Name for m in ac.mates(asm)}     # the mates there before (Add to new folder)
        self.kept = []
        self.kept_batches = []  # committed batch sizes, parallel to kept
        self.popup = None
        self.kind = None
        self.counts = {}
        self.names = {}
        self.faded = None
        self.picked = []         # (root object name, sub-element) of each pick, to keep them lit

        sel, lay = _box("Mate Selections", "Mate", "ASSEMBLIES_MATE")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        side = QtWidgets.QVBoxLayout()
        side.setSpacing(4)
        for kind, tip in (("Selection", "Entities to Mate"), ("Multiple", "Multiple mate mode")):
            b = _square(kind, tip=tip)
            b.setCheckable(kind == "Multiple")
            side.addWidget(b)
            if kind == "Multiple":
                b.setObjectName("FW_MultipleMate")
                b.toggled.connect(self._multi_toggled)
                self.multi_btn = b
            else:
                b.clicked.connect(lambda _=False: self.multi_btn.setChecked(False))
        side.addStretch(1)
        row.addLayout(side)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_MateSelections")
        self.list.setFixedHeight(_rows(self.list, 3))
        self.list.setStyleSheet(PICK_STYLE)
        self.list.setToolTip("Entities to Mate")
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(
            lambda pos: self._sel_menu(pos).popup(self.list.viewport().mapToGlobal(pos)))
        row.addWidget(self.list, 1)
        lay.addLayout(row)
        # asmpkg362: Entities to Mate is the box the picks go into (pmboxes' active mark, own colours kept), so a

        # the Distance field took the keys with "1.00" selected, and a typed key went into it)
        _mark_active(self.list)
        # Multiple mate mode: one common reference, many component references, a mate each
        self.multi = False
        self.common = None
        self.multi_refs, self.multi_pending = [], []
        self.multi_box = QtWidgets.QWidget()
        mlay = QtWidgets.QVBoxLayout(self.multi_box)
        mlay.setContentsMargins(0, 0, 0, 0)
        mlay.addWidget(QtWidgets.QLabel("Common reference:"))
        self.multi_common = QtWidgets.QListWidget()
        self.multi_common.setObjectName("FW_MultiCommon")
        self.multi_common.setFixedHeight(_rows(self.multi_common, 1))
        mlay.addWidget(self.multi_common)
        mlay.addWidget(QtWidgets.QLabel("Component references:"))
        self.multi_list = QtWidgets.QListWidget()
        self.multi_list.setObjectName("FW_MultiRefs")
        self.multi_list.setFixedHeight(_rows(self.multi_list, 3))
        mlay.addWidget(self.multi_list)
        self.multi_folder = QtWidgets.QCheckBox("Create multi-mate folder")
        self.multi_folder.setObjectName("FW_MultiFolder")
        mlay.addWidget(self.multi_folder)
        self.multi_box.hide()
        lay.addWidget(self.multi_box)
        # Angle: Reference Direction (the angle keeps its sense about it; Flip dimension turns it)
        self.angle_ref_box = QtWidgets.QWidget()
        alay = QtWidgets.QVBoxLayout(self.angle_ref_box)
        alay.setContentsMargins(0, 0, 0, 0)
        alay.addWidget(QtWidgets.QLabel("Reference Direction:"))
        self.angle_ref = QtWidgets.QListWidget()
        self.angle_ref.setObjectName("FW_AngleReference")
        self.angle_ref.setFixedHeight(_rows(self.angle_ref, 1))
        self.angle_ref.setStyleSheet(PICK_STYLE)
        self.angle_ref.setToolTip("Reference Direction: an edge, axis or face the angle is measured about")
        self.angle_ref.setContextMenuPolicy(Qt.CustomContextMenu)
        self.angle_ref.customContextMenuRequested.connect(
            lambda pos: self._angle_ref_menu().popup(self.angle_ref.viewport().mapToGlobal(pos)))
        alay.addWidget(self.angle_ref)
        self.angle_ref_box.hide()
        lay.addWidget(self.angle_ref_box)

        # (Rack, Pinion/Gear), each in its own box
        self.role_box = QtWidgets.QWidget()
        self.role_box.setObjectName("FW_MateRoles")
        rl = QtWidgets.QVBoxLayout(self.role_box)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)
        self.role_labels, self.role_lists = [], []
        for i in range(2):
            label = QtWidgets.QLabel("")
            w = QtWidgets.QListWidget()
            w.setObjectName("FW_MateRole%d" % (i + 1))
            w.setStyleSheet(PICK_STYLE)
            w.setFixedHeight(_rows(w, 1))
            rl.addWidget(label)
            rl.addWidget(w)
            self.role_labels.append(label)
            self.role_lists.append(w)
        self.role_box.hide()
        lay.addWidget(self.role_box)
        self.message = QtWidgets.QLabel("")
        self.message.setObjectName("FW_MateMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #e03030;")
        self.message.hide()
        lay.addWidget(self.message)

        self.type_tabs = QtWidgets.QTabBar()
        self.type_tabs.setObjectName("FW_MateTypeTabs")
        self.type_tabs.setDocumentMode(True)
        self.type_tabs.setExpanding(True)
        self.type_tabs.setDrawBase(False)
        self.type_tabs.setUsesScrollButtons(False)
        self.type_tabs.setStyleSheet("QTabBar::tab { padding: 3px 8px; }")     # all three in a 300 px pane
        for title in ("Standard", "Advanced", "Mechanical"):
            self.type_tabs.addTab(title)

        tabs_box = QtWidgets.QWidget()
        tabs_box.setObjectName("FW_MateTypeTabsBox")
        tabs_box.setWindowTitle("Mate Types")
        tl = QtWidgets.QVBoxLayout(tabs_box)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(self.type_tabs)
        self.type_tabs.hide()
        self.tab_block = _TabBlock(self)
        tl.addWidget(self.tab_block)
        for prop in ("swstyle_pm_title", "swstyle_pm_icon"):     # the page's title moves to the first group
            tabs_box.setProperty(prop, sel.property(prop))
            sel.setProperty(prop, None)
        self.tabs_box = tabs_box

        std, lay = _box("Mate Type")
        self.type_buttons = {}
        self.type_labels = {}
        self.group = group = QtWidgets.QButtonGroup(std)
        for kind in STANDARD:
            b = _square(kind, "FW_Mate_%s" % kind)
            b.clicked.connect(lambda _=False, k=kind: self.choose(k))
            group.addButton(b)
            label = _Label(kind, b)
            _row(lay, b, label)
            self.type_buttons[kind] = b
            self.type_labels[kind] = label
            if kind == "Concentric":
                self.lock_rotation = QtWidgets.QCheckBox("Lock rotation")
                self.lock_rotation.setObjectName("FW_LockRotation")
                self.lock_rotation.toggled.connect(self._lock_changed)
                self.lock_rotation.hide()
                _row(lay, self.lock_rotation, None, indent=28)
        self.distance_button = _square("Distance", "FW_Mate_Distance")
        self.distance_button.clicked.connect(lambda: self.choose("Distance"))
        group.addButton(self.distance_button)
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setObjectName("FW_MateDistance")
        self.distance.setRange(0.0, 1.0e6)
        self.distance.setDecimals(2)
        self.distance.setSuffix("mm")
        self.distance.setValue(1.0)
        self.distance.valueChanged.connect(lambda *_: self._typed("Distance"))
        _row(lay, self.distance_button, self.distance)
        self.flip_dimension = QtWidgets.QCheckBox("Flip dimension")
        self.flip_dimension.setObjectName("FW_FlipDimension")
        # only as wide as its box and text: a click beside the text, on a stretched check box,
        # did nothing (QCheckBox takes clicks on its box and text only)
        self.flip_dimension.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.flip_dimension.toggled.connect(self._flip_toggled)
        self.flip_dimension.hide()
        _row(lay, self.flip_dimension, None, indent=28)

        self.dist_kinds = QtWidgets.QWidget()
        self.dist_kinds.setObjectName("FW_DistanceKinds")
        dk = QtWidgets.QVBoxLayout(self.dist_kinds)
        dk.setContentsMargins(28, 0, 0, 0)
        dk.setSpacing(2)
        self.dist_kind = {}
        kg = QtWidgets.QButtonGroup(self.dist_kinds)
        for name in DISTANCE_KINDS:
            r = QtWidgets.QRadioButton(name)
            r.setObjectName("FW_Distance_" + name.replace(" ", ""))
            r.setChecked(name == "Center to Center")
            r.toggled.connect(lambda on, *_: on and self._dist_kind_changed())
            kg.addButton(r)
            dk.addWidget(r)
            self.dist_kind[name] = r
        self.custom_rows = QtWidgets.QWidget()
        cf = QtWidgets.QFormLayout(self.custom_rows)
        cf.setContentsMargins(16, 0, 0, 0)
        self.custom_sides = []
        for label in ("First selection:", "Second selection:"):
            c = QtWidgets.QComboBox()
            c.setObjectName("FW_DistanceCustom%d" % (len(self.custom_sides) + 1))
            c.addItems(list(SIDE_KINDS))
            c.currentTextChanged.connect(lambda *_: self._dist_kind_changed())
            cf.addRow(label, c)
            self.custom_sides.append(c)
        dk.addWidget(self.custom_rows)
        self.dist_kinds.hide()
        lay.addWidget(self.dist_kinds)
        self.angle_button = _square("Angle", "FW_Mate_Angle")
        self.angle_button.clicked.connect(lambda: self.choose("Angle"))
        group.addButton(self.angle_button)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("FW_MateAngle")
        self.angle.setRange(0.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("deg")
        self.angle.setValue(30.0)
        self.angle.valueChanged.connect(lambda *_: self._typed("Angle"))
        _row(lay, self.angle_button, self.angle)
        self.type_buttons["Distance"] = self.distance_button
        self.type_buttons["Angle"] = self.angle_button
        self.alignment_label = QtWidgets.QLabel("Mate alignment:")
        self.alignment_label.setAlignment(Qt.AlignHCenter)
        lay.addWidget(self.alignment_label)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        self.aligned = _square("Aligned", "FW_Aligned", "Aligned", size=26)
        self.anti = _square("Anti-Aligned", "FW_AntiAligned", "Anti-Aligned", size=26)
        align = QtWidgets.QButtonGroup(std)
        for b in (self.aligned, self.anti):
            align.addButton(b)
            b.clicked.connect(lambda _=False, w=b: self._align(w))
            row.addWidget(b)
        self.anti.setChecked(True)
        row.addStretch(1)
        lay.addLayout(row)

        adv, lay = _box("Advanced Mates")
        mech, lay2 = _box("Mechanical Mates")
        for box_lay, names in ((lay, ("Profile Center", "Symmetric", "Width", "Path Mate",
                                      "Linear/Linear Coupler", "Distance Range", "Angle Range")),
                               (lay2, ("Cam", "Slot", "Hinge", "Gear", "Rack Pinion", "Screw",
                                       "Universal Joint"))):
            for name in names:
                if name in ac.MECHANICAL + ac.ADVANCED:
                    b = _square(name, "FW_Mate_%s" % name.replace(" ", ""))
                    b.clicked.connect(lambda _=False, k=name: self.choose(k))
                    group.addButton(b)
                    label = _Label(shown(name), b)
                    if name in SHOWN:
                        label.setProperty("fw_text_only", True)
                        label.setProperty("swlayout", shown(name))     # pmlayout.DONE: its row is left as laid out
                    _row(box_lay, b, label)
                    self.type_buttons[name] = b
                    self.type_labels[name] = label
                    if name == "Gear":
                        self._gear_fields(box_lay)
                    if name == "Hinge":
                        self._hinge_fields(box_lay)
                    if name in COUPLER_MODES:
                        self._coupler_fields(box_lay, name)
                    if name == "Profile Center":
                        self._profile_fields(box_lay)
                    if name == "Width":
                        self._width_fields(box_lay)
                    if name == "Path Mate":
                        self._path_fields(box_lay)
                    if name == "Linear/Linear Coupler":
                        self._linear_fields(box_lay)
                    if name == "Symmetric":
                        self._symmetric_fields(box_lay)
                    if name in ac.LIMITS:
                        self._limit_fields(box_lay, name)
                    if name == "Slot":
                        self._slot_fields(box_lay)
                    if name == "Universal Joint":
                        self._ujoint_fields(box_lay)
                    if name == "Cam":
                        self.cam_note = QtWidgets.QLabel("Cam path: the first pick; Cam follower: the second.")
                        self.cam_note.setObjectName("FW_CamNote")
                        self.cam_note.setWordWrap(True)
                        self.cam_note.setEnabled(False)
                        self.cam_note.setProperty("fw_keep_grey", True)     # a grey note, not a control (pmnogrey keeps it)
                        _row(box_lay, self.cam_note, None, indent=28)
                        self.cam_note.hide()
                    continue
                b = _square(name)
                b.setEnabled(False)
                label = QtWidgets.QLabel(name)
                label.setEnabled(False)
                _row(box_lay, b, label)
        self.mech_box = mech
        self.adv_box = adv

        mlist, lay = _box("Mates")
        self.mates = QtWidgets.QListWidget()
        self.mates.setObjectName("FW_MatesList")
        self.mates.setFixedHeight(_rows(self.mates, 4))
        lay.addWidget(self.mates)

        opts, lay = _box("Options")
        self.add_folder = _check("Add to new folder", None, False)
        self.add_folder.setObjectName("FW_AddToNewFolder")
        lay.addWidget(self.add_folder)
        self.show_popup = _check("Show popup dialog", POPUP_PARAM, True)
        lay.addWidget(self.show_popup)
        self.show_preview = _check("Show preview", MATE_PREVIEW_PARAM, True)
        self.show_preview.setObjectName("FW_MateShowPreview")
        lay.addWidget(self.show_preview)
        self.position_only = _check("Use for positioning only", None, False)
        self.position_only.setObjectName("FW_PositionOnly")
        lay.addWidget(self.position_only)
        self.fade_first = _check("Make first selection transparent", FADE_PARAM, True)
        lay.addWidget(self.fade_first)

        self.analysis_boxes = self._analysis_boxes()
        self.form = [tabs_box, sel, std, adv, mech, mlist, opts] + self.analysis_boxes
        self.mate_boxes = [tabs_box, sel, std, adv, mech, mlist, opts]
        self.sel_box = sel
        self.std_box = std
        self.type_boxes = [std, adv, mech]
        for i, kinds in ((0, STANDARD), (1, ac.ADVANCED), (2, ac.MECHANICAL)):
            b = self.type_buttons.get(kinds[0]) if kinds else None
            if b is not None:
                self.type_tabs.setTabToolTip(i, "%s Mates" % self.type_tabs.tabText(i))
        self.type_tabs.setCurrentIndex(0)    # a mate edited from Advanced or Mechanical: _open_box picks its tab
        self.type_tabs.currentChanged.connect(self._type_tab)
        from . import safe_later as _sl; _sl.later(0, lambda: self._tab(0), self, "type_tabs")
        for wait in (0, 300, 1000):     # the PropertyManager's header row comes once the panel shows
            QtCore.QTimer.singleShot(wait, self._header)
        self._enable(())
        if joint is not None:
            self._load(joint)
        Gui.Selection.addObserver(self, 0)   # unresolved: the pick as the assembly sees it
        QtCore.QTimer.singleShot(0, self._preselected)

    def _gear_fields(self, lay):
        ""
        self.gear_row = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self.gear_row)
        row.setContentsMargins(28, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QtWidgets.QLabel("Ratio:"))
        self.gear_ratio = []
        for i in (1, 2):
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName("FW_GearRatio%d" % i)
            box.setRange(0.001, 1.0e6)
            box.setDecimals(2)
            box.setSuffix("mm")
            box.setValue(1.0)
            box.valueChanged.connect(self._value_changed)
            self.gear_ratio.append(box)
            row.addWidget(box, 1)
            if i == 1:
                row.addWidget(QtWidgets.QLabel(":"))
        lay.addWidget(self.gear_row)
        self.gear_reverse = QtWidgets.QCheckBox("Reverse")
        self.gear_reverse.setObjectName("FW_GearReverse")
        self.gear_reverse.toggled.connect(self._value_changed)
        _row(lay, self.gear_reverse, None, indent=28)
        self.gear_row.hide()
        self.gear_reverse.hide()

    def _profile_fields(self, lay):
        ""
        self.profile_box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(self.profile_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        self.profile_lock = QtWidgets.QCheckBox("Lock rotation")
        self.profile_lock.setObjectName("FW_ProfileLock")
        col.addWidget(self.profile_lock)
        row = QtWidgets.QHBoxLayout()
        self.profile_offset = QtWidgets.QDoubleSpinBox()
        self.profile_offset.setObjectName("FW_ProfileOffset")
        self.profile_offset.setRange(0.0, 1.0e6)
        self.profile_offset.setDecimals(2)
        self.profile_offset.setSuffix("mm")
        self.profile_offset.setToolTip("Offset distance")
        row.addWidget(self.profile_offset, 1)
        self.profile_flip = QtWidgets.QCheckBox("Flip dimension")
        self.profile_flip.setObjectName("FW_ProfileFlip")
        row.addWidget(self.profile_flip)
        col.addLayout(row)
        lay.addWidget(self.profile_box)
        self.profile_box.hide()
        self.profile_lock.toggled.connect(self._value_changed)
        self.profile_offset.valueChanged.connect(self._value_changed)
        self.profile_flip.toggled.connect(self._value_changed)

    def _limit_fields(self, lay, kind):
        ""
        if not hasattr(self, "limits"):
            self.limits = {}
        key = kind.replace(" ", "")
        box = QtWidgets.QWidget()
        box.setObjectName("FW_%sFields" % key)
        form = QtWidgets.QFormLayout(box)
        form.setContentsMargins(28, 0, 0, 0)
        fields = {}

        value = QtWidgets.QDoubleSpinBox()
        value.setObjectName("FW_%sValue" % key)
        value.setDecimals(2)
        value.setRange(0.0, 1.0e6 if kind == "Distance Range" else 180.0)
        value.setSuffix("mm" if kind == "Distance Range" else "deg")
        value.setKeyboardTracking(False)     # pkg309: a typed value applies once entered
        value.valueChanged.connect(lambda *_a, k=kind: self._limit_value_changed(k))
        form.addRow(value)
        flip = QtWidgets.QCheckBox("Flip dimension")
        flip.setObjectName("FW_%sFlip" % key)
        flip.toggled.connect(lambda *_a, k=kind: self._limit_value_changed(k))
        form.addRow(flip)
        for label, end in (("Maximum:", "Max"), ("Minimum:", "Min")):
            w = QtWidgets.QDoubleSpinBox()
            w.setObjectName("FW_%s%s" % (key, end))
            w.setDecimals(2)
            w.setRange(0.0, 1.0e6 if kind == "Distance Range" else 180.0)
            w.setSuffix("mm" if kind == "Distance Range" else "deg")
            w.setKeyboardTracking(False)     # pkg309: a typed Maximum/Minimum applies once entered, not per keystroke
            w.valueChanged.connect(lambda *_a, k=kind: self._limit_changed(k))
            form.addRow(label, w)
            fields[end] = w

        lay.addWidget(box)
        box.hide()
        self.limits[kind] = {"box": box, "max": fields["Max"], "min": fields["Min"], "value": value, "flip": flip,
                             "sign": 1.0}

    def _ujoint_fields(self, lay):
        ""

        self.uj_ref = None
        self.uj_box = QtWidgets.QWidget()
        self.uj_box.setObjectName("FW_UniversalJointFields")
        col = QtWidgets.QVBoxLayout(self.uj_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        self.uj_define = QtWidgets.QCheckBox("Define joint point")
        self.uj_define.setObjectName("FW_UJointDefine")
        col.addWidget(self.uj_define)
        self.uj_list = QtWidgets.QListWidget()
        self.uj_list.setObjectName("FW_UJointPoint")
        self.uj_list.setStyleSheet(PICK_STYLE)
        self.uj_list.setFixedHeight(_rows(self.uj_list, 1))
        self.uj_list.setToolTip("Joint point: a vertex or a circular edge")
        col.addWidget(self.uj_list)
        self.uj_list.setVisible(False)          # shown with Define joint point (not greyed)
        self.uj_define.toggled.connect(self._ujoint_toggled)
        lay.addWidget(self.uj_box)
        self.uj_box.hide()

    def _ujoint_toggled(self, on):
        self.uj_list.setVisible(on)
        joint = self.pending or self.editing
        if not on:
            self.uj_ref = None
            self.uj_list.clear()
            if joint is not None and ac.mate_type(joint) == "Universal Joint":
                ok = ac.set_joint_point(self.asm, joint, None)
                self._error_text("" if ok else ac.OVER_MESSAGE)

    def _ujoint_pick(self, ref):
        s = ac.element(*ref)
        if s is None or not (s.ShapeType == "Vertex" or (s.ShapeType == "Edge" and "Circle" in s.Curve.TypeId)):
            self._error_text("Select a vertex or a circular edge for the joint point.")
            return
        self.uj_ref = ref
        self.uj_list.clear()
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha())
        self.uj_list.addItem("%s@%s" % (kind, _pick_name(ref[0].Label)))
        joint = self.pending or self.editing
        if joint is not None:
            ok = ac.set_joint_point(self.asm, joint, ref)
            self._error_text("" if ok else ac.OVER_MESSAGE)

    def _slot_fields(self, lay):
        ""

        self.slot_box = QtWidgets.QWidget()
        self.slot_box.setObjectName("FW_SlotFields")
        col = QtWidgets.QVBoxLayout(self.slot_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(QtWidgets.QLabel("Constraint:"))
        self.slot_mode = QtWidgets.QComboBox()
        self.slot_mode.setObjectName("FW_SlotConstraint")
        for text in ac.SLOT_MODES:
            self.slot_mode.addItem(text, text)
        col.addWidget(self.slot_mode)
        self.slot_value = QtWidgets.QDoubleSpinBox()
        self.slot_value.setObjectName("FW_SlotValue")
        self.slot_value.setDecimals(2)
        col.addWidget(self.slot_value)
        self.slot_note = QtWidgets.QLabel("")      # pkg304: Free stops the pin at the slot's ends now
        self.slot_note.setObjectName("FW_SlotNote")
        self.slot_note.setWordWrap(True)
        self.slot_note.setEnabled(False)
        self.slot_note.setProperty("fw_keep_grey", True)     # a grey note, not a control (pmnogrey keeps it)
        col.addWidget(self.slot_note)
        lay.addWidget(self.slot_box)
        self.slot_box.hide()
        self.slot_mode.currentIndexChanged.connect(self._slot_mode_changed)
        self.slot_value.valueChanged.connect(self._slot_changed)
        self._slot_mode_changed(remake=False)

    def _slot_mode_changed(self, *args, remake=True):
        mode = self.slot_mode.currentData()
        self.slot_value.blockSignals(True)
        self.slot_value.setVisible(mode in ("Distance Along Slot", "Percent Along Slot"))
        self.slot_value.setSuffix("%" if mode == "Percent Along Slot" else "mm")
        self.slot_value.setRange(0.0, 100.0 if mode == "Percent Along Slot" else 1.0e6)
        if mode == "Percent Along Slot" and args:
            self.slot_value.setValue(50.0)
        self.slot_value.blockSignals(False)
        self.slot_note.setVisible(mode == "Free")
        if remake:
            self._slot_changed()

    def _slot_set(self, mode, value):
        for w in (self.slot_mode, self.slot_value):
            w.blockSignals(True)
        self.slot_mode.setCurrentIndex(max(0, self.slot_mode.findData(mode)))
        self.slot_value.setValue(value)
        for w in (self.slot_mode, self.slot_value):
            w.blockSignals(False)
        self._slot_mode_changed(remake=False)

    def _slot_start(self):
        """Slot chosen for the pin and the slot: the default mate goes; the pin is held in the slot."""
        import UtilsAssembly
        refs = list(self.refs)
        old = self.pending
        if old is not None and ac.mate_type(old) != "Slot":
            name = old.Name
            old = self.pending = None
            self.doc.removeObject(name)
            if getattr(self, "start", None):
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        self._slot_set("Free", 0.0)
        joint, problem = ac.make_slot(self.asm, refs, "Free", 0.0, joint=old)
        self.kind = "Slot"
        if joint is not None:
            self.pending = joint
        self._show_kind()
        self._error_text(problem or "")

    def _slot_changed(self, *args):
        joint = self.pending or self.editing
        if self.kind != "Slot" or joint is None or ac.mate_type(joint) != "Slot":
            return
        refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
        _j, problem = ac.make_slot(self.asm, refs, self.slot_mode.currentData(), self.slot_value.value(), joint=joint)
        self._error_text(problem or "")

    def _limit_set(self, kind, low, high, value=None):
        f = self.limits[kind]
        pairs = [(f["max"], high), (f["min"], low)]
        if value is not None:
            pairs.append((f["value"], abs(value)))
            f["sign"] = -1.0 if value < 0 else 1.0
            f["flip"].blockSignals(True)
            f["flip"].setChecked(False)
            f["flip"].blockSignals(False)
        for w, v in pairs:
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    def _limit_value_changed(self, kind):
        ""

        joint = self.pending or self.editing
        if self.kind != kind or joint is None or ac.mate_type(joint) != kind:
            return
        f = self.limits[kind]
        v = f["value"].value()
        for w, test in ((f["max"], lambda m: v > m), (f["min"], lambda m: v < m)):
            if test(w.value()):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
        ac.make_limit(self.asm, kind, refs, f["min"].value(), f["max"].value(), joint=joint)
        sign = f["sign"] * (-1.0 if f["flip"].isChecked() else 1.0)
        ac.limit_move(self.asm, joint, kind, sign * v)
        _j, problem = ac.make_limit(self.asm, kind, refs, f["min"].value(), f["max"].value(), joint=joint)
        self._error_text(problem or "")

    def _limit_start(self, kind):
        """Range chosen for the two picks: the default mate goes; the range is set on the mate
        that lets them move, Minimum and Maximum around where they are now."""
        import UtilsAssembly
        refs = list(self.refs)
        old = self.pending
        if old is not None and ac.mate_type(old) not in ac.LIMITS:
            name = old.Name
            old = self.pending = None
            self.doc.removeObject(name)
            if getattr(self, "start", None):
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        signed = ac.picked_value(kind, refs)
        now = abs(signed) if kind == "Distance Range" else signed
        span = 10.0 if kind == "Distance Range" else 30.0
        top = 1.0e6 if kind == "Distance Range" else 180.0
        low, high = max(0.0, now - span), min(top, now + span)
        self._limit_set(kind, low, high, signed)
        if old is not None and ac.mate_type(old) != kind:      # the other range: made again
            self.doc.removeObject(old.Name)
            old = self.pending = None
        joint, problem = ac.make_limit(self.asm, kind, refs, low, high, joint=old)
        if joint is None:
            self.kind = kind
            self._show_kind()
            self._error_text(problem)
            return
        self.pending = joint
        self.kind = kind
        self._show_kind()
        self._error_text(problem or "")

    def _limit_changed(self, kind):
        joint = self.pending or self.editing
        if self.kind != kind or joint is None or ac.mate_type(joint) != kind:
            return
        f = self.limits[kind]
        refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
        _j, problem = ac.make_limit(self.asm, kind, refs, f["min"].value(), f["max"].value(), joint=joint)
        v = f["value"].value()
        if f["min"].value() - 1e-9 <= v <= f["max"].value() + 1e-9:

            # clamped them on the way does not leave them at its end)
            sign = f["sign"] * (-1.0 if f["flip"].isChecked() else 1.0)
            ac.limit_move(self.asm, joint, kind, sign * v)
            _j, problem = ac.make_limit(self.asm, kind, refs, f["min"].value(), f["max"].value(), joint=joint)
        self._error_text(problem or "")

    def _symmetric_fields(self, lay):
        ""
        self.sym_entities, self.sym_plane = [], None
        self.sym_box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(self.sym_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(QtWidgets.QLabel("Entities to mate:"))
        self.sym_list = QtWidgets.QListWidget()
        self.sym_list.setObjectName("FW_SymmetricEntities")
        self.sym_list.setStyleSheet(PICK_STYLE)
        self.sym_list.setFixedHeight(_rows(self.sym_list, 2))
        col.addWidget(self.sym_list)
        col.addWidget(QtWidgets.QLabel("Symmetry plane:"))
        self.sym_plane_list = QtWidgets.QListWidget()
        self.sym_plane_list.setObjectName("FW_SymmetryPlane")
        self.sym_plane_list.setStyleSheet(PICK_STYLE)
        self.sym_plane_list.setFixedHeight(_rows(self.sym_plane_list, 1))
        col.addWidget(self.sym_plane_list)
        note = QtWidgets.QLabel("")      # pkg304: it follows a drag now; the label stays (hidden) for older readers
        note.setObjectName("FW_SymmetricNote")
        note.setWordWrap(True)
        note.setEnabled(False)
        note.setProperty("fw_keep_grey", True)     # a grey note, not a control (pmnogrey keeps it)
        col.addWidget(note)
        lay.addWidget(self.sym_box)
        self.sym_box.hide()

    def _symmetric_start(self):
        self.kind = "Symmetric"
        self.sym_entities, self.sym_plane = [], None
        self.sym_list.clear()
        self.sym_plane_list.clear()
        self._show_kind()

    def _symmetric_pick(self, ref):
        g = ac.geometry(ac.element(*ref))
        if g is None or g[0] != "plane" or ref in self.sym_entities:
            return
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        text = "%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label))
        if len(self.sym_entities) < 2:
            if self.sym_entities and self.sym_entities[0][0] is ref[0]:
                return      # two components
            self.sym_entities.append(ref)
            self.sym_list.addItem(text)
            return
        self.sym_plane = ref
        self.sym_plane_list.addItem(text)
        if not ac.symmetric_ok(self.sym_plane, self.sym_entities):
            self._error_text("The entities must be flat faces parallel to the symmetry plane.")
            self.sym_plane = None
            self.sym_plane_list.clear()
            return
        self.doc.openTransaction("Mate")
        try:
            self.pending, ok = ac.make_symmetric(self.asm, self.sym_plane, self.sym_entities)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.refs = [(self.pending.Reference1[0], self.pending.Reference1[1][0]),
                     (self.pending.Reference2[0], self.pending.Reference2[1][0])]
        self._list()
        self._show_kind()
        self._error(self.pending)

    def _width_fields(self, lay):
        ""

        self.width_sel, self.tab_sel = [], []
        self.width_box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(self.width_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        lists = []
        for label, name in (("Width selections 1:", "FW_WidthSelections"), ("Width selections 2:", "FW_TabSelections")):
            col.addWidget(QtWidgets.QLabel(label))
            w = QtWidgets.QListWidget()
            w.setObjectName(name)
            w.setStyleSheet(PICK_STYLE)
            w.setFixedHeight(_rows(w, 2))
            col.addWidget(w)
            lists.append(w)
        self.width_list, self.tab_list = lists
        col.addWidget(QtWidgets.QLabel("Constraint:"))
        self.width_mode = QtWidgets.QComboBox()
        self.width_mode.setObjectName("FW_WidthConstraint")
        for text, mode in WIDTH_MODES:
            self.width_mode.addItem(text, mode)
        col.addWidget(self.width_mode)
        row = QtWidgets.QHBoxLayout()
        self.width_value = QtWidgets.QDoubleSpinBox()
        self.width_value.setObjectName("FW_WidthValue")
        self.width_value.setRange(0.0, 1.0e6)
        self.width_value.setDecimals(2)
        row.addWidget(self.width_value, 1)
        self.width_flip = QtWidgets.QCheckBox("Flip dimension")
        self.width_flip.setObjectName("FW_WidthFlip")
        row.addWidget(self.width_flip)
        col.addLayout(row)
        lay.addWidget(self.width_box)
        self.width_box.hide()
        self.width_mode.currentIndexChanged.connect(self._width_mode_changed)
        self.width_value.valueChanged.connect(self._width_changed)
        self.width_flip.toggled.connect(self._width_changed)
        self._width_mode_changed()

    def _width_mode_changed(self, *args):
        mode = self.width_mode.currentData()
        value = mode in ("dimension", "percent")
        self.width_value.setVisible(value)
        self.width_flip.setVisible(value)
        self.width_value.blockSignals(True)
        self.width_value.setSuffix("%" if mode == "percent" else "mm")
        self.width_value.setRange(0.0, 100.0 if mode == "percent" else 1.0e6)
        self.width_value.setValue(50.0 if mode == "percent" else 0.0)
        self.width_value.blockSignals(False)
        self._width_changed()

    def _width_changed(self, *args):
        joint = self.pending or self.editing
        if self.kind != "Width" or joint is None or ac.mate_type(joint) != "Width":
            return
        width, tab = (self.width_sel, self.tab_sel) if len(self.tab_sel) == 2 else ac.width_values(joint)[:2]
        ac.make_width(self.asm, width, tab, self.width_mode.currentData() or "centered",
                      self.width_value.value(), self.width_flip.isChecked(), joint=joint)
        self._error(joint)

    def _width_start(self):
        """Width chosen before any pick: the next picks fill Width selections, then Tab selections."""
        self.kind = "Width"
        self.width_sel, self.tab_sel = [], []
        self.width_list.clear()
        self.tab_list.clear()
        self.width_mode.blockSignals(True)
        self.width_mode.setCurrentIndex(0)
        self.width_mode.blockSignals(False)
        self._width_mode_changed()
        self._show_kind()

    def _width_pick(self, ref):
        el = ac.element(*ref)
        g = ac.geometry(el)
        if g is None or ref in self.width_sel + self.tab_sel:
            return
        if len(self.tab_sel) >= 2:

            # replaces the selection rather than taking a third tab entity)
            self.tab_sel = []
            self.tab_list.clear()
        if g[0] == "axis" and getattr(el, "ShapeType", "Face") != "Face":
            return
        target, view = (self.width_sel, self.width_list) if len(self.width_sel) < 2 else (self.tab_sel, self.tab_list)

        if g[0] != "plane" and not (g[0] == "axis" and target is self.tab_sel and not self.tab_sel):
            return
        if target and target[0][0] is not ref[0]:
            return          # both faces of a selection on one component
        if target is self.tab_sel and ref[0] is self.width_sel[0][0]:
            return          # the tab is another component
        target.append(ref)
        if g[0] == "axis":
            target.append(ref)      # one cylindrical face fills the Tab selections
        try:
            from . import asmwidthtags
            asmwidthtags.show(self)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: width tags: %s\n" % error)
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        view.addItem("%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label)))
        if len(self.tab_sel) == 2:
            if not ac.width_ok(self.width_sel, self.tab_sel):
                self._error_text("The width faces must be flat and parallel, and the tab two faces "
                                 "parallel to them or one cylindrical face along them.")
                return
            self.doc.openTransaction("Mate")
            self.pending, ok = ac.make_width(self.asm, self.width_sel, self.tab_sel,
                                             self.width_mode.currentData() or "centered",
                                             self.width_value.value(), self.width_flip.isChecked())
            self.refs = [(self.pending.Reference1[0], self.pending.Reference1[1][0]),
                         (self.pending.Reference2[0], self.pending.Reference2[1][0])]
            self._list()
            self._show_kind()
            self._error(self.pending)

    # ------------------------------------------------------------------------- Cam
    def _cam_start(self):
        """Cam chosen for the cam's face and the follower: the default mate goes; the follower is
        put on the cam."""
        import UtilsAssembly
        refs = list(self.refs)
        if not asmcam.is_cam(refs[0]) or asmcam.follower_kind(refs[1]) is None:
            refs.reverse()
        old = self.pending
        if old is not None and ac.mate_type(old) != "Cam":
            name = old.Name
            self.pending = None
            self.doc.removeObject(name)
            if getattr(self, "start", None):
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        joint, problem = asmcam.make(self.asm, refs[0], refs[1])
        self.kind = "Cam"
        if joint is not None:
            self.pending = joint
            self._title(joint.Label)
        self._show_kind()
        self._error_text(problem or "")

    # ------------------------------------------------------------------------- Linear/Linear Coupler
    def _linear_fields(self, lay):
        ""

        self.linear_refs = ["", ""]
        self.linear_box = QtWidgets.QWidget()
        self.linear_box.setObjectName("FW_LinearFields")
        col = QtWidgets.QVBoxLayout(self.linear_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        self.linear_ref_lists = []
        for i in (1, 2):
            col.addWidget(QtWidgets.QLabel("Reference component %d:" % i))
            w = QtWidgets.QListWidget()
            w.setObjectName("FW_LinearReference%d" % i)
            w.setStyleSheet(PICK_STYLE)
            w.setFixedHeight(_rows(w, 1))
            col.addWidget(w)
            self.linear_ref_lists.append(w)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Ratio:"))
        self.linear_ratio = []
        for i in (1, 2):
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName("FW_LinearRatio%d" % i)
            box.setRange(0.001, 1.0e6)
            box.setDecimals(2)
            box.setSuffix("mm")
            box.setValue(1.0)
            box.valueChanged.connect(self._linear_changed)
            self.linear_ratio.append(box)
            row.addWidget(box, 1)
            if i == 1:
                row.addWidget(QtWidgets.QLabel(":"))
        col.addLayout(row)
        self.linear_reverse = QtWidgets.QCheckBox("Reverse")
        self.linear_reverse.setObjectName("FW_LinearReverse")
        self.linear_reverse.toggled.connect(self._linear_changed)
        col.addWidget(self.linear_reverse)
        lay.addWidget(self.linear_box)
        self.linear_box.hide()

    def _linear_set(self, r1=1.0, r2=1.0, reverse=False, refs=("", "")):
        for box, v in zip(self.linear_ratio, (r1, r2)):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
        self.linear_reverse.blockSignals(True)
        self.linear_reverse.setChecked(reverse)
        self.linear_reverse.blockSignals(False)
        self.linear_refs = list(refs)
        for w, name in zip(self.linear_ref_lists, refs):
            w.clear()
            comp = self.doc.getObject(name) if name else None
            if comp is not None:
                w.addItem(_pick_name(comp.Label))

    def _linear_start(self):
        """Linear/Linear Coupler chosen for the two picks: the default mate goes; the coupler
        counts each one's travel from where it is now."""
        import UtilsAssembly
        refs = list(self.refs)
        old = self.pending
        if old is not None and ac.mate_type(old) != asmcoupler.KIND:
            name = old.Name
            self.pending = None
            self.doc.removeObject(name)
            if getattr(self, "start", None):
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        self._linear_set()
        joint, problem = asmcoupler.make(self.asm, refs[0], refs[1])
        self.kind = asmcoupler.KIND
        if joint is not None:
            self.pending = joint
        self._show_kind()
        self._error_text(problem or "")

    def _linear_values(self):
        return dict(r1=self.linear_ratio[0].value(), r2=self.linear_ratio[1].value(),
                    reverse=self.linear_reverse.isChecked(), references=tuple(self.linear_refs))

    def _linear_changed(self, *args):
        joint = self.pending or self.editing
        if self.kind != asmcoupler.KIND or joint is None or ac.mate_type(joint) != asmcoupler.KIND:
            return
        r1, r2 = asmcoupler.refs_of(joint)
        _j, problem = asmcoupler.make(self.asm, r1, r2, joint=joint, **self._linear_values())
        self._error_text(problem or "")

    def _linear_pick(self, ref):
        """With the coupler made, the next picks fill Reference component 1, then 2."""
        for i, w in enumerate(self.linear_ref_lists):
            if not self.linear_refs[i]:
                self.linear_refs[i] = ref[0].Name
                w.addItem(_pick_name(ref[0].Label))
                self._linear_changed()
                return

    # ------------------------------------------------------------------------- Path Mate
    def _path_fields(self, lay):
        ""



        self.path_vertex, self.path_edges, self.path_upref = None, [], None
        self.path_box = QtWidgets.QWidget()
        self.path_box.setObjectName("FW_PathFields")
        col = QtWidgets.QVBoxLayout(self.path_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        lists = []
        for label, name, rows in (("Component vertex:", "FW_PathVertex", 1), ("Path selection:", "FW_PathSelection", 3)):
            col.addWidget(QtWidgets.QLabel(label))
            w = QtWidgets.QListWidget()
            w.setObjectName(name)
            w.setStyleSheet(PICK_STYLE)
            w.setFixedHeight(_rows(w, rows))
            col.addWidget(w)
            lists.append(w)
        self.path_vertex_list, self.path_list = lists
        self.path_manager = QtWidgets.QPushButton("SelectionManager")
        self.path_manager.setObjectName("FW_PathSelectionManager")
        self.path_manager.setToolTip("Select the path's edges in a chain (Select Closed Loop)")
        self.path_manager.clicked.connect(self._path_loop)
        col.addWidget(self.path_manager)
        col.addWidget(QtWidgets.QLabel("Path Constraint:"))
        self.path_mode = QtWidgets.QComboBox()
        self.path_mode.setObjectName("FW_PathConstraint")
        for text in asmpath.MODES:
            self.path_mode.addItem(asmpath.LABELS.get(text, text), text)
        col.addWidget(self.path_mode)
        row = QtWidgets.QHBoxLayout()
        self.path_value = QtWidgets.QDoubleSpinBox()
        self.path_value.setObjectName("FW_PathValue")
        self.path_value.setDecimals(2)
        row.addWidget(self.path_value, 1)
        self.path_flip = QtWidgets.QCheckBox("Flip dimension")
        self.path_flip.setObjectName("FW_PathFlip")
        row.addWidget(self.path_flip)
        col.addLayout(row)
        self.path_axes = {}
        for key, title, items in (("pitch", "Pitch/Yaw Control:", asmpath.PITCH), ("roll", "Roll Control:", asmpath.ROLL)):
            title_label = QtWidgets.QLabel(title)
            col.addWidget(title_label)
            combo = QtWidgets.QComboBox()
            combo.setObjectName("FW_Path%s" % key.capitalize())
            for text in items:
                combo.addItem(text, text)
            col.addWidget(combo)
            if key == "roll":
                self.path_up_label = QtWidgets.QLabel("Up vector:")
                col.addWidget(self.path_up_label)
                self.path_up_list = QtWidgets.QListWidget()
                self.path_up_list.setObjectName("FW_PathUpVector")
                self.path_up_list.setStyleSheet(PICK_STYLE)
                self.path_up_list.setFixedHeight(_rows(self.path_up_list, 1))
                col.addWidget(self.path_up_list)
            axes = QtWidgets.QHBoxLayout()
            group = QtWidgets.QButtonGroup(self.path_box)
            buttons = {}
            for a in asmpath.AXES:
                b = QtWidgets.QRadioButton(a)
                b.setObjectName("FW_Path%s%s" % (key.capitalize(), a))
                group.addButton(b)
                axes.addWidget(b)
                buttons[a] = b
                b.toggled.connect(self._path_changed)
            buttons["X" if key == "pitch" else "Y"].setChecked(True)
            flip = QtWidgets.QCheckBox("Flip")
            flip.setObjectName("FW_Path%sFlip" % key.capitalize())
            flip.toggled.connect(self._path_changed)
            axes.addWidget(flip)
            col.addLayout(axes)
            self.path_axes[key] = {"combo": combo, "axes": buttons, "flip": flip, "label": title_label}
            combo.currentIndexChanged.connect(lambda *_a: self._path_mode_changed())
        lay.addWidget(self.path_box)
        self.path_box.hide()
        self.path_mode.currentIndexChanged.connect(lambda *_a: self._path_mode_changed(reset=True))
        self.path_value.valueChanged.connect(self._path_changed)
        self.path_flip.toggled.connect(self._path_changed)
        self._path_mode_changed(remake=False)

    def _path_settings(self):
        out = {"mode": self.path_mode.currentData(), "value": self.path_value.value(),
               "flip": self.path_flip.isChecked()}
        for key, f in self.path_axes.items():
            out[key] = f["combo"].currentData()
            out[key + "_axis"] = next((a for a, b in f["axes"].items() if b.isChecked()), "X")
            out[key + "_flip"] = f["flip"].isChecked()
        return out

    def _path_widgets(self):
        out = [self.path_mode, self.path_value, self.path_flip]
        for f in self.path_axes.values():
            out += [f["combo"], f["flip"]] + list(f["axes"].values())
        return out

    def _path_mode_changed(self, *args, remake=True, reset=False):
        mode = self.path_mode.currentData()
        self.path_value.blockSignals(True)
        on = mode != "Free"
        self.path_value.setVisible(on)
        self.path_flip.setVisible(on)
        self.path_value.setSuffix("%" if mode == "Along Path Percent" else "mm")
        self.path_value.setRange(0.0, 100.0 if mode == "Along Path Percent" else 1.0e6)
        if reset:
            self.path_value.setValue(50.0 if mode == "Along Path Percent" else 0.0)
        self.path_value.blockSignals(False)
        follow = self.path_axes["pitch"]["combo"].currentData() == "Follow Path"

        for b in list(self.path_axes["pitch"]["axes"].values()) + [self.path_axes["pitch"]["flip"]]:
            b.setVisible(follow)
        roll = self.path_axes["roll"]
        roll["combo"].setVisible(follow)
        roll["label"].setVisible(follow)
        up = follow and roll["combo"].currentData() in ("Up Vector", "Along Path")
        for b in list(roll["axes"].values()) + [roll["flip"]]:
            b.setVisible(up)
        vec = follow and roll["combo"].currentData() == "Up Vector"
        self.path_up_list.setVisible(vec)
        self.path_up_label.setVisible(vec)
        if remake:
            self._path_changed()

    def _path_set(self, v):
        ws = self._path_widgets()
        for w in ws:
            w.blockSignals(True)
        self.path_mode.setCurrentIndex(max(0, self.path_mode.findData(v["mode"])))
        self.path_value.setRange(0.0, 100.0 if v["mode"] == "Along Path Percent" else 1.0e6)
        self.path_value.setValue(v["value"])
        self.path_flip.setChecked(v["flip"])
        for key in ("pitch", "roll"):
            f = self.path_axes[key]
            f["combo"].setCurrentIndex(max(0, f["combo"].findData(v[key])))
            f["axes"][v[key + "_axis"]].setChecked(True)
            f["flip"].setChecked(v[key + "_flip"])
        for w in ws:
            w.blockSignals(False)
        self._path_mode_changed(remake=False)

    def _path_start(self, seed=()):
        """Path Mate chosen: the next picks fill Component vertex (a vertex) and Path selection
        (edges of one other component); with Up Vector on, a face or edge fills Up vector."""
        import UtilsAssembly
        old = self.pending
        if old is not None and ac.mate_type(old) != "Path Mate":
            name = old.Name
            self.pending = None
            self.doc.removeObject(name)
            if getattr(self, "start", None):
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        self.kind = "Path Mate"
        self.path_vertex, self.path_edges, self.path_upref = None, [], None
        for w in (self.path_vertex_list, self.path_list, self.path_up_list):
            w.clear()
        self._path_set(asmpath.values(None))
        self._show_kind()
        for ref in seed:
            self._path_pick(ref)

    def _path_name(self, ref):
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Edge"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.names[ref] = "%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label))
        return self.names[ref]

    def _path_pick(self, ref):
        roll = self.path_axes["roll"]
        if self.path_vertex is not None and self.path_edges and roll["combo"].currentData() == "Up Vector" \
                and self.path_upref is None and not asmpath.is_vertex(ref):
            g = ac.geometry(ac.element(*ref))
            if g is not None and g[0] in ("plane", "line", "axis"):
                self.path_upref = ref
                self.path_up_list.addItem(self._path_name(ref))
                self._path_changed()
            return
        if asmpath.is_vertex(ref) and self.path_vertex is None:
            if self.path_edges and self.path_edges[0][0] is ref[0]:
                return      # the vertex is on the moving component, the path on another
            self.path_vertex = ref
            self.path_vertex_list.addItem(self._path_name(ref))
        elif asmpath.is_edge(ref) and ref not in self.path_edges:
            if self.path_edges and self.path_edges[0][0] is not ref[0]:
                return      # the whole path on one component
            if self.path_vertex is not None and self.path_vertex[0] is ref[0]:
                return
            self.path_edges.append(ref)
            self.path_list.addItem(self._path_name(ref))
        else:
            return
        self._path_make()

    def _path_loop(self):
        """SelectionManager > Select Closed Loop: the edges chained to the picked ones on their
        component (tangent or not), added to Path selection."""
        if not self.path_edges:
            return
        comp = self.path_edges[0][0]
        prefix = ac._prefix(self.path_edges[0][1])
        have = {e for _c, e in self.path_edges}
        shapes = [ac.element(comp, e) for _c, e in self.path_edges]
        grew = True
        while grew:
            grew = False
            ends = [v.Point for s in shapes for v in (s.Vertexes[0], s.Vertexes[-1])]
            for i in range(1, 10000):
                name = "%sEdge%d" % (prefix, i)
                if name in have:
                    continue
                e = ac.element(comp, name)
                if e is None:
                    break
                if e.ShapeType != "Edge":
                    continue
                a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
                touching = [p for p in ends if (p - a).Length < 1e-6 or (p - b).Length < 1e-6]
                # a loop: continue only from an end that no picked edge has shared yet
                free = [p for p in ends if sum(1 for q in ends if (q - p).Length < 1e-6) == 1]
                if any((p - a).Length < 1e-6 or (p - b).Length < 1e-6 for p in free) and touching:
                    have.add(name)
                    shapes.append(e)
                    self.path_edges.append((comp, name))
                    self.path_list.addItem(self._path_name((comp, name)))
                    grew = True
                    break
        self._path_make()

    def _path_make(self):
        if self.path_vertex is None or not self.path_edges:
            return
        if self.pending is None:
            self.doc.openTransaction("Mate")
        joint = self.pending if self.pending is not None and ac.mate_type(self.pending) == "Path Mate" else None
        self.pending, problem = asmpath.make(self.asm, self.path_vertex, self.path_edges, self._path_settings(),
                                             joint=joint, up=self.path_upref or ())
        if self.pending is not None:
            self.refs = [(self.pending.Reference1[0], self.pending.Reference1[1][0]),
                         (self.pending.Reference2[0], self.pending.Reference2[1][0])]
            self._list()
            self._title(self.pending.Label)
        self._error_text(problem or "")

    def _path_changed(self, *args):
        joint = self.pending or self.editing
        if self.kind != "Path Mate" or joint is None or ac.mate_type(joint) != "Path Mate":
            return
        vertex, edges = asmpath.refs_of(joint)
        _j, problem = asmpath.make(self.asm, vertex, edges, self._path_settings(), joint=joint,
                                   up=self.path_upref if self.path_upref else None)
        self._error_text(problem or "")

    def _path_load(self, joint):
        vertex, edges = asmpath.refs_of(joint)
        self.path_vertex, self.path_edges = vertex, edges
        up = getattr(joint, asmpath.UP_PROP, None)
        self.path_upref = (up[0], up[1][0]) if up and up[0] is not None and up[1] else None
        for w in (self.path_vertex_list, self.path_list, self.path_up_list):
            w.clear()
        self.path_vertex_list.addItem("%s@%s" % (vertex[1], _pick_name(vertex[0].Label)))
        for comp, elem in edges:
            self.path_list.addItem("%s@%s" % (elem, _pick_name(comp.Label)))
        if self.path_upref:
            self.path_up_list.addItem("%s@%s" % (self.path_upref[1], _pick_name(self.path_upref[0].Label)))
        self._path_set(asmpath.values(joint))

    def _profile_set(self, offset=0.0, flip=False, lock=False):
        for w, v in ((self.profile_offset, offset), (self.profile_flip, flip), (self.profile_lock, lock)):
            w.blockSignals(True)
            if w is self.profile_offset:
                w.setValue(v)
            else:
                w.setChecked(v)
            w.blockSignals(False)

    def _coupler_fields(self, lay, kind):
        ""

        if not hasattr(self, "couplers"):
            self.couplers = {}
        key = kind.replace(" ", "")
        box = QtWidgets.QWidget()
        box.setObjectName("FW_%sFields" % key)
        col = QtWidgets.QVBoxLayout(box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        modes = QtWidgets.QButtonGroup(box)
        radios = {}
        for mode, label, unit in COUPLER_MODES[kind]:
            r = QtWidgets.QRadioButton(label)
            r.setObjectName("FW_%s_%s" % (key, mode))
            modes.addButton(r)
            col.addWidget(r)
            radios[mode] = r
        value = QtWidgets.QDoubleSpinBox()
        value.setObjectName("FW_%sValue" % key)
        value.setRange(0.0001, 1.0e6)
        value.setDecimals(4 if kind == "Screw" else 2)
        col.addWidget(value)
        reverse = QtWidgets.QCheckBox("Reverse")
        reverse.setObjectName("FW_%sReverse" % key)
        col.addWidget(reverse)
        lay.addWidget(box)
        box.hide()
        self.couplers[kind] = {"box": box, "radios": radios, "value": value, "reverse": reverse,
                               "values": {}}
        radios[COUPLER_FIRST[kind]].setChecked(True)
        self._coupler_unit(kind)
        for r in radios.values():
            r.toggled.connect(lambda on, k=kind: on and self._coupler_mode(k))
        value.valueChanged.connect(self._value_changed)
        reverse.toggled.connect(self._value_changed)

    def _coupler_mode_of(self, kind):
        c = self.couplers[kind]
        return next(m for m, r in c["radios"].items() if r.isChecked())

    def _coupler_unit(self, kind):
        c = self.couplers[kind]
        mode = self._coupler_mode_of(kind)
        unit = dict((m, u) for m, _, u in COUPLER_MODES[kind])[mode]
        c["value"].setSuffix(unit)

    def _coupler_mode(self, kind):
        ""
        c = self.couplers[kind]
        old = c.get("mode", COUPLER_FIRST[kind])
        new = self._coupler_mode_of(kind)
        v = c["value"].value()
        if old != new and v > 0:
            if kind == "Rack Pinion":
                v = v * math.pi if new == "travel" else v / math.pi     # travel per turn = pi * diameter
            else:
                v = 1.0 / v                                             # revolutions/mm = 1 / (mm per turn)
        c["mode"] = new
        c["value"].blockSignals(True)
        self._coupler_unit(kind)
        c["value"].setValue(v)
        c["value"].blockSignals(False)
        self._value_changed()

    def _coupler_defaults(self, kind):
        c = self.couplers[kind]
        if kind == "Rack Pinion":
            v = ac.pinion_diameter(*self.shapes()) if len(self.refs) == 2 else 10.0
        else:
            v = 1.0
        for w in list(c["radios"].values()) + [c["value"], c["reverse"]]:
            w.blockSignals(True)
        c["radios"][COUPLER_FIRST[kind]].setChecked(True)
        c["mode"] = COUPLER_FIRST[kind]
        self._coupler_unit(kind)
        c["value"].setValue(v)
        c["reverse"].setChecked(False)
        for w in list(c["radios"].values()) + [c["value"], c["reverse"]]:
            w.blockSignals(False)

    def _coupler_load(self, kind, joint):
        c = self.couplers[kind]
        text = getattr(joint, ac.VALUE_PROP, "") or ""
        try:
            mode, number = text.split()[0], float(text.split()[1])
        except (IndexError, ValueError):
            mode = COUPLER_FIRST[kind]
            size = abs(float(getattr(joint, "Distance", 1.0)))
            number = size * 2.0 if kind == "Rack Pinion" else size
        for w in list(c["radios"].values()) + [c["value"], c["reverse"]]:
            w.blockSignals(True)
        c["radios"][mode].setChecked(True)
        c["mode"] = mode
        self._coupler_unit(kind)
        c["value"].setValue(number)
        c["reverse"].setChecked(float(getattr(joint, "Distance", 1.0)) < 0)
        for w in list(c["radios"].values()) + [c["value"], c["reverse"]]:
            w.blockSignals(False)

    def _hinge_fields(self, lay):
        ""

        self.hinge_planes = []
        self.hinge_box = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(self.hinge_box)
        col.setContentsMargins(28, 0, 0, 0)
        col.setSpacing(2)
        col.addWidget(QtWidgets.QLabel("Coincident Selections:"))
        self.hinge_list = QtWidgets.QListWidget()
        self.hinge_list.setObjectName("FW_HingeCoincident")
        self.hinge_list.setStyleSheet(PICK_STYLE)
        self.hinge_list.setFixedHeight(_rows(self.hinge_list, 2))
        self.hinge_list.setToolTip("Pick a flat face on each component")
        col.addWidget(self.hinge_list)
        self.hinge_limits = QtWidgets.QCheckBox("Specify angle limits")
        self.hinge_limits.setObjectName("FW_HingeLimits")
        self.hinge_limits.toggled.connect(self._hinge_limits_changed)
        col.addWidget(self.hinge_limits)
        self.hinge_angle_label = QtWidgets.QLabel("Angle Selections:")
        col.addWidget(self.hinge_angle_label)
        self.hinge_angle = QtWidgets.QListWidget()
        self.hinge_angle.setObjectName("FW_HingeAngle")
        self.hinge_angle.setStyleSheet(PICK_STYLE)
        self.hinge_angle.setFixedHeight(_rows(self.hinge_angle, 2))
        self.hinge_angle.setToolTip("Pick a face on each component: the angle is measured between them")
        col.addWidget(self.hinge_angle)
        self.hinge_angle_refs = []
        form = QtWidgets.QFormLayout()
        self.hinge_max, self.hinge_min = [], []
        for label, name, value in (("Maximum:", "FW_HingeMax", 90.0), ("Minimum:", "FW_HingeMin", 0.0)):
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName(name)
            box.setRange(-360.0, 360.0)
            box.setDecimals(2)
            box.setSuffix("deg")
            box.setValue(value)
            box.valueChanged.connect(self._hinge_limits_changed)
            form.addRow(label, box)
            box.setVisible(False)           # shown with Specify angle limits (not greyed)
            form.labelForField(box).setVisible(False)
            if name == "FW_HingeMax":
                self.hinge_max = box
            else:
                self.hinge_min = box
        col.addLayout(form)
        lay.addWidget(self.hinge_box)
        self.hinge_box.hide()
        self.hinge_angle_label.hide()
        self.hinge_angle.hide()

    def _hinge_limit_values(self):
        if not self.hinge_limits.isChecked():
            return None
        return (self.hinge_min.value(), self.hinge_max.value())

    def _hinge_limits_changed(self, *args):
        on = self.hinge_limits.isChecked()
        for box in (self.hinge_max, self.hinge_min):
            box.setVisible(on)
            lab = None
            for f in (box.parentWidget().findChildren(QtWidgets.QLabel) if box.parentWidget() is not None else []):
                if f.buddy() is box:
                    lab = f
            if lab is not None:
                lab.setVisible(on)
        self.hinge_angle_label.setVisible(on)
        self.hinge_angle.setVisible(on)
        joint = self.pending or self.editing
        if on and 0 < len(self.hinge_angle_refs) < 2:
            return      # the limits are the angle between the Angle Selections: wait for the second face
        if joint is not None and ac.mate_type(joint) == "Hinge" and joint.JointType == "Revolute":
            ac.hinge_limits(joint, self._hinge_limit_values(), self.hinge_angle_refs or None)
            if on and not self.hinge_angle_refs:
                return  # typed before the Angle Selections: nothing turns yet (the values are their angle)
            ac.solve(self.asm)

    def _hinge_angle_pick(self, ref):
        ""

        comps = [r[0] for r in self.refs]
        g = ac.geometry(ac.element(*ref))
        if ref[0] not in comps or g is None or g[0] != "plane" \
                or any(c is ref[0] for c, _e in self.hinge_angle_refs) or len(self.hinge_angle_refs) >= 2:
            return
        self.hinge_angle_refs.append(ref)
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.hinge_angle.addItem("%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label)))
        if len(self.hinge_angle_refs) == 2:
            self._hinge_limits_changed()

    def _hinge_pick(self, ref):
        """A flat face for Coincident Selections: one on each of the two components."""
        comps = [r[0] for r in self.refs]
        shape = ac.element(*ref)
        g = ac.geometry(shape)
        if len(self.hinge_planes) == 2 and self.hinge_limits.isChecked():
            self._hinge_angle_pick(ref)
            return
        if ref[0] not in comps or g is None or g[0] != "plane" or any(c is ref[0] for c, _e in self.hinge_planes):
            return
        self.hinge_planes.append(ref)
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.hinge_list.addItem("%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label)))
        if len(self.hinge_planes) == 2:
            joint = self.pending or self.editing
            ac.make_hinge(self.asm, joint, self.hinge_planes, self._hinge_limit_values())
            self._show_kind()
            self._error(joint)

    def _type_tab(self, index):
        ""
        self._tab(1 if getattr(self, "analysis_tab", False) else 0)
        if getattr(self, "tab_block", None) is not None:
            self.tab_block.sync()

    @staticmethod
    def _task_box(w):
        box = w.parentWidget()
        while box is not None and not box.metaObject().className().endswith("TaskBox"):
            box = box.parentWidget()
        return box

    def _type_headers(self):
        """The tab row has no group title of its own; the tab's mate types are never folded."""
        try:
            self._type_headers_()
        except RuntimeError as _fw_err:
            _fw_log("asmpm.py:2703", _fw_err)

    def _type_headers_(self):
        top = self._task_box(self.tabs_box) if getattr(self, "tabs_box", None) is not None else None
        if top is not None:
            for h in top.children():
                if isinstance(h, QtWidgets.QWidget) and h.inherits("QSint::TaskHeader"):
                    h.hide()
        for w in getattr(self, "type_boxes", ()):
            box = self._task_box(w)
            if box is None:
                continue
            if box.isVisible() and not w.isVisible():
                QtCore.QMetaObject.invokeMethod(box, "showHide")    # folded in an earlier session

    def _open_box(self, widget):
        """Opens a folded PropertyManager group (Mechanical Mates when its mate is chosen)."""
        if widget in getattr(self, "type_boxes", ()):
            if not getattr(self, "analysis_tab", False):
                self.type_tabs.setCurrentIndex(self.type_boxes.index(widget))
            return
        if widget.isVisible() or not self.list.isVisible():
            return
        box = widget.parentWidget()
        while box is not None and not box.metaObject().className().endswith("ActionGroup") \
                and not box.metaObject().className().endswith("TaskBox"):
            box = box.parentWidget()
        if box is not None:
            QtCore.QMetaObject.invokeMethod(box, "showHide")

    def _fit_box(self, widget):
        """A PropertyManager group keeps the height it opened with (FreeCAD's fold animation):
        grow it to fit the fields a mechanical mate has just shown."""
        try:
            box = widget.parentWidget()
            while box is not None and not box.metaObject().className().endswith("TaskBox"):
                box = box.parentWidget()
            if box is None or not widget.isVisible():
                return
            want = box.sizeHint().height()
            if box.height() < want or box.minimumHeight() > want:
                box.setMinimumHeight(want)
                box.updateGeometry()
        except RuntimeError as _fw_err:
            _fw_log("asmpm.py:2747", _fw_err)

    def _gear_defaults(self):
        if len(self.refs) != 2:
            return
        d1, d2 = ac.gear_diameters(*self.shapes())
        for box, d in zip(self.gear_ratio, (d1, d2)):
            box.blockSignals(True)
            box.setValue(d)
            box.blockSignals(False)
        self.gear_reverse.blockSignals(True)
        self.gear_reverse.setChecked(False)
        self.gear_reverse.blockSignals(False)

    def _header(self):
        ""

        try:
            view = self.list.window().findChild(QtWidgets.QWidget, "SWStyle_PMHeader")
        except RuntimeError:
            return              # the PropertyManager closed before the timer came
        if view is None or view.findChild(QtWidgets.QToolButton, "FW_MateUndo") is not None:
            return
        row = getattr(view, "row", None)
        if row is None:
            return
        undo = QtWidgets.QToolButton(view)
        undo.setObjectName("FW_MateUndo")
        undo.setAutoRaise(True)
        undo.setIcon(_std_icon("Std_Undo", "STANDARD_UNDO"))
        undo.setIconSize(QtCore.QSize(_px(16), _px(16)))
        undo.setToolTip("Undo")
        undo.clicked.connect(self.undo)
        row.insertWidget(row.count() - 1, undo)
        page_owned(view, undo)
        self.pin = QtWidgets.QToolButton(view)
        self.pin.setObjectName("FW_MatePin")
        self.pin.setCheckable(True)
        self.pin.setChecked(True)
        self.pin.setToolTip("Keep Visible")
        try:
            from . import propertymanager as pm
            self.pin.setIcon(pm._drawn("PIN_ACTIVE"))
            self.pin.toggled.connect(lambda on: self.pin.setIcon(pm._drawn("PIN_ACTIVE" if on else "PIN_NORMAL")))
        except Exception:
            self.pin.setText("pin")
        self.pin.setIconSize(QtCore.QSize(_px(16), _px(16)))
        t = _tokens()
        self.pin.setStyleSheet("QToolButton { border: 1px solid transparent; background: transparent; }"
                               " QToolButton:checked { background: %s; border-color: %s; }"
                               % (t["down"], t["down_line"]))
        row.insertWidget(row.count() - 1, self.pin)
        page_owned(view, self.pin)
        outer = view.layout()
        if outer is not None:
            tabs = QtWidgets.QTabBar(view)
            tabs.setObjectName("FW_MateTabs")
            tabs.setDrawBase(False)
            tabs.setExpanding(False)
            tabs.addTab(sw_icon("Coincident"), "Mates")
            tabs.addTab(sw_icon("Multiple"), "Analysis")
            tabs.currentChanged.connect(self._tab)
            tabs.currentChanged.connect(lambda _i: getattr(self, "tab_block", None) and self.tab_block.sync())
            tabs.hide()                   # its Mates / Analysis pages are in the four-tab block (_TabBlock)
            tabs.setStyleSheet(
                "QTabBar::tab { background: %(pane)s; color: %(text)s; border: 1px solid %(line_mid)s;"
                " padding: 2px 8px; margin-right: 1px; }"
                " QTabBar::tab:selected { background: %(base)s; border-bottom-color: %(base)s; }"
                " QTabBar::tab:disabled { color: %(text_disabled)s; }" % _tokens())
            outer.addWidget(tabs, 0, Qt.AlignLeft)
            page_owned(view, tabs)

    # ------------------------------------------------------------ the Analysis tab
    def _analysis_boxes(self):
        ""

        from . import asmphysics as ph
        out = []


        mb, lay = _box("Message")
        self.analysis_message = QtWidgets.QLabel(ANALYSIS_MESSAGE)
        self.analysis_message.setObjectName("FW_MateAnalysisMessage")
        self.analysis_message.setWordWrap(True)
        lay.addWidget(self.analysis_message)
        out.append(mb)
        self.analysis_note_box = mb
        lb, lay = _box("Load Bearing Faces")
        self.load_faces = QtWidgets.QListWidget()
        self.load_faces.setObjectName("FW_MateLoadFaces")
        self.load_faces.setStyleSheet(PICK_STYLE)
        self.load_faces.setFixedHeight(_rows(self.load_faces, 3))
        lay.addWidget(self.load_faces)
        self.isolate_comps = QtWidgets.QCheckBox("Isolate components")
        self.isolate_comps.setObjectName("FW_MateIsolate")
        self.isolate_comps.toggled.connect(self._isolate)
        lay.addWidget(self.isolate_comps)
        out.append(lb)
        fb, lay = _box("Friction")
        self.friction_on = QtWidgets.QCheckBox("Friction")
        self.friction_on.setObjectName("FW_MateFriction")
        lay.addWidget(self.friction_on)
        self.fric_materials = QtWidgets.QRadioButton("Specify materials")
        self.fric_materials.setObjectName("FW_MateFrictionMaterials")
        self.fric_coef = QtWidgets.QRadioButton("Specify friction coefficient")
        self.fric_coef.setObjectName("FW_MateFrictionCoefficient")
        self.fric_materials.setChecked(True)
        lay.addWidget(self.fric_materials)
        self.mat1 = QtWidgets.QComboBox()
        self.mat1.setObjectName("FW_MateMaterial1")
        self.mat2 = QtWidgets.QComboBox()
        self.mat2.setObjectName("FW_MateMaterial2")
        for c in (self.mat1, self.mat2):
            c.addItems(list(ph.MATERIALS))
            lay.addWidget(c)
        lay.addWidget(self.fric_coef)
        self.mu = QtWidgets.QDoubleSpinBox()
        self.mu.setObjectName("FW_MateMu")
        self.mu.setRange(0.0, 2.0)
        self.mu.setDecimals(3)
        self.mu.setSingleStep(0.01)
        self.mu.setValue(ph.friction(ph.MATERIALS[0], ph.MATERIALS[0]))
        lay.addWidget(self.mu)
        row = QtWidgets.QHBoxLayout()
        self.mu_ends = (QtWidgets.QLabel("Slippery"), QtWidgets.QLabel("Sticky"))
        row.addWidget(self.mu_ends[0])
        self.mu_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.mu_slider.setObjectName("FW_MateMuSlider")
        self.mu_slider.setRange(0, 200)
        self.mu_slider.setValue(int(round(self.mu.value() * 100)))
        row.addWidget(self.mu_slider, 1)
        row.addWidget(self.mu_ends[1])
        lay.addLayout(row)
        self.mu_slider.valueChanged.connect(lambda n: abs(self.mu.value() * 100 - n) >= 0.5 and self.mu.setValue(n / 100.0))
        self.mu.valueChanged.connect(self._mu_slider_sync)
        out.append(fb)
        bb, lay = _box("Bushing")
        self.bushing_on = QtWidgets.QCheckBox("Bushing")
        self.bushing_on.setObjectName("FW_MateBushing")
        lay.addWidget(self.bushing_on)
        self.isotropic = QtWidgets.QCheckBox("Isotropic")
        self.isotropic.setObjectName("FW_MateIsotropic")
        self.isotropic.setChecked(True)
        lay.addWidget(self.isotropic)
        form = QtWidgets.QFormLayout()
        self.bush_form = form
        self.bush_heads = []
        self.bush = {}

        for key, label, suffix, value in (("k", "Translational stiffness:", " N/mm", 100.0),
                                          ("c", "Translational damping:", " N/(mm/s)", 1.0),
                                          ("p", "Preload force:", " N", 0.0),
                                          ("kt", "Torsional stiffness:", " N*mm/deg", 10.0),
                                          ("ct", "Torsional damping:", " N*mm/(deg/s)", 0.1),
                                          ("pt", "Preload torque:", " N*mm", 0.0)):
            if key in ("k", "kt"):
                head = QtWidgets.QLabel("Translational" if key == "k" else "Torsional")
                self.bush_heads.append(head)
                form.addRow(head)
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName("FW_MateBushing_" + key)
            box.setRange(-1.0e9 if key in ("p", "pt") else 0.0, 1.0e9)
            box.setDecimals(3)
            box.setSuffix(suffix)
            box.setValue(value)
            form.addRow(label, box)
            self.bush[key] = box
        lay.addLayout(form)
        out.append(bb)
        for w in (self.friction_on, self.fric_materials, self.fric_coef, self.bushing_on, self.isotropic):
            w.toggled.connect(lambda *_: self._analysis_changed())
        for w in (self.mat1, self.mat2):
            w.currentIndexChanged.connect(lambda *_: self._analysis_changed(materials=True))
        self.mu.valueChanged.connect(lambda *_: self._analysis_changed())
        for box in self.bush.values():
            box.valueChanged.connect(lambda *_: self._analysis_changed())
        self.load_refs = []
        self.analysis_tab = False
        self._analysis_enable()
        return out

    def _mu_slider_sync(self, *args):
        self.mu_slider.blockSignals(True)
        self.mu_slider.setValue(int(round(self.mu.value() * 100)))
        self.mu_slider.blockSignals(False)

    def _analysis_enable(self):
        self._mu_slider_sync()

        on = self.friction_on.isChecked()
        for w in (self.fric_materials, self.fric_coef):
            w.setVisible(on)
        self.mat1.setVisible(on and self.fric_materials.isChecked())
        self.mat2.setVisible(on and self.fric_materials.isChecked())
        coef = on and self.fric_coef.isChecked()
        for w in (self.mu, self.mu_slider) + self.mu_ends:
            w.setVisible(coef)
        b = self.bushing_on.isChecked()
        self.isotropic.setVisible(b)
        for w in self.bush_heads:
            w.setVisible(b)
        for box in self.bush.values():
            box.setVisible(b)
            lab = self.bush_form.labelForField(box)
            if lab is not None:
                lab.setVisible(b)

    def _tab(self, index):
        """Mates / Analysis: the PropertyManager shows the tab's groups."""
        self.analysis_tab = index == 1
        current = self.type_boxes[self.type_tabs.currentIndex()] if getattr(self, "type_boxes", None) else None
        boxes = {}
        for w in self.mate_boxes:
            group = w.parentWidget()
            show = not self.analysis_tab and (current is None or w not in self.type_boxes or w is current)
            if w is getattr(self, "tabs_box", None):
                show = True               # the four-tab block stays on the Analysis tab too
            # pkg312: the title bars too (Mate Selections, Mates, Options showed as empty folded boxes

            box = self._task_box(w)
            if box is not None:
                boxes[box] = boxes.get(box, False) or show
            else:       # asmpkg358: a group's rows alone are hidden only without a title bar (a fold to the PM's fold memory)
                (group if group is not None else w).setVisible(show)
        for box, show in boxes.items():
            box.setVisible(show)
        if not self.analysis_tab and current is not None:
            QtCore.QTimer.singleShot(0, self._type_headers)
        has_mate = (self.pending or self.editing) is not None
        for w in self.analysis_boxes:
            note = w is getattr(self, "analysis_note_box", None)
            on = self.analysis_tab and (note != has_mate)    # asmpkg348: the Message alone until there is a mate
            group = w.parentWidget()
            box = self._task_box(w)     # its title bar too: Friction / Bushing showed on the Mates tab
            if box is not None:
                box.setVisible(on)
            else:
                (group if group is not None else w).setVisible(on)
        if self.analysis_tab:
            self._analysis_load(self.pending or self.editing)

    def _analysis_values(self):
        import json
        from . import asmphysics as ph
        return json.dumps({"load_faces": ["%s|%s" % (c.Name, e) for c, e in self.load_refs],
                           "friction": self.friction_on.isChecked(),
                           "mode": "materials" if self.fric_materials.isChecked() else "coefficient",
                           "mat1": self.mat1.currentText(), "mat2": self.mat2.currentText(),
                           "mu": self.mu.value(), "bushing": self.bushing_on.isChecked(),
                           "isotropic": self.isotropic.isChecked(),
                           **{k: b.value() for k, b in self.bush.items()}})

    def _analysis_changed(self, materials=False):
        from . import asmphysics as ph
        if materials or self.fric_materials.isChecked():
            self.mu.blockSignals(True)
            self.mu.setValue(ph.friction(self.mat1.currentText(), self.mat2.currentText()))
            self.mu.blockSignals(False)
        self._analysis_enable()
        joint = self.pending or self.editing
        if joint is None:
            return
        if not hasattr(joint, ph.ANALYSIS_PROP):
            joint.addProperty("App::PropertyString", ph.ANALYSIS_PROP, "FreeCAD", "The mate's Analysis tab")
            joint.setPropertyStatus(ph.ANALYSIS_PROP, "Hidden")
        setattr(joint, ph.ANALYSIS_PROP, self._analysis_values())

    def _analysis_load(self, joint):
        import json
        from . import asmphysics as ph
        try:
            v = json.loads(getattr(joint, ph.ANALYSIS_PROP, "") or "{}") if joint is not None else {}
        except ValueError:
            v = {}
        widgets = [self.friction_on, self.fric_materials, self.fric_coef, self.mat1, self.mat2, self.mu,
                   self.bushing_on, self.isotropic] + list(self.bush.values())
        for w in widgets:
            w.blockSignals(True)
        self.friction_on.setChecked(bool(v.get("friction")))
        (self.fric_coef if v.get("mode") == "coefficient" else self.fric_materials).setChecked(True)
        if v.get("mat1"):
            self.mat1.setCurrentText(v["mat1"])
        if v.get("mat2"):
            self.mat2.setCurrentText(v["mat2"])
        if "mu" in v:
            self.mu.setValue(v["mu"])
        self.bushing_on.setChecked(bool(v.get("bushing")))
        self.isotropic.setChecked(v.get("isotropic", True))
        for k, b in self.bush.items():
            if k in v:
                b.setValue(v[k])
        for w in widgets:
            w.blockSignals(False)
        comps = {c.Name: c for c in ac.components(self.asm)}
        self.load_refs = []
        self.load_faces.clear()
        for item in v.get("load_faces", []):
            name, _bar, elem = item.partition("|")
            if name in comps:
                self.load_refs.append((comps[name], elem))
                self.load_faces.addItem("%s@%s" % (elem.split(".")[-1], _pick_name(comps[name].Label)))
        self._analysis_enable()

    def _isolate(self, on):
        """Isolate components: only the mate's two components show while load faces are picked."""
        refs = [r[0] for r in self.refs] if self.refs else []
        for c in ac.components(self.asm):
            if c in refs:
                continue
            if on and c.Visibility:
                c.Visibility = False
                self._isolated = getattr(self, "_isolated", []) + [c]
            elif not on and c in getattr(self, "_isolated", []):
                c.Visibility = True
        if not on:
            self._isolated = []

    def _load_face_pick(self, ref):
        refs = [r[0] for r in self.refs] if self.refs else []
        if ref[0] not in refs or ref in self.load_refs:
            return
        self.load_refs.append(ref)
        self.load_faces.addItem("%s@%s" % (ref[1].split(".")[-1], _pick_name(ref[0].Label)))
        self._analysis_changed()

    # ------------------------------------------------------------ picks
    def _preselected(self):
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames:
                self._pick(sel.Object, sub)

    def _gone(self):
        """The PM was closed without OK or Cancel (Gui.Control.closeDialog): stop listening."""
        from .widgets import alive
        if alive(self.form if not isinstance(self.form, list) else self.form[0]):
            return False
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmpm.py:3052", _fw_err)
        return True

    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name or self._gone():
            return
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        if sub and not sub.endswith(".") and (obj, sub) not in getattr(self, "_held", ()):
            self._last_added = (obj, sub)   # the element a following whole-component re-click is on
        from . import safe_later as _sl; _sl.later(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub)), self, "uj_define")

    def removeSelection(self, doc, obj, sub):
        if doc != self.doc.Name or getattr(self, "_unpicking", False) or self._gone():
            return
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._unpick(self.doc.getObject(obj), sub)))

    def clearSelection(self, doc):
        # FreeCAD clears the whole selection when a selected entity is clicked again (no Ctrl):

        if doc not in ("", self.doc.Name) or getattr(self, "_unpicking", False) or self._gone() or not (self.refs or getattr(self, "width_sel", None) or getattr(self, "tab_sel", None)):
            return
        import time
        self._cleared = time.monotonic()    # a pick added again right after this is a click on it again
        try:
            pre = Gui.Selection.getPreselection()
            obj, sub = pre.Object, pre.SubElementNames[0] if pre.SubElementNames else ""
        except Exception as _fw_err:
            _fw_log("asmpm.py:3102", _fw_err)
            return
        if obj is None or not sub or pre.DocumentName != self.doc.Name:
            return
        if obj is not self.asm and obj.Name + "." not in sub:
            # FreeCAD names the preselected leaf: a component's own element, as an assembly path
            comp = next((r[0] for r in self.refs if r[0] is obj), None)
            if comp is not None:
                obj, sub = self.asm, comp.Name + "." + sub
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._unpick(obj, sub)))

    def _reclick_whole(self, root, sub):
        ""

        import time
        if time.monotonic() - getattr(self, "_cleared", -10.0) >= 0.3 or self.multi:
            return False
        head = sub.split(".")[0]
        comp = self.doc.getObject(head) if root is self.asm else None
        if comp is None:
            return False
        pairs = list(zip(self.picked, self.refs))
        if self.kind == "Width" and self.pending is None:
            pairs = [((root.Name, r[0].Name + "." + r[1]), r) for r in (self.width_sel + self.tab_sel)]
        last = getattr(self, "_last_added", None)
        lref = ac.reference(self.asm, self.doc.getObject(last[0]), last[1]) if last else None
        mine = [(p, r) for p, r in pairs if r[0] is comp and r == lref]     # the element clicked again, only
        if not mine:
            return False
        self._cleared = -10.0
        try:
            Gui.Selection.removeSelection(self.doc.Name, root.Name, sub)     # not the whole component either
        except Exception as _fw_err:
            _fw_log("asmpm.py:3111", _fw_err)
        (name, psub), _r = mine[-1]
        self._unpick(self.doc.getObject(name), psub)
        return True

    def _unpick(self, root, sub):
        ""
        if root is None or not sub or self.multi or self.editing is not None or getattr(self, "analysis_tab", False):
            return
        if self.kind == "Width":
            ref = ac.reference(self.asm, root, sub)
            if ref is not None and ref in self.width_sel + self.tab_sel:
                if self.pending is not None:

                    import UtilsAssembly
                    start = getattr(self, "start", None)
                    self.pending = None
                    self.doc.abortTransaction()
                    if start:
                        UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, start)
                self._just_unpicked = ref
                QtCore.QTimer.singleShot(250, lambda: setattr(self, "_just_unpicked", None))
                self.width_sel = [r for r in self.width_sel if r != ref]
                self.tab_sel = [r for r in self.tab_sel if r != ref]
                for sel, view in ((self.width_sel, self.width_list), (self.tab_sel, self.tab_list)):
                    view.clear()
                    for r in sel[:2 if sel is self.width_sel else (1 if len(sel) == 2 and sel[0] == sel[1] else 2)]:
                        view.addItem("%s@%s" % (r[1].split(".")[-1], _pick_name(r[0].Label)))
                try:
                    from . import asmwidthtags
                    asmwidthtags.show(self)
                except Exception as _fw_err:
                    _fw_log("asmpm.py:3143", _fw_err)
            return
        if self.kind in ("Width", "Path Mate", "Symmetric", "Universal Joint", asmcoupler.KIND) or len(self.refs) > 2:
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is None or not any(r == ref for r in self.refs):
            return
        gone = [(n, sb) for (n, sb), r in zip(self.picked, self.refs) if r == ref]
        keep = [(n, sb) for (n, sb), r in zip(self.picked, self.refs) if r != ref]
        self._just_unpicked = ref
        QtCore.QTimer.singleShot(250, lambda: setattr(self, "_just_unpicked", None))
        self._unpicking = True
        try:
            if self.pending is not None:
                import UtilsAssembly
                start = getattr(self, "start", None)
                self.drop()
                if start:
                    UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, start)
            else:
                self.drop()
            for n, sb in gone:
                try:
                    Gui.Selection.removeSelection(self.doc.Name, n, sb)
                except Exception as _fw_err:
                    _fw_log("asmpm.py:3168", _fw_err)
            for n, sb in keep:
                self._pick(self.doc.getObject(n), sb)
        finally:
            self._unpicking = False

    def _pick(self, root, sub):
        if root is not None and sub and sub.endswith(".") and self._reclick_whole(root, sub):
            return
        if root is None or not sub or (self.editing is not None and not getattr(self, "analysis_tab", False)
                                       and not (self.kind == "Universal Joint" and self.uj_define.isChecked())
                                       and self.kind != "Angle"):
            return
        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return
        if self.multi:
            self._multi_pick(root, sub, ref)
            return
        if self.analysis_tab:
            self._load_face_pick(ref)
            return
        if self.kind == "Universal Joint" and self.uj_define.isChecked() and len(self.refs) == 2:
            self._ujoint_pick(ref)
            return
        if self.kind == "Hinge" and len(self.refs) == 2 and self.pending is not None:
            self._hinge_pick(ref)
            return
        if self.kind == "Width" and self.pending is None:
            import time
            if ref == getattr(self, "_just_unpicked", None):
                return
            if ref in self.width_sel + self.tab_sel and time.monotonic() - getattr(self, "_cleared", -10.0) < 0.3:
                self._cleared = -10.0
                self._unpick(root, sub)     # clicked again: out of the Width / Tab selections
                return
            self._width_pick(ref)
            return
        if self.kind == "Angle" and (self.pending or self.editing) is not None \
                and (len(self.refs) >= 2 or self.editing is not None):
            self._angle_ref_pick(ref)      # past the two entities: the Reference Direction
            return
        if self.kind == "Path Mate" and (self.pending is None or ac.mate_type(self.pending) == "Path Mate"):
            self._path_pick(ref)
            return
        if self.kind == asmcoupler.KIND and self.pending is not None and ac.mate_type(self.pending) == asmcoupler.KIND:
            if any(r == ref for r in self.refs):
                # asmpkg364: one of the two mate entities selected again (the page keeps its picks lit): not a
                # Reference component. It filled Reference component 1 with the first slider itself, so the
                # coupler measured that slider against itself and the other one never followed.
                return
            self._linear_pick(ref)
            return
        if self.kind == "Symmetric" and self.pending is None:
            self._symmetric_pick(ref)
            return
        if any(r == ref for r in self.refs):
            import time
            held = getattr(self, "_held", set())
            if (root.Name, sub) in held:
                held.discard((root.Name, sub))      # our own re-add (_hold)
            elif time.monotonic() - getattr(self, "_cleared", -10.0) < 0.3:
                self._cleared = -10.0
                self._unpick(root, sub)     # FreeCAD's plain click on a pick: clear, then the same pick
            return
        if ref == getattr(self, "_just_unpicked", None):
            return          # the click that took it out also selected it again in FreeCAD
        if len(self.refs) >= 2:
            return
        if self.refs and self.refs[0][0] == ref[0]:

            # stayed highlighted while Mate Selections did not list it), and the status bar says why
            doc_name, obj_name = self.doc.Name, root.Name
            QtCore.QTimer.singleShot(0, lambda: Gui.Selection.removeSelection(doc_name, obj_name, sub))
            Gui.getMainWindow().statusBar().showMessage(
                "Mate selections must be on two different components", 4000)
            return
        self.refs.append(ref)
        self.picked.append((root.Name, sub))
        mid = _midpoint_pick(self.doc, root, sub)
        if mid is not None:
            self.mids[tuple(ref)] = mid      # Select Midpoint: the edge picked at its middle, a point
        else:
            self.mids.pop(tuple(ref), None)
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.names[ref] = "%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label))
        if len(self.refs) == 1 and self.fade_first.isChecked():
            self._fade(ref[0], ref[1])
        self._list()
        self._hold()
        if len(self.refs) == 2:
            self._preview()

    # ------------------------------------------------------------ Multiple mate mode
    def _hold_back(self):
        """Show preview off: the mate is made but the components stay where they were till the check."""
        if self.show_preview.isChecked() or not getattr(self, "start", None):
            return
        import UtilsAssembly
        UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)

    def _multi_toggled(self, on):
        if self.pending is not None or self.multi_pending:
            self.drop()
        self.multi = bool(on)
        self.multi_box.setVisible(self.multi)
        self.list.setVisible(not self.multi)
        self._multi_clear()
        _mark_active(self.list, not self.multi)
        _mark_active(self.multi_common, self.multi)

    def _multi_clear(self):
        self.common = None
        self.multi_refs, self.multi_pending = [], []
        self.multi_common.clear()
        self.multi_list.clear()

    def _multi_name(self, ref):
        kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return "%s<%d>@%s" % (kind, self.counts[kind], _pick_name(ref[0].Label))

    def _multi_pick(self, root, sub, ref):
        ""

        if self.common is None:
            self.common = ref
            self.multi_common.addItem(self._multi_name(ref))
            self.picked.append((root.Name, sub))
            if self.fade_first.isChecked():
                self._fade(ref[0], ref[1])
            self._hold()
            return
        if ref[0] == self.common[0] or any(r == ref for r in self.multi_refs):
            return
        s1, s2 = ac.element(*self.common), ac.element(*ref)
        kinds = [k for k in ac.allowed(s1, s2, [self.common, ref]) if k in STANDARD + ("Distance", "Angle")]
        if not kinds:
            return
        if not self.multi_pending:
            import UtilsAssembly
            self.start = UtilsAssembly.saveAssemblyPartsPlacements(self.asm)
            self.doc.openTransaction("Multiple Mate")
        kind = self.kind if self.kind in kinds else (ac.first_choice(s1, s2) if ac.first_choice(s1, s2) in kinds else kinds[0])
        try:
            joint = ac.add_mate(self.asm, kind, self.common, ref, self._value(kind))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: mate not made: %s\n" % error)
            return
        if self.kind is not None and kind != self.kind:     # the others follow the new pick's type
            for j in self.multi_pending:
                ac.change_mate(self.asm, j, kind, self._value(kind), self.lock_rotation.isChecked())
        self.kind = kind
        self.multi_refs.append(ref)
        self.multi_pending.append(joint)
        self.picked.append((root.Name, sub))
        self.multi_list.addItem(self._multi_name(ref))
        self.refs = [self.common, ref]          # the type buttons and alignment look at the last pair
        self._hold_back()
        self._enable(kinds)
        self.pending = None
        self._show_kind()
        self._title("Multiple mate")
        self._hold()
        if self.show_popup.isChecked():
            self._popup(kinds)

    def _multi_keep(self):
        if not self.multi_pending:
            return []
        if not self.show_preview.isChecked():
            ac.solve(self.asm)
        self.doc.recompute()
        self.doc.commitTransaction()
        made = list(self.multi_pending)
        for j in made:
            self.kept.append(j)
            self.mates.addItem(QtWidgets.QListWidgetItem(sw_icon(ac.mate_type(j)), ac.mate_text(j)))
        self.kept_batches.append(len(made))
        if self.multi_folder.isChecked():
            from . import asmfolder
            folder = asmfolder.add_to_new_folder(made)
            if folder is not None:
                n = 1
                labels = {o.Label for o in self.doc.Objects}
                while "MultiMate%d" % n in labels:
                    n += 1
                folder.Label = "MultiMate%d" % n
        self.multi_refs, self.multi_pending = [], []
        self.multi_list.clear()
        return made

    def _hold(self):
        ""
        lit = {(s.Object.Name, n) for s in Gui.Selection.getSelectionEx(self.doc.Name, 0)
               for n in s.SubElementNames}
        held = getattr(self, "_held", None)
        if held is None:
            held = self._held = set()
        for name, sub in self.picked:
            if (name, sub) not in lit:
                held.add((name, sub))       # our own re-add, not a click on it again
                Gui.Selection.addSelection(self.doc.Name, name, sub)

    def _list(self):
        self.list.clear()
        for ref in self.refs:
            comp, element = ref
            name = self.names.get(ref)
            if name is None:
                kind = "".join(ch for ch in element.split(".")[-1] if ch.isalpha()) or "Face"
                self.counts[kind] = self.counts.get(kind, 0) + 1
                name = self.names[ref] = "%s<%d>@%s" % (kind, self.counts[kind], _pick_name(comp.Label))
            item = QtWidgets.QListWidgetItem(name)
            self.list.addItem(item)
            item.setSelected(True)

    def _fade(self, comp, element=""):
        ""





        self._unfade()
        vobj = getattr(comp, "ViewObject", None)
        if vobj is None or not hasattr(vobj, "OverrideMaterial"):
            return
        old = (vobj.OverrideMaterial, vobj.ShapeMaterial)
        try:
            source = getattr(getattr(comp, "LinkedObject", None), "ViewObject", None)
            colour = tuple((getattr(source, "ShapeColor", None) or (0.8, 0.8, 0.8))[:3])
            material = App.Material()
            material.DiffuseColor = colour
            material.Transparency = FADE_LEVEL
            vobj.ShapeMaterial = material
            vobj.OverrideMaterial = True
            self.faded = (comp, old, self._solid_pick(comp, element, colour))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: first selection not faded: %s\n" % error)

    def _solid_pick(self, comp, element, colour):
        shape = ac.element(comp, element)
        if shape is None or shape.ShapeType != "Face":
            return None
        from pivy import coin
        points, triangles = shape.tessellate(0.05)
        if not triangles:
            return None
        packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("SelectionColor", 0x0058C0FF)
        select = [((packed >> shift) & 0xFF) / 255.0 for shift in (24, 16, 8)]
        node = coin.SoSeparator()
        mat = coin.SoMaterial()
        mat.diffuseColor.setValue(*colour)
        mat.emissiveColor.setValue(*select)
        node.addChild(mat)
        offset = coin.SoPolygonOffset()
        offset.factor = -1.0
        offset.units = -1.0
        node.addChild(offset)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
        node.addChild(coords)
        faces = coin.SoIndexedFaceSet()
        index = []
        for t in triangles:
            index += [t[0], t[1], t[2], -1]
        faces.coordIndex.setValues(0, len(index), index)
        node.addChild(faces)
        root = Gui.ActiveDocument.ActiveView.getSceneGraph()
        root.addChild(node)
        return node

    def _follow_fade(self):
        """The mate may have moved the first pick's component: redraw its solid face there."""
        if self.faded is None or not self.refs:
            return
        comp, old, node = self.faded
        if node is not None:
            try:
                Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(node)
            except Exception as _fw_err:
                _fw_log("asmpm.py:3433", _fw_err)
        source = getattr(getattr(comp, "LinkedObject", None), "ViewObject", None)
        colour = tuple((getattr(source, "ShapeColor", None) or (0.8, 0.8, 0.8))[:3])
        try:
            node = self._solid_pick(comp, self.refs[0][1], colour)
        except Exception:
            node = None
        self.faded = (comp, old, node)

    def _unfade(self):
        if self.faded is not None:
            comp, (override, material), node = self.faded
            self.faded = None
            try:
                comp.ViewObject.ShapeMaterial = material
                comp.ViewObject.OverrideMaterial = override
            except Exception as _fw_err:
                _fw_log("asmpm.py:3450", _fw_err)
            if node is not None:
                try:
                    Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(node)
                except Exception as _fw_err:
                    _fw_log("asmpm.py:3455", _fw_err)

    def shapes(self):
        out = [ac.element(c, e) for c, e in self.refs]
        if self._mid_mode():
            import Part
            out = [Part.Vertex(self._mid_local(r)) if tuple(r) in self.mids else s for r, s in zip(self.refs, out)]
        return out

    def _mid_local(self, ref):
        """A Select Midpoint pick's middle in the assembly's axes (rcmenus gives it in the world's)."""
        p = self.mids[tuple(ref)]
        try:
            return self.asm.getGlobalPlacement().inverse().multVec(p)
        except Exception:
            return p

    def _mid_mode(self):
        ""


        mids = getattr(self, "mids", None) or {}
        if len(self.refs) != 2 or not any(tuple(r) in mids for r in self.refs):
            return None
        if self._point_pair():
            return "points"
        if all(tuple(r) in mids for r in self.refs):
            return None
        other = [r for r in self.refs if tuple(r) not in mids][0]
        g = ac.geometry(ac.element(*other))
        if g is None:
            return None
        if g[0] == "plane" and str(other[1]).split(".")[-1].startswith("Face"):
            return "plane"
        if g[0] == "axis":
            return "axis"
        return None

    def _mid_kinds(self, kinds):
        mode = self._mid_mode()
        if mode is None:
            return kinds
        keep = {"points": ("Coincident", "Lock"), "plane": ("Coincident", "Lock"), "axis": ("Concentric", "Lock")}[mode]
        return tuple(k for k in kinds if k in keep) or keep

    def _mate_refs(self):
        """(ref1, ref2, add_mate's extra arguments): a Select Midpoint edge with a plane or an axis is
        its start vertex with the joint frame moved to the middle (FreeCAD's solver then sees a point)."""
        r1, r2 = self.refs[0], self.refs[1]
        mode = self._mid_mode()
        if mode not in ("plane", "axis"):
            return r1, r2, {}
        out, offsets = [], {}
        for i, r in enumerate((r1, r2), 1):
            if tuple(r) not in self.mids:
                out.append(r)
                continue
            comp, sub = r
            edge = ac.element(comp, sub)
            prefix = sub.rsplit(".", 1)[0] + "." if "." in sub else ""
            whole = ac.element(comp, prefix.rstrip(".")) if prefix else getattr(comp, "Shape", None)
            v0 = edge.Vertexes[0].Point
            name = None
            for k, v in enumerate(getattr(whole, "Vertexes", []) or []):
                if (v.Point - v0).Length < 1e-7:
                    name = "%sVertex%d" % (prefix, k + 1)
                    break
            if name is None:
                return r1, r2, {}
            plc = comp.Placement
            offsets[i] = plc.Rotation.inverted().multVec(self._mid_local(r) - v0)
            out.append((comp, name))
        return out[0], out[1], {"offsets": offsets}

    def _point_pair(self):
        ""


        mids = getattr(self, "mids", None) or {}
        if len(self.refs) != 2 or not any(tuple(r) in mids for r in self.refs):
            return False
        for r in self.refs:
            if tuple(r) in mids:
                continue
            if not str(r[1]).split(".")[-1].startswith("Vertex"):
                return False
        return True

    def _ball(self):
        return self._point_pair()

    # ------------------------------------------------------------ the preview
    def _enable(self, kinds):
        picks = bool(getattr(self, "refs", None))
        if not picks and getattr(self, "pending", None) is None:

            kinds = tuple(kinds) + STANDARD + ("Distance", "Angle", "Width", "Symmetric", "Path Mate")
        # nothing greyed: a type that does not fit the picks says why when pressed (choose)
        self.allowed_kinds = tuple(kinds) if picks else None
        for kind, b in self.type_buttons.items():
            b.setEnabled(True)
            fits = not picks or kind in kinds or kind not in STANDARD
            if not fits and b.isChecked():
                self.group.setExclusive(False)
                b.setChecked(False)
                self.group.setExclusive(True)

            b.setVisible(fits)
            if kind in self.type_labels:
                self.type_labels[kind].setEnabled(True)
                self.type_labels[kind].setVisible(fits)
        align = bool(kinds) and picks           # Mate alignment: shown once there is a pair to align
        for w in (self.alignment_label, self.aligned, self.anti):
            w.setEnabled(True)
            w.setVisible(align)
        self.distance.setEnabled(True)
        self.angle.setEnabled(True)

    def _preview(self):
        s1, s2 = self.shapes()
        kinds = ac.allowed(s1, s2, self.refs)
        kinds = self._mid_kinds(kinds)
        self._enable(kinds)
        first, self.first_kind = getattr(self, "first_kind", None), None
        later = first if first in PRE_PICK else None
        miss = None
        if later is not None and later not in kinds:
            miss, later = later, None
        # Cam, Slot, Linear/Linear Coupler pressed first: the default mate first, then made into it below (asmpkg355)
        self.kind = first if first in kinds and first not in ac.LIMITS and first in ac.JOINT else ac.first_choice(s1, s2)
        if self.kind in getattr(self, "couplers", {}):
            self._coupler_defaults(self.kind)   # pressed before the picks: its value from them (1 mm per turn)
        elif self.kind == "Gear":
            self._gear_defaults()
        if first not in ("Distance", "Angle"):
            self._measured()
        import UtilsAssembly
        self.start = UtilsAssembly.saveAssemblyPartsPlacements(self.asm)    # before the suggested mate moved them
        self.doc.openTransaction("Mate")
        try:
            m1, m2, extra = self._mate_refs()
            self.pending = ac.add_mate(self.asm, self.kind, m1, m2, self._value(self.kind),
                                       ball=self.kind == "Coincident" and self._ball(), **extra)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: mate not made: %s\n" % error)
            self.doc.abortTransaction()
            self.pending = None
            return
        self._hold_back()
        self._show_kind()
        self._error(self.pending)
        if miss is not None:
            self._error_text("%s cannot be made from these selections." % miss)
        if later is not None:
            self.choose(later)      # pressed before the picks (Mechanical/Advanced tab): made of them
            return
        if self.show_popup.isChecked():
            self._popup(kinds)

    def _radius(self, ref):
        """The radius of a cylindrical face picked (None for anything else)."""
        try:
            f = ac.element(*ref)
            if f is not None and f.ShapeType == "Face" and f.Surface.TypeId == "Part::GeomCylinder":
                return float(f.Surface.Radius)
        except Exception as _fw_err:
            _fw_log("asmpm.py:3509", _fw_err)
        return None

    def cylinders(self):
        if len(self.refs) != 2:
            return None
        r = [self._radius(x) for x in self.refs]
        return r if all(v is not None for v in r) else None

    def distance_kind(self):
        return next((n for n, b in self.dist_kind.items() if b.isChecked()), "Center to Center")

    def _dist_kind_changed(self):
        self.custom_rows.setVisible(self.distance_kind() == "Custom Distance")
        if self.kind == "Distance":
            self.choose("Distance")

    def centre_distance(self, v):
        """The joint's distance for the value typed on two cylinders: Center to Center is between
        their axes, Minimum Distance between the nearest sides, Maximum between the farthest,
        Custom per selection (Center, Minimum or Maximum of each)."""
        rs = self.cylinders()
        kind = self.distance_kind()
        if rs is None:
            return v
        if kind == "Custom Distance":
            signs = [SIDE_SIGN[c.currentText()] for c in self.custom_sides]
        elif kind == "Center to Center":
            signs = [0.0, 0.0]
        else:
            signs = [SIDE_SIGN["Minimum" if kind == "Minimum Distance" else "Maximum"]] * 2
        centre = v + signs[0] * rs[0] + signs[1] * rs[1]
        return centre - rs[0] - rs[1]       # FreeCAD's Distance of two cylinders is between their sides

    def _value(self, kind):
        if kind == "Distance":
            v = self.centre_distance(self.distance.value())
            return -v if self.flip_dimension.isChecked() else v
        if kind == "Angle":
            return self.angle.value()
        if kind == "Gear":
            return (self.gear_ratio[0].value(), self.gear_ratio[1].value(), self.gear_reverse.isChecked())
        if kind in getattr(self, "couplers", {}):
            c = self.couplers[kind]
            return (self._coupler_mode_of(kind), c["value"].value(), c["reverse"].isChecked())
        if kind == "Profile Center":
            return (self.profile_offset.value(), self.profile_flip.isChecked(), self.profile_lock.isChecked())
        return None

    def _show_kind(self):
        b = self.type_buttons.get(self.kind)
        if b is not None:
            b.setChecked(True)
        self.lock_rotation.setVisible(self.kind == "Concentric")
        self.flip_dimension.setVisible(self.kind in ("Distance", "Angle"))
        self.angle_ref_box.setVisible(self.kind == "Angle" and not self.multi)
        self.dist_kinds.setVisible(self.kind == "Distance" and self.cylinders() is not None)
        self.custom_rows.setVisible(self.distance_kind() == "Custom Distance")
        gear = self.kind == "Gear"
        self.gear_row.setVisible(gear)
        self.gear_reverse.setVisible(gear)
        self.hinge_box.setVisible(self.kind == "Hinge")
        for kind, c in getattr(self, "couplers", {}).items():
            c["box"].setVisible(self.kind == kind)
        self.profile_box.setVisible(self.kind == "Profile Center")
        self.width_box.setVisible(self.kind == "Width")
        self.path_box.setVisible(self.kind == "Path Mate")
        self.linear_box.setVisible(self.kind == asmcoupler.KIND)
        self.cam_note.setVisible(False)          # the Cam Path / Cam Follower boxes say it now
        self._roles()
        self.sym_box.setVisible(self.kind == "Symmetric")
        self.slot_box.setVisible(self.kind == "Slot")
        self.uj_box.setVisible(self.kind == "Universal Joint")
        for kind, f in getattr(self, "limits", {}).items():
            f["box"].setVisible(self.kind == kind)
        if self.kind in ac.ADVANCED:
            self._open_box(self.adv_box)
            for wait in (450, 1200):
                QtCore.QTimer.singleShot(wait, lambda: self._fit_box(self.adv_box))
        if self.kind in ac.MECHANICAL:
            self._open_box(self.mech_box)
        for wait in (450, 1200):        # after FreeCAD's fold animation has set its own height
            QtCore.QTimer.singleShot(wait, lambda: self._fit_box(self.mech_box))
        for w in (self.alignment_label, self.aligned, self.anti):
            w.setEnabled(self.kind not in ac.MECHANICAL + ac.LIMITS + ("Symmetric", "Path Mate", asmcoupler.KIND) and bool(self.refs))  # no alignment for these
        self._follow_fade()

        self.distance.setEnabled(True)
        self.angle.setEnabled(True)
        joint = self.pending or self.editing
        self._title(joint.Label if joint is not None else "Mate")
        self._sync_alignment()
        if self.popup is not None:
            self.popup.mark(self.kind)

    ROLES = {"Cam": ("Cam Path:", "Cam Follower:"), "Rack Pinion": ("Rack:", "Pinion/Gear:")}

    def _roles(self):
        ""
        names = self.ROLES.get(self.kind)
        joint = self.pending or self.editing
        if names is None or len(self.refs) < 2 and joint is None:
            self.role_box.hide()
            return
        texts = [self.list.item(i).text() for i in range(self.list.count())]
        refs = list(self.refs)
        order = [0, 1]
        try:
            if self.kind == "Cam":
                if not asmcam.is_cam(refs[0]) and asmcam.is_cam(refs[1]):
                    order = [1, 0]
            else:
                g = ac.geometry(ac.element(*refs[0]))
                if g is not None and g[0] in ("axis", "circle"):
                    order = [1, 0]      # the round pick is the pinion
        except Exception as _fw_err:
            _fw_log("asmpm.py:3624", _fw_err)
        for i, (label, w) in enumerate(zip(self.role_labels, self.role_lists)):
            label.setText(names[i])
            w.clear()
            k = order[i]
            if k < len(texts):
                w.addItem(texts[k])
        self.role_box.show()

    def _popup(self, kinds):
        self._close_popup()
        from . import asmrefopts
        if not asmrefopts.customize("QuickMates"):
            return          # Customize > Toolbars: Quick Mates off, no pop-up after the picks
        self.popup = MatePopup(self, kinds, self.kind)
        pos = QtGui.QCursor.pos() + QtCore.QPoint(18, 18)
        self.popup.move(pos)
        self.popup.show()

    def _close_popup(self):
        if self.popup is not None:
            self.popup.hide()
            self.popup.deleteLater()
            self.popup = None

    def choose(self, kind):
        if self.multi:
            if not self.multi_pending and kind in STANDARD + ("Distance", "Angle"):
                self.kind = kind            # chosen before the picks: the mates are made of it
                return
            if not self.multi_pending or kind not in STANDARD + ("Distance", "Angle"):
                return
            self.kind = kind
            for j in self.multi_pending:
                ac.change_mate(self.asm, j, kind, self._value(kind), self.lock_rotation.isChecked())
            self._hold_back()
            self._show_kind()
            self._title("Multiple mate")
            return
        joint = self.pending or self.editing
        allowed = getattr(self, "allowed_kinds", None)
        if allowed is not None and joint is not None and kind not in allowed and kind not in ("Width", "Path Mate", "Symmetric"):

            self._error_text("%s cannot be made from these selections." % shown(kind))
            b = self.type_buttons.get(self.kind)
            if b is not None:
                b.setChecked(True)
            return
        if kind == "Width" and joint is None:
            self._width_start()
            return
        if kind == "Path Mate" and (joint is None or (joint is self.pending and ac.mate_type(joint) != "Path Mate")):
            seed = [r for r in self.refs if asmpath.is_vertex(r)] + [r for r in self.refs if asmpath.is_edge(r)]
            self._path_start(seed if joint is not None else ())
            return
        if kind == "Path Mate" and joint is not None and ac.mate_type(joint) == "Path Mate":
            self.kind = "Path Mate"
            self._show_kind()
            return
        if kind == "Cam" and joint is not None and joint is not self.editing and ac.mate_type(joint) != "Cam":
            self._cam_start()
            return
        if kind == "Cam" and joint is not None and ac.mate_type(joint) == "Cam":
            self.kind = kind
            self._show_kind()
            return
        if kind == asmcoupler.KIND and joint is not None and joint is not self.editing \
                and ac.mate_type(joint) != asmcoupler.KIND:
            self._linear_start()
            return
        if kind == asmcoupler.KIND and joint is not None and ac.mate_type(joint) == asmcoupler.KIND:
            self.kind = kind
            self._show_kind()
            return
        if kind == "Symmetric" and joint is None:
            self._symmetric_start()
            return
        if kind in ac.LIMITS and joint is not None and joint is not self.editing:
            self._limit_start(kind)
            return
        if kind == "Slot" and joint is not None and joint is not self.editing:
            self._slot_start()
            return
        if kind == "Slot" and joint is not None and ac.mate_type(joint) == "Slot":
            self.kind = "Slot"
            self._show_kind()
            return
        if joint is not None and joint is self.pending and ac.mate_type(joint) in ac.VIRTUAL and kind not in ac.VIRTUAL:
            # from a range back to a plain mate: the range goes, the mate is made again
            name = joint.Name
            self.pending = None
            self.doc.removeObject(name)
            ac.solve(self.asm)
            m1, m2, extra = self._mate_refs()
            self.pending = ac.add_mate(self.asm, kind, m1, m2, self._value(kind),
                                       ball=kind == "Coincident" and self._ball(), **extra)
            joint = self.pending
        if joint is None:
            if kind in STANDARD + ("Distance", "Angle") + PRE_PICK and not getattr(self, "refs", None):

                self.first_kind = kind
                self.distance.setEnabled(kind == "Distance")
                self.angle.setEnabled(kind == "Angle")
            return
        if kind == "Gear" and self.kind != "Gear":
            self._gear_defaults()
            if joint is self.pending and getattr(self, "start", None):
                # a Gear holds nothing: the gears go back to where they were (the suggested
                # Concentric put them on one axis, and coaxial gears crash FreeCAD's solver later)
                import UtilsAssembly
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        if kind == "Profile Center" and self.kind != kind:
            self._profile_set()
        if kind in getattr(self, "couplers", {}) and self.kind != kind:
            self._coupler_defaults(kind)
            if joint is self.pending and getattr(self, "start", None):
                # a coupling mate holds nothing: the components go back to where they were
                import UtilsAssembly
                UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        if kind == "Hinge":
            if ac.mate_type(joint) != "Hinge":

                # flat faces come next (Coincident Selections). Shown as Concentric till then.
                if ac.mate_type(joint) != "Concentric":
                    ac.change_mate(self.asm, joint, "Concentric", None, False, editing=joint is self.editing)
                self.hinge_planes = []
                self.hinge_list.clear()
                self.hinge_angle_refs = []
                self.hinge_angle.clear()
            self.kind = "Hinge"
            self._show_kind()
            self._error(joint)
            return
        if joint is self.pending and getattr(self, "start", None) and kind != self.kind \
                and kind in ("Distance", "Angle", "Perpendicular") and ac.mate_type(joint) in ("Concentric", "Coincident"):
            # the suggested Concentric/Coincident put the picks on each other: from there a Distance
            # or Angle is degenerate (FreeCAD's solver can crash on it), so start from where they were
            import UtilsAssembly
            UtilsAssembly.restoreAssemblyPartsPlacements(self.asm, self.start)
        self.kind = kind
        ac.change_mate(self.asm, joint, kind, self._value(kind), self.lock_rotation.isChecked(),
                       editing=joint is self.editing)
        if kind == "Angle" and self.flip_dimension.isChecked() != bool(getattr(joint, ac.ANGLE_FLIP_PROP, False)):
            ac.set_angle_flip(self.asm, joint, self.flip_dimension.isChecked())
        if joint is self.pending:
            self._hold_back()
        self._show_kind()
        self._error(joint)

    def _lock_changed(self, on):
        if self.kind == "Concentric":
            self.choose("Concentric")

    def _flip_toggled(self, on):
        """Flip dimension: a Distance goes to the other side; an Angle is measured the other way."""
        if self.kind != "Angle" or self.multi:
            self._value_changed()
            return
        joint = self.pending or self.editing
        if joint is None:
            return
        ac.set_angle_flip(self.asm, joint, on)
        if joint is self.pending:
            self._hold_back()
        self._error(joint)

    def _angle_ref_pick(self, ref):
        joint = self.pending or self.editing
        if joint is None or ac.geometry(ac.element(*ref)) is None:
            return
        ac.set_angle_ref(self.asm, joint, ref)
        self._angle_ref_list(joint)
        if joint is self.pending:
            self._hold_back()
        self._error(joint)

    def _angle_ref_list(self, joint):
        self.angle_ref.clear()
        ref = ac.angle_ref(self.asm, joint) if joint is not None else None
        if ref is not None:
            kind = "".join(ch for ch in ref[1].split(".")[-1] if ch.isalpha()) or "Face"
            self.angle_ref.addItem("%s@%s" % (kind, _pick_name(ref[0].Label)))

    def _angle_ref_menu(self):
        menu = QtWidgets.QMenu(self.angle_ref)
        act = menu.addAction("Clear Selections")
        act.setObjectName("FW_AngleReferenceClear")
        act.setEnabled(self.angle_ref.count() > 0)
        act.triggered.connect(self._angle_ref_clear)
        return menu

    def _angle_ref_clear(self, *args):
        joint = self.pending or self.editing
        if joint is not None:
            ac.set_angle_ref(self.asm, joint, None)
        self.angle_ref.clear()

    def _typed(self, kind):
        """A value typed in the Distance or Angle box (or its arrows): that mate, as pressing its icon."""
        if self.kind != kind:
            self.choose(kind)
        else:
            self._value_changed()

    def _value_changed(self, *args):
        if self.kind in ("Distance", "Angle", "Gear", "Rack Pinion", "Screw", "Profile Center"):
            self.choose(self.kind)

    def _align(self, button):
        """Aligned / Anti-Aligned: the button pressed in shows the side the mate holds."""
        want_anti = button is self.anti
        if want_anti != getattr(self, "_anti_state", True):
            self.flip_alignment()

    def flip_alignment(self):
        joint = self.pending or self.editing
        if joint is not None:
            ac.flip(self.asm, joint)
            self._error(joint)
        if not self._sync_alignment():
            self._anti_state = not getattr(self, "_anti_state", True)
            self._mark_alignment()

    def _title(self, text):
        ""
        box = getattr(self, "tabs_box", None) or self.sel_box     # the first group holds the page's title
        box.setProperty("swstyle_pm_title", text)
        box.setProperty("swstyle_pm_icon", ICONS.get(self.kind, ("ASSEMBLIES_MATE",))[0]
                        if text != "Mate" else "ASSEMBLIES_MATE")
        try:
            from . import propertymanager
            header = propertymanager._header_of(self.sel_box)
            if header is not None:
                header.sync()       # the header shows it now, not at the next page change
        except Exception as _fw_err:
            _fw_log("asmpm.py:_title", _fw_err)

    def _measured(self):
        ""


        try:
            s1, s2 = ac.element(*self.refs[0]), ac.element(*self.refs[1])
            if s1 is None or s2 is None:
                return
            g1, g2 = ac.geometry(s1), ac.geometry(s2)
            d1 = g1[2] if g1 is not None and g1[0] in ("plane", "axis", "line") else None
            d2 = g2[2] if g2 is not None and g2[0] in ("plane", "axis", "line") else None
            angle = None
            if d1 is not None and d2 is not None and d1.Length > 1e-12 and d2.Length > 1e-12:
                c = max(-1.0, min(1.0, d1.dot(d2) / (d1.Length * d2.Length)))
                angle = math.degrees(math.acos(abs(c)))
            if g1[0] == "plane" and g2[0] == "plane" and angle is not None and angle < 1e-6:
                n = App.Vector(d1); n.normalize()
                dist = abs((g2[1] - g1[1]).dot(n))
            else:
                dist = s1.distToShape(s2)[0]
            for box, value in ((self.distance, dist), (self.angle, angle)):
                if value is not None:
                    box.blockSignals(True)
                    box.setValue(value)
                    box.blockSignals(False)
        except Exception as _fw_err:
            _fw_log("asmpm.py:_measured", _fw_err)

    def _sync_alignment(self):
        """Press in the alignment the mate holds now: the picks' normals (or axes) the same way
        is Aligned, opposite is Anti-Aligned."""
        if len(self.refs) != 2:
            return False
        try:
            g1, g2 = [ac.geometry(sh) for sh in self.shapes()]
        except Exception:
            return False
        if g1 is None or g2 is None or g1[0] == "point" or g2[0] == "point":
            return False
        dot = g1[2].dot(g2[2])
        if abs(dot) < 1e-6:
            return False
        self._anti_state = dot < 0
        self._mark_alignment()
        return True

    def _mark_alignment(self):
        (self.anti if self._anti_state else self.aligned).setChecked(True)
        if self.popup is not None:
            self.popup.flip.setChecked(not self._anti_state)

    def _error_text(self, text):
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _error(self, joint):
        bad = joint is not None and ac.mate_error(joint)
        off = ac.misalignment(joint) if joint is not None and not bad and ac.is_misaligned(joint) else 0.0
        if bad:
            self.message.setText(ac.OVER_MESSAGE)
        elif off:
            self.message.setText("Misaligned: the axes are %.2fmm apart (Allow creation of misaligned mates)." % off)
        else:
            self.message.setText("")
        self.message.setVisible(bad or bool(off))

    # ------------------------------------------------------------ keep / drop
    def keep(self):
        """The mate pop-up's check: the mate stays; the next pair can be picked. With Use for
        positioning only, the components stay where the mate put them and the mate goes."""
        if self.multi:
            self._multi_keep()
            self._close_popup()
            self._unfade()
            self._multi_clear()
            self.refs, self.picked, self.kind = [], [], None
            self._enable(())
            Gui.Selection.clearSelection()
            return
        if self.pending is not None and self.position_only.isChecked():
            if not self.show_preview.isChecked():
                ac.solve(self.asm)
            name = self.pending.Name
            self.doc.recompute()
            self.pending = None
            try:
                self.doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("asmpm.py:3896", _fw_err)
            self.doc.commitTransaction()
        if self.pending is not None:
            if not self.show_preview.isChecked():
                ac.solve(self.asm)      # Show preview off: the parts move now
            self.doc.recompute()
            self.doc.commitTransaction()
            self.kept.append(self.pending)
            self.kept_batches.append(1)
            self.mates.addItem(QtWidgets.QListWidgetItem(sw_icon(ac.mate_type(self.pending)),
                                                         ac.mate_text(self.pending)))
            self.pending = None
        self._reset()
        pin = getattr(self, "pin", None)
        if pin is not None and not pin.isChecked():
            QtCore.QTimer.singleShot(0, self.accept)    # pushpin out: one mate, then close

    def undo(self):
        """The Undo beside check and X: the mate being shown, else the last one kept."""
        if self.pending is not None:
            self.drop()
            return
        if self.kept:
            count = self.kept_batches.pop() if self.kept_batches else 1
            self.doc.undo()
            for _ in range(min(count, len(self.kept))):
                self.kept.pop()
                if self.mates.count():
                    self.mates.takeItem(self.mates.count() - 1)
            ac.solve(self.asm)

    def _sel_menu(self, pos):
        ""
        menu = QtWidgets.QMenu(self.list)
        menu.setObjectName("FW_MateSelectionsMenu")
        item = self.list.itemAt(pos)
        row = self.list.row(item) if item is not None else -1
        delete = menu.addAction("Delete")
        delete.setEnabled(0 <= row < len(self.picked))
        delete.triggered.connect(lambda *_: self.delete_pick(row))
        clear = menu.addAction("Clear Selections")
        clear.setEnabled(bool(self.refs) or self.pending is not None)
        clear.triggered.connect(lambda *_: (self.drop(), Gui.Selection.clearSelection()))
        self.list._fw_menu = menu
        return menu

    def delete_pick(self, row):
        """Delete one entity: the mate being shown goes, the other picks stay picked."""
        keep = [p for i, p in enumerate(self.picked) if i != row]
        self.drop()
        Gui.Selection.clearSelection()
        for root_name, sub in keep:
            root = self.doc.getObject(root_name)
            if root is not None:
                self._pick(root, sub)

    def drop(self):
        if self.multi_pending:
            self.multi_pending = []
            self.doc.abortTransaction()
        if self.pending is not None:
            self.pending = None
            self.doc.abortTransaction()
        self._multi_clear()
        self._reset()

    def _reset(self):
        self._close_popup()
        self._unfade()
        self._anti_state = True
        self.anti.setChecked(True)
        self.refs = []
        self.mids = {}
        self.picked = []
        self.kind = None
        self._list()
        self._enable(())
        self.lock_rotation.hide()
        self.flip_dimension.blockSignals(True)
        self.flip_dimension.setChecked(False)
        self.flip_dimension.blockSignals(False)
        self.flip_dimension.hide()
        self.angle_ref.clear()
        self.angle_ref_box.hide()
        self.dist_kinds.hide()
        self.gear_row.hide()
        self.gear_reverse.hide()
        for c in getattr(self, "couplers", {}).values():
            c["box"].hide()
        self.profile_box.hide()
        for f in getattr(self, "limits", {}).values():
            f["box"].hide()
        self.width_box.hide()
        self.path_box.hide()
        self.linear_box.hide()
        self.linear_refs = ["", ""]
        for w in self.linear_ref_lists:
            w.clear()
        self.path_vertex, self.path_edges, self.path_upref = None, [], None
        for w in (self.path_vertex_list, self.path_list, self.path_up_list):
            w.clear()
        self.sym_box.hide()
        self.sym_entities, self.sym_plane = [], None
        self.sym_list.clear()
        self.sym_plane_list.clear()
        self.width_sel, self.tab_sel = [], []
        self.width_list.clear()
        self.tab_list.clear()
        self.hinge_box.hide()
        self.hinge_planes = []
        self.hinge_list.clear()
        self.hinge_angle_refs = []
        self.hinge_angle.clear()
        self.role_box.hide()
        self.slot_box.hide()
        self.uj_box.hide()
        self.uj_ref = None
        self.uj_list.clear()
        self.uj_define.blockSignals(True)
        self.uj_define.setChecked(False)
        self.uj_define.blockSignals(False)
        self._title("Mate")
        self._error(None)
        Gui.Selection.clearSelection()

    def _load(self, joint):
        self.kind = ac.mate_type(joint)
        self.refs = [(joint.Reference1[0], joint.Reference1[1][0]), (joint.Reference2[0], joint.Reference2[1][0])]
        self._list()
        self._enable(ac.allowed(*self.shapes(), refs=self.refs))
        if self.kind == "Distance":
            self.distance.blockSignals(True)
            self.distance.setValue(abs(ac.distance_value(joint)))
            self.distance.blockSignals(False)
            self.flip_dimension.blockSignals(True)
            self.flip_dimension.setChecked(ac.distance_value(joint) < 0)
            self.flip_dimension.blockSignals(False)
        if self.kind == "Angle":
            self.angle.blockSignals(True)
            self.angle.setValue(joint.Angle.Value if hasattr(joint.Angle, "Value") else joint.Angle)
            self.angle.blockSignals(False)
            self.flip_dimension.blockSignals(True)
            self.flip_dimension.setChecked(bool(getattr(joint, ac.ANGLE_FLIP_PROP, False)))
            self.flip_dimension.blockSignals(False)
            self._angle_ref_list(joint)
        if self.kind == "Gear":
            for box, prop in zip(self.gear_ratio, ("Distance", "Distance2")):
                box.blockSignals(True)
                box.setValue(2.0 * abs(float(getattr(joint, prop, 0.5))))
                box.blockSignals(False)
            self.gear_reverse.blockSignals(True)
            self.gear_reverse.setChecked(joint.JointType == "Belt")
            self.gear_reverse.blockSignals(False)
        if self.kind in getattr(self, "couplers", {}):
            self._coupler_load(self.kind, joint)
        if self.kind == "Profile Center":
            self._profile_set(*ac._profile_values(joint))
        if self.kind == "Symmetric":
            first, _sign = ac.symmetric_first(joint)
            self.sym_list.clear()
            self.sym_plane_list.clear()
            if first is not None and first[0] is not None:
                self.sym_list.addItem("%s@%s" % (first[1], _pick_name(first[0].Label)))
            self.sym_list.addItem("%s@%s" % (joint.Reference2[1][0], _pick_name(joint.Reference2[0].Label)))
            self.sym_plane_list.addItem("%s@%s" % (joint.Reference1[1][0], _pick_name(joint.Reference1[0].Label)))
        if self.kind == "Slot":
            self._slot_set(*ac.slot_values(joint))
        if self.kind == "Path Mate":
            self._path_load(joint)
        if self.kind == "Universal Joint":
            ref = getattr(joint, ac.JOINT_POINT_PROP, None)
            self.uj_define.blockSignals(True)
            self.uj_define.setChecked(bool(ref and ref[0] is not None))
            self.uj_define.blockSignals(False)
            self.uj_list.setEnabled(self.uj_define.isChecked())
            self.uj_list.clear()
            if ref and ref[0] is not None and ref[1]:
                self.uj_ref = (ref[0], ref[1][0])
                kind = "".join(ch for ch in ref[1][0].split(".")[-1] if ch.isalpha())
                self.uj_list.addItem("%s@%s" % (kind, _pick_name(ref[0].Label)))
        if self.kind == asmcoupler.KIND:
            v = asmcoupler.values(joint)
            self._linear_set(v["r1"], v["r2"], v["reverse"], asmcoupler.reference_names(joint))
        if self.kind in ac.LIMITS:
            data = ac.limit_values(joint)
            if data is not None:
                refs = [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]
                try:
                    now = ac.picked_value(self.kind, refs)
                except Exception:
                    now = None
                self._limit_set(self.kind, data[1], data[2], now)
        if self.kind == "Width":
            data = ac.width_values(joint)
            if data is not None:
                width, tab, mode, value, flip = data
                self.width_list.clear()
                self.tab_list.clear()
                for picks, view in ((width, self.width_list), (tab[:1] if ac.round_tab(tab) else tab, self.tab_list)):
                    for comp, elem in picks:
                        view.addItem("%s@%s" % (elem, _pick_name(comp.Label)))
                for w in (self.width_mode, self.width_value, self.width_flip):
                    w.blockSignals(True)
                self.width_mode.setCurrentIndex(max(0, self.width_mode.findData(mode)))
                self.width_value.setVisible(mode in ("dimension", "percent"))
                self.width_flip.setVisible(mode in ("dimension", "percent"))
                self.width_value.setSuffix("%" if mode == "percent" else "mm")
                self.width_value.setRange(0.0, 100.0 if mode == "percent" else 1.0e6)
                self.width_value.setValue(value)
                self.width_flip.setChecked(flip)
                for w in (self.width_mode, self.width_value, self.width_flip):
                    w.blockSignals(False)
        if self.kind == "Hinge":
            on = bool(getattr(joint, "EnableAngleMax", False))
            for w, v in ((self.hinge_limits, on), (self.hinge_max, getattr(joint, "AngleMax", 90.0)),
                         (self.hinge_min, getattr(joint, "AngleMin", 0.0))):
                w.blockSignals(True)
                if w is self.hinge_limits:
                    w.setChecked(v)
                else:
                    w.setValue(float(getattr(v, "Value", v)))
                    w.setEnabled(on)
                w.blockSignals(False)
            self.hinge_list.addItem("(Coincident faces of %s)" % joint.Label)
            self.hinge_angle_refs = ac.hinge_angle_refs(joint)
            self.hinge_angle.clear()
            for c, e in self.hinge_angle_refs:
                self.hinge_angle.addItem("%s@%s" % (e, _pick_name(c.Label)))
            self.hinge_angle_label.setVisible(on)
            self.hinge_angle.setVisible(on)
        self.lock_rotation.blockSignals(True)
        self.lock_rotation.setChecked(bool(getattr(joint, ac.LOCK_PROP, False)))
        self.lock_rotation.blockSignals(False)
        self._show_kind()
        self._error(joint)
        self.mates.addItem(QtWidgets.QListWidgetItem(sw_icon(self.kind), ac.mate_text(joint)))
        self.doc.openTransaction("Edit Mate")

    def _finish(self):
        try:
            self._isolate(False)        # Isolate components: the hidden ones show again
        except Exception as error:      # the assembly may be gone: the clean-up below still runs
            App.Console.PrintLog("Mate: isolate off: %s\n" % error)
        Gui.Selection.removeObserver(self)
        try:
            from . import asmwidthtags
            asmwidthtags.close(self)
        except Exception as _fw_err:
            _fw_log("asmpm.py:4140", _fw_err)
        self._close_popup()
        self._unfade()
        self._header_off()

    def _header_off(self):
        """The header stays for the next PropertyManager: Undo, the pushpin and the tabs are Mate's own."""
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
            if widget.objectName() in ("FW_MateUndo", "FW_MatePin", "FW_MateTabs"):
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def accept(self):
        if self.editing is not None:
            self.doc.recompute()
            self.doc.commitTransaction()
        else:
            self.keep()
            if self.add_folder.isChecked():
                made = [m for m in ac.mates(self.asm) if m.Name not in self.before_names]
                if made:
                    from . import asmfolder
                    asmfolder.add_to_new_folder(made)
        self._finish()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        if self.editing is not None:
            self.doc.abortTransaction()
        else:
            self.drop()
        self._finish()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


# ============================================================================= Move / Rotate Component
MOVE_MODES = ("Free Drag", "Along Assembly XYZ", "Along Entity", "By Delta XYZ", "To XYZ Position")
ROTATE_MODES = ("Free Drag", "About Entity", "By Delta XYZ")


def smart_mate(asm, first, ref):
    ""

    if first is None or ref is None or ref[0] is first[0]:
        return None
    s1, s2 = ac.element(*first), ac.element(*ref)
    if s1 is None or s2 is None:
        return None
    try:
        kind = ac.first_choice(s1, s2)
    except Exception:
        kind = "Coincident"
    peg = peg_faces(first, ref, s1, s2)
    doc = asm.Document
    doc.openTransaction("SmartMates")
    temp = ref[0] not in ac.grounded(asm)
    try:
        if temp:
            ac.fix(asm, ref[0])
        if peg is not None:

            # faces the edges bound)
            joint = ac.add_mate(asm, "Concentric", first, ref)
            second = ac.add_mate(asm, "Coincident", (first[0], peg[0]), (ref[0], peg[1]))
            if joint is not None and second is not None:
                PEG[joint.Name] = (second.Name, (first[0], peg[0]), (ref[0], peg[1]))

                # round both rims, a third mate (Concentric) lines up a pair of the holes
                pair = pattern_holes(first, ref)
                if pair is not None:
                    third = ac.add_mate(asm, "Concentric", pair[0], pair[1])
                    if third is not None and (ac.mate_error(third) or not ac.satisfied(third)):
                        doc.removeObject(third.Name)
                        doc.recompute()
        else:
            joint = ac.add_mate(asm, kind, first, ref)
    finally:
        if temp:
            ac.float_(asm, ref[0])
        doc.commitTransaction()
    doc.recompute()
    return joint


PEG = {}        # a peg-in-hole SmartMate's Concentric: (its Coincident's name, the two flat faces)


def peg_partner(asm, joint):
    """The Coincident made with a peg-in-hole SmartMate's Concentric, else None."""
    entry = PEG.get(getattr(joint, "Name", ""))
    return asm.Document.getObject(entry[0]) if entry else None


def flip_smart(asm, joint):
    """Flip Mate Alignment on a SmartMate. A peg-in-hole turns the peg end for end on the
    hole's axis: its Coincident is made again after the Concentric flips (FreeCAD can't flip
    one mate of a part another mate holds)."""
    partner = peg_partner(asm, joint)
    if partner is None:
        return ac.flip(asm, joint)
    _, a, b = PEG[joint.Name]
    label = partner.Label
    asm.Document.removeObject(partner.Name)
    ok = ac.flip(asm, joint)
    second = ac.add_mate(asm, "Coincident", a, b)
    if second is not None:
        second.Label = label
        PEG[joint.Name] = (second.Name, a, b)
    else:
        PEG.pop(joint.Name, None)
    return ok and second is not None and ac.satisfied(second)


def _flat_face_of(comp, sub, edge):
    """The flat face a circular edge bounds, as an element name next to the edge's."""
    prefix, _, _ = sub.rpartition(".")
    try:
        owner = ac.element(comp, prefix + ".") if prefix else comp.Shape
    except Exception:
        owner = None
    if owner is None or edge is None:
        return None
    from . import pegfaces
    i = pegfaces.flat_face_for_circle(owner, edge)
    return None if i is None else (prefix + "." if prefix else "") + "Face%d" % (i + 1)


def _round_holes(comp, sub, centre, axis, rim):
    """[(element, radius, pitch radius, angle point)] of the round faces of comp's part (sub's
    prefix) parallel to axis and off it: the holes of a pattern round the rim."""
    prefix = sub.rpartition(".")[0]
    try:
        owner = ac.element(comp, prefix + ".") if prefix else comp.Shape
    except Exception:
        owner = None
    out = []
    for i, f in enumerate(getattr(owner, "Faces", []) or [], 1):
        try:
            srf = f.Surface
            if srf.TypeId != "Part::GeomCylinder" or abs(abs(V3(srf.Axis).normalize().dot(axis)) - 1) > 1e-6:
                continue
            c = V3(srf.Center) - centre
            off = c - axis * c.dot(axis)
            if off.Length < rim + srf.Radius - 1e-6:
                continue
            out.append(((prefix + "." if prefix else "") + "Face%d" % i, srf.Radius, off.Length, off))
        except Exception:
            continue
    return out


def V3(v):
    return App.Vector(v)


def pattern_holes(first, ref):
    """After a peg-in-hole on two rims: (first's hole, ref's hole) of the same size on the same
    pitch circle, the pair nearest to lining up; None when the two have no such pattern."""
    try:
        e1, e2 = ac.element(*first), ac.element(*ref)
        if e2 is None or e1 is None:
            return None
        axis = V3(e2.Curve.Axis).normalize()
        centre = V3(e2.Curve.Center)
        mine = _round_holes(first[0], first[1], V3(e1.Curve.Center), axis, e1.Curve.Radius)
        theirs = _round_holes(ref[0], ref[1], centre, axis, e2.Curve.Radius)
        best = None
        for a in mine:
            for b in theirs:
                if abs(a[1] - b[1]) > 1e-4 or abs(a[2] - b[2]) > 1e-4:
                    continue
                turn = a[3].getAngle(b[3]) if a[3].Length > 1e-9 and b[3].Length > 1e-9 else 0.0
                if best is None or turn < best[0] - 1e-9:
                    best = (turn, a[0], b[0])
        if best is None:
            return None
        return (first[0], best[1]), (ref[0], best[2])
    except Exception as _fw_err:
        _fw_log("asmpm.py:pattern holes", _fw_err)
        return None


def _page_key(header):
    try:
        from . import propertymanager as pmod
        control = pmod._edit_control(header.view)
        if control is None:
            return None
        import shiboken6
        return int(shiboken6.getCppPointer(control)[0])
    except Exception:
        return None


def page_owned(header, widget):
    """A button this page put on the PropertyManager header (Mate's Undo, the pushpins) goes when
    the page goes: closed another way than OK/Cancel (the next command closing it), it stayed on
    every later PropertyManager (Linear Pattern showed Mate's Undo and two pushpins)."""
    widget.setProperty("fw_page", _page_key(header) or 0)
    cls = type(header)
    if getattr(cls, "_fw_page_owned", False):
        return
    sync0 = cls._sync

    def _sync(self, title, icon):
        sync0(self, title, icon)
        try:
            key = _page_key(self)
            for w in self.findChildren(QtWidgets.QWidget):
                owner = w.property("fw_page")
                if owner is not None and owner != key:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
        except Exception as _fw_err:
            _fw_log("asmpm.py:page owned", _fw_err)
    cls._sync = _sync
    cls._fw_page_owned = True


def peg_faces(first, ref, s1=None, s2=None):
    """Two circular edges (a peg's and a hole's): the flat faces they bound, else None."""
    s1 = s1 if s1 is not None else ac.element(*first)
    s2 = s2 if s2 is not None else ac.element(*ref)
    try:
        if not all(s is not None and s.ShapeType == "Edge" and s.Curve.TypeId == "Part::GeomCircle"
                   for s in (s1, s2)):
            return None
    except Exception:
        return None
    f1, f2 = _flat_face_of(first[0], first[1], s1), _flat_face_of(ref[0], ref[1], s2)
    return (f1, f2) if f1 and f2 else None


def group_visible(box, on):
    """Shows or hides a whole PM group (its task box with its title bar)."""
    w = box
    while w is not None and not (w.inherits("Gui::TaskView::TaskBox") or w.inherits("QSint::ActionGroup")):
        w = w.parentWidget()
    (w or box).setVisible(on)
    box.setVisible(on)


def entity_frame(shape):
    """What Along Entity / About Entity keep to: ('line', point, direction) for a straight edge,
    an axis or a round face's axis; ('plane', point, normal) for a flat face or a plane."""
    g = ac.geometry(shape)
    if g is None:
        return None
    if g[0] in ("line", "axis"):
        return ("line", App.Vector(g[1]), App.Vector(g[2]).normalize())
    if g[0] == "plane":
        return ("plane", App.Vector(g[1]), App.Vector(g[2]).normalize())
    return None


def along(d, frame):
    """A drag step d kept along the entity: on the line, or in the plane."""
    if frame is None:
        return d
    u = frame[2]
    if frame[0] == "line":
        return u * d.dot(u)
    return d - u * d.dot(u)


def along_xyz(d):
    """Along Assembly XYZ: the drag kept to the assembly axis it goes most along."""
    i = max(range(3), key=lambda k: abs(d[k]))
    out = App.Vector()
    out[i] = d[i]
    return out


def about(start, now, frame, centre):
    """About Entity: the turn about the line that brings the start centre round to where the drag
    put it, applied to the start placement."""
    p0, u = frame[1], frame[2]
    if frame[0] != "line":
        return now
    r0 = centre - p0
    r0 = r0 - u * r0.dot(u)
    moved = centre + (now.Base - start.Base)
    r1 = moved - p0
    r1 = r1 - u * r1.dot(u)
    if r0.Length < 1e-9 or r1.Length < 1e-9:
        return start
    import math
    ang = math.degrees(math.atan2(r0.cross(r1).dot(u), r0.dot(r1)))
    turn = App.Placement(App.Vector(), App.Rotation(u, ang), p0)
    return turn.multiply(start)


class MoveComponentPanel:
    ""




    def __init__(self, asm, rotate=False):
        _track(self)
        self.asm = asm
        self.doc = asm.Document
        title = "Rotate Component" if rotate else "Move Component"
        family = "ASSEMBLIES_ROTATE_COMPONENT" if rotate else "ASSEMBLIES_MOVE_COMPONENT"
        move, lay = _box("Move", title, family)
        self.smart = QtWidgets.QToolButton()
        self.smart.setObjectName("FW_MoveSmartMates")
        self.smart.setText("SmartMates")
        self.smart.setCheckable(True)
        self.smart.setToolTip("SmartMates: double-click an entity of the component to move, "
                              "then click the entity to mate it to")
        self.smart.toggled.connect(self._smart_toggled)
        lay.addWidget(self.smart, 0, Qt.AlignLeft)
        self.smart_first = None
        self.move_mode = QtWidgets.QComboBox()
        self.move_mode.setObjectName("FW_MoveMode")
        self.move_mode.addItems(MOVE_MODES)
        lay.addWidget(self.move_mode)
        self.move_entity = QtWidgets.QLineEdit()
        self.move_entity.setObjectName("FW_MoveEntity")
        self.move_entity.setReadOnly(True)
        self.move_entity.setPlaceholderText("Select an edge, axis or face")
        self.move_entity.setStyleSheet(PICK_STYLE)
        lay.addWidget(self.move_entity)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_MoveComponents")
        self.list.setMaximumHeight(56)
        self.list.setStyleSheet(PICK_STYLE)
        lay.addWidget(self.list)
        grid = QtWidgets.QFormLayout()
        self.move_spins = []
        for axis in "XYZ":
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(-1.0e6, 1.0e6)
            spin.setDecimals(2)
            spin.setSuffix("mm")
            spin.setObjectName("FW_Move%s" % axis)
            grid.addRow("Δ%s" % axis, spin)
            self.move_spins.append(spin)
        lay.addLayout(grid)
        self.move_grid = grid
        self.apply_move = QtWidgets.QPushButton("Apply")
        self.apply_move.setObjectName("FW_MoveApply")
        self.apply_move.clicked.connect(self.do_move)
        lay.addWidget(self.apply_move, 0, Qt.AlignLeft)
        self.move_mode.currentIndexChanged.connect(self._modes)

        rot, lay = _box("Rotate")
        self.rot_mode = QtWidgets.QComboBox()
        self.rot_mode.setObjectName("FW_RotateMode")
        self.rot_mode.addItems(ROTATE_MODES)
        lay.addWidget(self.rot_mode)
        self.rot_entity = QtWidgets.QLineEdit()
        self.rot_entity.setObjectName("FW_RotateEntity")
        self.rot_entity.setReadOnly(True)
        self.rot_entity.setPlaceholderText("Select an edge or axis")
        self.rot_entity.setStyleSheet(PICK_STYLE)
        lay.addWidget(self.rot_entity)
        self.entity = {"move": None, "rotate": None}     # (frame, (root name, sub)) per field
        grid = QtWidgets.QFormLayout()
        self.rot_spins = []
        for axis in "XYZ":
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(-360.0, 360.0)
            spin.setDecimals(2)
            spin.setSuffix("deg")
            spin.setObjectName("FW_Rotate%s" % axis)
            grid.addRow("Δ%s" % axis, spin)
            self.rot_spins.append(spin)
        lay.addLayout(grid)
        self.rot_grid = grid
        self.apply_rot = QtWidgets.QPushButton("Apply")
        self.apply_rot.setObjectName("FW_RotateApply")
        self.apply_rot.clicked.connect(self.do_rotate)
        lay.addWidget(self.apply_rot, 0, Qt.AlignLeft)
        self.rot_mode.currentIndexChanged.connect(self._modes)

        opts, lay = _box("Options")
        self.options = {}
        for name in ("Standard Drag", "Collision Detection", "Physical Dynamics"):
            b = QtWidgets.QRadioButton(name)
            b.setObjectName("FW_Move" + name.replace(" ", ""))
            b.toggled.connect(lambda *_: self._option_changed())
            lay.addWidget(b)
            self.options[name] = b
        self.options["Standard Drag"].setChecked(True)
        self.collide_box = QtWidgets.QWidget()
        clay = QtWidgets.QVBoxLayout(self.collide_box)
        clay.setContentsMargins(12, 0, 0, 0)
        clay.addWidget(QtWidgets.QLabel("Check between:"))
        self.check_these = QtWidgets.QRadioButton("These components")
        self.check_these.setObjectName("FW_CollideThese")
        self.check_all = QtWidgets.QRadioButton("All components")
        self.check_all.setObjectName("FW_CollideAll")
        self.check_all.setChecked(True)
        clay.addWidget(self.check_these)
        self.these_list = QtWidgets.QListWidget()
        self.these_list.setObjectName("FW_CollideList")
        self.these_list.setStyleSheet(PICK_STYLE)
        self.these_list.setFixedHeight(_rows(self.these_list, 3))
        clay.addWidget(self.these_list)
        self.resume = QtWidgets.QPushButton("Resume Drag")
        self.resume.setObjectName("FW_CollideResume")
        self.resume.clicked.connect(self._resume_drag)
        clay.addWidget(self.resume, 0, Qt.AlignLeft)
        clay.addWidget(self.check_all)
        self.stop_at = QtWidgets.QCheckBox("Stop at collision")
        self.dragged_only = QtWidgets.QCheckBox("Dragged part only")
        for name, box in (("FW_CollideStop", self.stop_at), ("FW_CollideDraggedOnly", self.dragged_only)):
            box.setObjectName(name)
            box.setChecked(True)
            clay.addWidget(box)

        self.highlight = QtWidgets.QCheckBox("Highlight faces")
        self.sound = QtWidgets.QCheckBox("Sound")
        self.ignore_complex = QtWidgets.QCheckBox("Ignore complex surfaces")
        self.this_config = QtWidgets.QCheckBox("This configuration")
        for name, box, on in (("FW_CollideHighlight", self.highlight, True), ("FW_CollideSound", self.sound, True),
                              ("FW_CollideIgnoreComplex", self.ignore_complex, False),
                              ("FW_CollideThisConfig", self.this_config, False)):
            box.setObjectName(name)
            box.setChecked(on)
        from .asmpattern import _takes_over
        for w in (self.these_list, self.resume):
            _takes_over(w, self.check_these, True)      # live: using them picks "These components"
        lay.addWidget(self.collide_box)
        self.dyn_box = QtWidgets.QWidget()
        dlay = QtWidgets.QFormLayout(self.dyn_box)
        dlay.setContentsMargins(12, 0, 0, 0)
        self.sensitivity = QtWidgets.QSlider(Qt.Horizontal)
        self.sensitivity.setObjectName("FW_DynSensitivity")
        self.sensitivity.setRange(1, 10)
        self.sensitivity.setValue(5)
        dlay.addRow("Sensitivity:", self.sensitivity)
        lay.addWidget(self.dyn_box)
        self.adv, alay = _box("Advanced Options")
        self.adv.setObjectName("FW_MoveAdvanced")
        for box in (self.highlight, self.sound, self.ignore_complex, self.this_config):
            alay.addWidget(box)

        # while dragging, and the drag can stop at a set clearance
        self.clear_group, clay2 = _box("Dynamic Clearance")
        self.clear_group.setObjectName("FW_DynClearance")
        self.clear_on = QtWidgets.QCheckBox("Dynamic Clearance")
        self.clear_on.setObjectName("FW_DynClearanceOn")
        clay2.addWidget(self.clear_on)
        clay2.addWidget(QtWidgets.QLabel("Components for Collision Check:"))
        self.clear_list = QtWidgets.QListWidget()
        self.clear_list.setObjectName("FW_ClearanceList")
        self.clear_list.setStyleSheet(PICK_STYLE)
        self.clear_list.setFixedHeight(_rows(self.clear_list, 3))
        clay2.addWidget(self.clear_list)
        self.clear_resume = QtWidgets.QPushButton("Resume Drag")
        self.clear_resume.setObjectName("FW_ClearanceResume")
        self.clear_resume.clicked.connect(self._clearance_resume)
        clay2.addWidget(self.clear_resume, 0, Qt.AlignLeft)
        row = QtWidgets.QHBoxLayout()
        self.clear_stop = QtWidgets.QCheckBox("Stop at specified clearance")
        self.clear_stop.setObjectName("FW_ClearanceStop")
        self.clear_value = QtWidgets.QDoubleSpinBox()
        self.clear_value.setObjectName("FW_ClearanceValue")
        self.clear_value.setRange(0.0, 1.0e5)
        self.clear_value.setDecimals(2)
        self.clear_value.setSuffix("mm")
        self.clear_value.setValue(10.0)
        clay2.addWidget(self.clear_stop)
        row.addSpacing(20)
        row.addWidget(self.clear_value, 1)
        clay2.addLayout(row)
        self.clear_now = QtWidgets.QLabel("")
        self.clear_now.setObjectName("FW_ClearanceNow")
        clay2.addWidget(self.clear_now)
        self.clear_comps = []
        self.clear_on.toggled.connect(self._clearance_toggled)
        self._clearance_toggled(False)
        self.these_comps = []
        from . import asmcollide
        self.watch = asmcollide.install(self)
        self._option_changed()
        self.form = ([rot, move, opts] if rotate else [move, rot, opts]) + [self.adv, self.clear_group]
        self.rotating = rotate
        self._modes()
        self.comps = []
        Gui.Selection.addObserver(self, 0)
        from . import safe_later as _sl; _sl.later(0, self._from_selection, self, "list")
        QtCore.QTimer.singleShot(0, self._option_changed)     # the groups' boxes exist once shown

    def option(self):
        return next((n for n, b in self.options.items() if b.isChecked()), "Standard Drag")

    def _option_changed(self):
        if not hasattr(self, "dyn_box"):
            return          # still being built
        mode = self.option()

        # Physical Dynamics; Stop at collision and Dragged part only under Collision Detection
        self.collide_box.setVisible(mode in ("Collision Detection", "Physical Dynamics"))
        for w in (self.stop_at, self.dragged_only):
            w.setVisible(mode == "Collision Detection")
        self.dyn_box.setVisible(mode == "Physical Dynamics")
        group_visible(self.adv, mode == "Collision Detection")
        if getattr(self, "watch", None) is not None:
            self.watch.unlight()
            self.watch.snapshot()

    def these(self):
        return list(self.these_comps)

    def _resume_drag(self):
        """These components: the components picked so far are the ones checked; drag on."""
        self.these_comps = list(self.comps)
        self.these_list.clear()
        for c in self.these_comps:
            self.these_list.addItem(c.Label)

    def _clearance_toggled(self, on):
        from .asmpattern import _takes_over
        for w in (self.clear_list, self.clear_resume, self.clear_stop, self.clear_value):
            if not hasattr(w, "_fw_take_over"):
                _takes_over(w, self.clear_on, True)     # live: using one turns Dynamic Clearance on
        if not on:
            self.clear_now.setText("")

    def _clearance_resume(self):
        """Components for Collision Check: the components picked so far; drag on."""
        self.clear_comps = list(self.comps)
        self.clear_list.clear()
        for c in self.clear_comps:
            self.clear_list.addItem(c.Label)
        self.clearance()

    def clearance(self):
        ""

        comps = [c for c in self.clear_comps if c in ac.components(self.asm)]
        if not self.clear_on.isChecked() or len(comps) < 2:
            return None
        best = None
        for i, a in enumerate(comps):
            for b in comps[i + 1:]:
                try:
                    d = a.Shape.distToShape(b.Shape)[0]
                except Exception:
                    continue
                best = d if best is None else min(best, d)
        if best is not None:
            self.clear_now.setText("Clearance: %.2fmm" % best)
        return best

    def clearance_stop(self):
        """Stop at specified clearance: True when the drag came closer than the value."""
        d = self.clearance()
        return d is not None and self.clear_stop.isChecked() and d < self.clear_value.value() - 1e-6

    # ------------------------------------------------------------ drag kept to an axis / entity
    def constrain(self, comp, start):
        """The dragged component's placement kept to the Move / Rotate mode (None: as it is)."""
        now = comp.Placement
        mm, rm = self.move_mode.currentText(), self.rot_mode.currentText()
        d = now.Base - start.Base
        if rm == "About Entity" and self.entity["rotate"] is not None:
            try:
                centre = comp.Shape.BoundBox.Center - (now.Base - start.Base)
            except Exception:
                centre = start.Base
            return about(start, now, self.entity["rotate"][0], centre)
        if getattr(self, "rotating", False) and rm == "Free Drag":
            return self._free_turn(comp, start, now)
        if mm == "Along Assembly XYZ":
            return App.Placement(start.Base + along_xyz(d), start.Rotation)
        if mm == "Along Entity" and self.entity["move"] is not None:
            return App.Placement(start.Base + along(d, self.entity["move"][0]), start.Rotation)
        return None

    def _free_turn(self, comp, start, now):
        ""



        import math
        d = now.Base - start.Base
        key = (comp.Name, tuple(start.Base), tuple(start.Rotation.Q))
        st = getattr(self, "_turn", None)
        if st is None or st[0] != key:
            try:
                box = comp.Shape.BoundBox
                local = start.inverse().multVec(box.Center - d)
                size = max(box.DiagonalLength / 2.0, 1.0)
            except Exception:
                local, size = App.Vector(), 10.0
            st = self._turn = [key, App.Vector(), App.Placement(start), local, size]
        inc = d - st[1]
        if inc.Length < 1e-6:
            return App.Placement(st[2])
        try:
            look = Gui.ActiveDocument.ActiveView.getViewDirection()
        except Exception:
            look = App.Vector(0, 0, -1)
        axis = look.cross(inc)
        if axis.Length < 1e-9:
            return App.Placement(st[2])
        axis.normalize()
        last = st[2]
        centre = last.multVec(st[3])
        turn = App.Placement(App.Vector(), App.Rotation(axis, math.degrees(inc.Length / st[4])), centre)
        comp.Placement = turn.multiply(last)
        if ac.mates(self.asm):
            try:
                ac.follow_cross(self.asm, comp)           # a Universal Joint's other shaft turns with it
                ac.solve(self.asm)
                # the solver laid it back on its mates and let its centre slide: back under the pointer's
                # turn as far as the mates allow (a second solve keeps only what they let it keep)
                slip = centre - comp.Placement.multVec(st[3])
                if slip.Length > 1e-6:
                    comp.Placement = App.Placement(comp.Placement.Base + slip, comp.Placement.Rotation)
                    ac.solve(self.asm)
                ac.follow_mesh(self.asm, comp, last)      # a Gear / Rack Pinion partner turns as far as it turned
            except Exception as _fw_err:
                _fw_log("asmpm.py:free turn", _fw_err)
        st[1] = App.Vector(d)
        st[2] = App.Placement(comp.Placement)
        return App.Placement(comp.Placement)

    def _entity_field(self):
        if self.rot_mode.currentText() == "About Entity" and self.entity["rotate"] is None:
            return "rotate"
        if self.move_mode.currentText() == "Along Entity" and self.entity["move"] is None:
            return "move"
        return None

    def take_entity(self, field, root, sub):
        """Along Entity / About Entity: the picked edge, axis or face."""
        shape = None
        try:
            ref = ac.reference(self.asm, root, sub)
            shape = ac.element(*ref) if ref else None
        except Exception:
            shape = None
        if shape is None:
            try:
                obj = root.getSubObject(sub, 1)
                if obj is not None and obj.TypeId in ("App::Line", "App::Plane"):
                    pl = obj.getGlobalPlacement()
                    z = pl.Rotation.multVec(App.Vector(1, 0, 0) if obj.TypeId == "App::Line" else App.Vector(0, 0, 1))
                    if obj.TypeId == "App::Line" and getattr(obj, "Role", "") in ("Y_Axis",):
                        z = pl.Rotation.multVec(App.Vector(1, 0, 0))
                    frame = ("line" if obj.TypeId == "App::Line" else "plane", pl.Base, z)
                    return self._set_entity(field, frame, root, sub, obj.Label)
            except Exception as _fw_err:
                _fw_log("asmpm.py:4639", _fw_err)
            return False
        frame = entity_frame(shape)
        if frame is None or (field == "rotate" and frame[0] != "line"):
            return False
        return self._set_entity(field, frame, root, sub, (ref[0].Label + "/" + sub.split(".")[-1]))

    def _set_entity(self, field, frame, root, sub, text):
        self.entity[field] = (frame, (root.Name, sub))
        (self.rot_entity if field == "rotate" else self.move_entity).setText(text)
        return True

    # ------------------------------------------------------------ SmartMates
    def _smart_toggled(self, on):
        self.smart_first = None
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "SmartMates: double-click an entity of the component to move" if on else "", 0)
        except Exception as _fw_err:
            _fw_log("asmpm.py:4658", _fw_err)

    def smart_pick(self, root, sub):
        ""


        ref = ac.reference(self.asm, root, sub)
        if ref is None:
            return None
        if self.smart_first is None:
            self.smart_first = ref
            try:
                Gui.getMainWindow().statusBar().showMessage("SmartMates: click the entity to mate to", 0)
            except Exception as _fw_err:
                _fw_log("asmpm.py:4672", _fw_err)
            return None
        first, self.smart_first = self.smart_first, None
        joint = smart_mate(self.asm, first, ref)
        self.watch.snapshot()
        return joint

    def _modes(self, *args):
        ent = self.move_mode.currentText() == "Along Entity"
        self.move_entity.setVisible(ent)
        if not ent:
            self.entity["move"] = None
            self.move_entity.clear()
        rent = self.rot_mode.currentText() == "About Entity"
        self.rot_entity.setVisible(rent)
        if not rent:
            self.entity["rotate"] = None
            self.rot_entity.clear()
        delta = self.move_mode.currentText() in ("By Delta XYZ", "To XYZ Position")
        for spin in self.move_spins:
            spin.setEnabled(delta)
        self.apply_move.setEnabled(delta)
        rdelta = self.rot_mode.currentText() == "By Delta XYZ"
        for spin in self.rot_spins:
            spin.setEnabled(rdelta)
        self.apply_rot.setEnabled(rdelta)

        to_xyz = self.move_mode.currentText() == "To XYZ Position"
        for grid, spins, button, on in ((getattr(self, "move_grid", None), self.move_spins, self.apply_move, delta),
                                        (getattr(self, "rot_grid", None), self.rot_spins, self.apply_rot, rdelta)):
            for axis, spin in zip("XYZ", spins):
                spin.setVisible(on)
                label = grid.labelForField(spin) if grid is not None else None
                if label is not None:
                    label.setVisible(on)
                    if spins is self.move_spins:
                        label.setText(axis if to_xyz else "Δ%s" % axis)
            button.setVisible(on)
        if to_xyz and getattr(self, "comps", None):
            self._xyz_now()

    def _from_selection(self):
        try:
            import shiboken6
            if not shiboken6.isValid(self.list):
                return          # the panel is closed: this call was queued before it (lifetime2-1126)
        except Exception:
            pass
        comps = []
        points = {}
        taken = {e[1] for e in self.entity.values() if e is not None}
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames or [""]:
                if (sel.Object.Name, sub) in taken:
                    continue
                ref = ac.reference(self.asm, sel.Object, sub) if sub else None
                comp = ref[0] if ref else (sel.Object if sel.Object in ac.components(self.asm) else None)
                if comp is None and sub:
                    # a component picked in the tree (the flyout too): its row gives "Comp." with no

                    head = sel.Object.getSubObject(sub, retType=1) if hasattr(sel.Object, "getSubObject") else None
                    for c in ac.components(self.asm):
                        if c is head or c.Name == sub.split(".")[0] or (sub.endswith(".") and c.Name == sub.rstrip(".").split(".")[-1]):
                            comp = c
                            break
                if comp is not None and comp not in comps:
                    comps.append(comp)
                if comp is not None and ref and ref[1].split(".")[-1].startswith("Vertex"):
                    try:
                        v = ac.element(*ref[:2])
                        if v is not None and hasattr(v, "Point"):
                            points[comp.Name] = App.Vector(v.Point) - comp.Placement.Base
                    except Exception as _fw_err:
                        _fw_log("asmpm.py:move point", _fw_err)
        self.comps = comps
        self.points = points
        self.list.clear()
        for comp in comps:
            self.list.addItem(comp.Label)
        self._xyz_now()

    def _xyz_now(self):
        """To XYZ Position shows where the first component's picked point (else its origin) is now."""
        if self.move_mode.currentText() != "To XYZ Position" or not self.comps:
            return
        c = self.comps[0]
        here = c.Placement.Base + getattr(self, "points", {}).get(c.Name, App.Vector())
        for spin, v in zip(self.move_spins, (here.x, here.y, here.z)):
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)

    def _to_base(self, comp, d):
        """To XYZ Position: the component's base that puts its picked point (else origin) at d."""
        return d - getattr(self, "points", {}).get(comp.Name, App.Vector())

    def addSelection(self, doc=None, obj=None, sub=None, pnt=None, *args):
        try:
            root = App.getDocument(doc).getObject(obj) if doc and obj else None
        except Exception:
            root = None
        if root is not None and sub:
            if self.smart.isChecked():
                QtCore.QTimer.singleShot(0, lambda: self.smart_pick(root, sub))
                return
            field = self._entity_field()
            if field is not None and self.take_entity(field, root, sub):
                from . import safe_later as _sl; _sl.later(0, self._from_selection, self, "list")
                return
        from . import safe_later as _sl; _sl.later(0, self._from_selection, self, "list")

    def removeSelection(self, *args):
        from . import safe_later as _sl; _sl.later(0, self._from_selection, self, "list")

    def clearSelection(self, *args):
        from . import safe_later as _sl; _sl.later(0, self._from_selection, self, "list")

    def _movable(self):
        fixed = ac.grounded(self.asm)
        return [c for c in self.comps if c not in fixed]

    def do_move(self):
        d = App.Vector(*[s.value() for s in self.move_spins])
        comps = self._movable()
        if not comps:
            return
        self.doc.openTransaction("Move Component")
        try:
            self.watch.snapshot()
            was = []
            for comp in comps:
                plc = App.Placement(comp.Placement)
                if self.move_mode.currentText() == "To XYZ Position":
                    plc.Base = self._to_base(comp, d)
                else:
                    plc.Base = plc.Base + d
                was.append((comp, App.Placement(comp.Placement)))
                comp.Placement = plc
                ac.follow_cross(self.asm, comp)           # a Universal Joint's other shaft turns with it
            ac.solve(self.asm)
            for comp, before in was:
                ac.follow_mesh(self.asm, comp, before)    # a rack moved as far as its mates let it: its pinion turns
            if self.watch.tick() and self.option() == "Collision Detection" and self.stop_at.isChecked():
                self._stop_at_touch(comps, d)
            self.doc.recompute()
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()

    def _stop_at_touch(self, comps, d):
        """Stop at collision on a typed move: as far along the move as it goes without overlapping."""
        from . import asmcollide
        start = {c.Name: App.Placement(c.Placement) for c in comps}
        to = self.move_mode.currentText() == "To XYZ Position"
        among = self.these() if self.check_these.isChecked() else None
        lo, hi = 0.0, 1.0
        for _i in range(20):
            mid = (lo + hi) / 2.0
            for c in comps:
                p0 = start[c.Name]
                step = (self._to_base(c, d) - p0.Base) * mid if to else d * mid
                c.Placement = App.Placement(p0.Base + step, p0.Rotation)
            if asmcollide.collisions(self.asm, comps, among):
                hi = mid
            else:
                lo = mid
        for c in comps:
            p0 = start[c.Name]
            step = (self._to_base(c, d) - p0.Base) * lo if to else d * lo
            c.Placement = App.Placement(p0.Base + step, p0.Rotation)
        self.watch.snapshot()

    def do_rotate(self):
        rx, ry, rz = [s.value() for s in self.rot_spins]
        comps = self._movable()
        if not comps:
            return
        self.doc.openTransaction("Rotate Component")
        try:
            self.watch.snapshot()
            turn = App.Rotation(rz, ry, rx)
            was = []
            for comp in comps:
                plc = App.Placement(comp.Placement)
                centre = comp.Shape.BoundBox.Center if comp.Shape.BoundBox.isValid() else plc.Base
                # about the component's own centre, along the assembly's axes
                comp.Placement = App.Placement(App.Vector(), turn, centre) * plc
                was.append((comp, plc))
                ac.follow_cross(self.asm, comp)           # a Universal Joint's other shaft turns with it
            ac.solve(self.asm)
            for comp, before in was:
                ac.follow_mesh(self.asm, comp, before)    # a Gear / Rack Pinion partner turns as far as it turned
            self.watch.tick()
            self.doc.recompute()
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()

    def _finish(self):
        Gui.Selection.removeObserver(self)
        from . import asmcollide
        asmcollide.remove(getattr(self, "watch", None))
        self.watch = None

    def accept(self):
        self._finish()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._finish()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok
