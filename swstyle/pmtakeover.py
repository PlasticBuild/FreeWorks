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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

MIRROR, LINEAR, POLAR = "PartDesign::Mirrored", "PartDesign::LinearPattern", "PartDesign::PolarPattern"
COMMANDS = {"PartDesign_Mirrored": "SWStyle_Mirror", "PartDesign_LinearPattern": "SWStyle_LinearPattern",
            "PartDesign_PolarPattern": "SWStyle_CircularPattern"}
_passing = [False]
_created = {}
_observers = []


def enabled():
    return paths.params().GetBool("SolidWorksPages", True)


# --------------------------------------------------------------------------- views
def view_widget():
    """The 3D view's drawing widget (where Escape and clicks arrive)."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi is not None else None
    for root in ([sub.widget()] if sub is not None else []) + [Gui.getMainWindow()]:
        for w in root.findChildren(QtWidgets.QGraphicsView):
            if w.isVisible():
                return w.viewport()
    return None


def hook_escape(panel):
    """The pages looked for the view as a QOpenGLWidget, which FreeCAD 1.1's view is not seen
    as from Python, so Esc never reached them: hook the view's viewport instead."""
    view = view_widget()
    if view is not None and getattr(panel, "_esc", None) is not None and view not in panel._views:
        view.installEventFilter(panel._esc)
        panel._views.append(view)


# --------------------------------------------------------------------------- loading a feature
def _ref(link):
    """(obj, sub) from a link property value (obj, [subs]) or obj."""
    if link is None:
        return None
    if isinstance(link, (list, tuple)):
        if not link or link[0] is None:
            return None
        subs = link[1] if len(link) > 1 else []
        return (link[0], subs[0] if subs else "")
    return (link, "")


def _load_pattern(panel, f):
    panel.whole = getattr(f, "TransformMode", "Features") == "Whole shape"
    panel.features = [] if panel.whole else list(f.Originals)
    d1 = panel.dirs["dir1"]
    if f.TypeId == LINEAR:
        d1["ref"] = _ref(f.Direction)
        d1["reverse"] = bool(f.Reversed)
        d1["count"] = int(f.Occurrences)
        if getattr(f, "Mode", "Spacing") == "Spacing":
            d1["value"] = float(f.Offset.Value)
        else:
            d1["value"] = float(f.Length.Value) / max(1, int(f.Occurrences) - 1)
        if getattr(f, "Direction2", None) and int(getattr(f, "Occurrences2", 1)) > 1:
            d2 = panel.dirs["dir2"]
            d2["use"] = True
            d2["ref"] = _ref(f.Direction2)
            d2["reverse"] = bool(f.Reversed2)
            d2["count"] = int(f.Occurrences2)
            if getattr(f, "Mode2", "Spacing") == "Spacing":
                d2["value"] = float(f.Offset2.Value)
            else:
                d2["value"] = float(f.Length2.Value) / max(1, int(f.Occurrences2) - 1)
    else:
        d1["ref"] = _ref(f.Axis)
        d1["reverse"] = bool(f.Reversed)
        d1["count"] = int(f.Occurrences)
        if getattr(f, "Mode", "Extent") == "Extent":
            d1["equal"] = True
            d1["value"] = float(f.Angle.Value)
        else:
            d1["equal"] = False
            d1["value"] = float(f.Offset.Value)


def _load_mirror(panel, f):
    panel.whole = getattr(f, "TransformMode", "Features") == "Whole shape"
    panel.features = [] if panel.whole else list(f.Originals)
    panel.plane = _ref(f.MirrorPlane)
    panel.active = "features"


def _links(value):
    """[(obj, sub)] from a LinkSubList value."""
    out = []
    for item in value or []:
        if isinstance(item, (list, tuple)):
            obj, subs = item[0], (item[1] if len(item) > 1 else [])
            if isinstance(subs, str):
                subs = [subs]
            if obj is not None:
                out.extend((obj, sub) for sub in (subs or [""]))
        elif item is not None:
            out.append((item, ""))
    return out


def _first(value):
    links = _links(value)
    return links[0] if links else None


def _load_own_pattern(panel, f):
    ""

    from . import patterns
    panel.whole = False
    panel.features = [o for o, _ in _links(getattr(f, "Features", []))]
    panel.faces = _links(getattr(f, "Faces", []))
    d1, d2 = panel.dirs["dir1"], panel.dirs["dir2"]
    if f.SWStyleKind == patterns.LINEAR.internal:
        d1["ref"] = _first(f.Direction1)
        d1["reverse"] = bool(f.Reverse1)
        d1["value"] = float(f.Spacing1)
        d1["count"] = int(f.Count1)
        d2["use"] = bool(f.UseDirection2)
        d2["ref"] = _first(f.Direction2) if f.UseDirection2 else None
        d2["reverse"] = bool(f.Reverse2)
        d2["value"] = float(f.Spacing2)
        d2["count"] = int(f.Count2)
        d2["seed"] = bool(f.SeedOnly)

        d2["symmetric"] = bool(f.UseDirection2 and f.SeedOnly and d2["ref"] is not None and d2["ref"] == d1["ref"]
                               and d2["reverse"] != d1["reverse"] and d2["count"] == d1["count"]
                               and abs(d2["value"] - d1["value"]) < 1e-9)
        if d2["symmetric"]:

            d2.update(ref=None, reverse=False, seed=False, count=1)
        for k, d in ((1, d1), (2, d2)):
            # Up to reference (features/103): files made before it lack the fields
            d["upto"] = getattr(f, "Mode%d" % k, "") == patterns.UP_TO_REFERENCE
            d["upto_ref"] = _first(getattr(f, "Reference%d" % k, []))
            d["offset"] = float(getattr(f, "Offset%d" % k, 0.0))
            d["reverse_offset"] = bool(getattr(f, "ReverseOffset%d" % k, False))
            d["ref_from"] = getattr(f, "RefFrom%d" % k, "Centroid") == "Selected reference"
            d["seed_ref"] = _first(getattr(f, "SeedReference%d" % k, []))
            d["set_by"] = "count" if getattr(f, "SetBy%d" % k, "") == "Set number of instances" else "spacing"
        panel.skip = set(patterns.parse_skip(f.Skip))
    else:
        d1["ref"] = _first(f.Axis)
        d1["reverse"] = bool(f.Reverse1)
        d1["equal"] = bool(f.EqualSpacing)
        d1["value"] = float(f.Angle)
        d1["count"] = int(f.Count1)
        d2["use"] = bool(f.UseDirection2)
        d2["symmetric"] = bool(f.Symmetric)
        d2["equal"] = bool(getattr(f, "EqualSpacing2", True))
        d2["value"] = float(getattr(f, "Angle2", 0.0) or f.Angle)
        d2["count"] = int(f.Count2)
        panel.skip = {(k, 1) for k, _ in patterns.parse_skip(f.Skip)}
    panel.vary = bool(f.VarySketch)
    panel.geometry = bool(f.GeometryPattern)
    panel.propagate = bool(f.Propagate)
    if hasattr(panel, "load_vary") and "VaryInstances" in f.PropertiesList:
        panel.load_vary(f)


def _load_own_mirror(panel, f):
    panel.whole = bool(f.Whole)
    panel.features = [] if panel.whole else [o for o, _ in _links(getattr(f, "Features", []))]
    panel.faces = _links(getattr(f, "Faces", []))
    panel.plane = _first(f.Plane)
    panel.plane2 = _first(f.Plane2)
    for box, value in ((panel.geometry, f.GeometryPattern), (panel.propagate, f.Propagate)):
        box.blockSignals(True)
        box.setChecked(bool(value))
        box.blockSignals(False)
    panel.active = "features"


def kind_of(feature):
    ""
    from . import patterns
    type_id = feature.TypeId
    if type_id == MIRROR:
        return "mirror"
    if type_id == LINEAR:
        return "linear"
    if type_id == POLAR:
        return "circular"
    kind = getattr(feature, "SWStyleKind", "")
    if kind == patterns.MIRROR.internal:
        return "mirror"
    if kind == patterns.LINEAR.internal:
        return "linear"
    if kind == patterns.CIRCULAR.internal:
        return "circular"
    return None


def edit_panel(feature):
    ""

    body = feature.getParentGeoFeatureGroup()
    kind = kind_of(feature)
    if body is None or kind is None:
        return None
    doc = feature.Document
    own = feature.TypeId not in (MIRROR, LINEAR, POLAR)
    if kind == "mirror":
        from . import mirrorpm
        panel = mirrorpm.MirrorPanel(doc, body, [])
        (_load_own_mirror if own else _load_mirror)(panel, feature)
        panel.mirror = feature
    else:
        from . import patternpm
        cls = patternpm.LinearPanel if kind == "linear" else patternpm.CircularPanel
        panel = cls(doc, body, [])
        (_load_own_pattern if own else _load_pattern)(panel, feature)
        panel.pattern = feature
    panel.before = feature.BaseFeature
    panel.edited = feature
    doc.openTransaction("Edit " + feature.Label)
    try:
        panel.opened = True
        # never delete the feature being edited when its picks are cleared
        panel._drop = lambda: None
        first = panel.form[0]
        first.setProperty("swstyle_pm_title", feature.Label)
        panel.update()
        hook_escape(panel)
        close = panel._close

        def close_and_reset():
            close()
            try:
                # an own feature's Edit Feature went through FreeCAD's edit mode: leave it
                gdoc = Gui.getDocument(doc.Name)
                edit = gdoc.getInEdit()
                if edit is not None and getattr(edit, "Object", None) is not None:
                    gdoc.resetEdit()
            except Exception as _fw_err:
                _fw_log("pmtakeover.py:268", _fw_err)
        panel._close = close_and_reset
        return panel
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


def open_edit(feature):
    ""
    panel = edit_panel(feature)
    if panel is None:
        return False
    Gui.Control.showDialog(panel)
    return True


# --------------------------------------------------------------------------- taking over
def _in_task_view(w):
    while w is not None:
        if "TaskView" in w.metaObject().className():
            return True
        w = w.parentWidget()
    return False


def native_panels():
    """FreeCAD's own pattern / mirror panels open in the task view."""
    out = []
    for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
        name = w.metaObject().className()
        if name.startswith("PartDesignGui::Task") and ("Pattern" in name or "Mirrored" in name or
                                                       "Transformed" in name or "MultiTransform" in name):
            out.append(w)
    return out


def _native_cancel():
    """The Cancel of the panel in the task view now (a hidden box left by an earlier panel is not it)."""
    found = []
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(QtWidgets.QDialogButtonBox.Cancel)
        if button is not None and box.window() is Gui.getMainWindow():
            found.append((_in_task_view(box), box, button))
    inside = [b for ok, _box, b in found if ok]
    if inside:
        return inside[-1]
    return found[-1][2] if found else None


def take_over(obj, tries=0):
    if obj is None:
        return
    try:
        doc, name, type_id = obj.Document, obj.Name, obj.TypeId
        made = _created.pop(doc.Name + "." + name, None)
        fresh = made is not None and time.time() - made < 0.5
        originals = [(o.Document.Name, o.Name) for o in getattr(obj, "Originals", [])] if fresh else []
    except Exception:
        return
    cancel = _native_cancel()
    App.Console.PrintLog("FreeCAD takeover %s fresh=%s cancel=%s\n" % (name, fresh, cancel is not None))
    if cancel is None:
        # a slow machine builds FreeCAD's panel after the edit starts: look again (up to 3 s)
        if tries < 30 and _still_editing(obj):
            if made is not None:
                _created[doc.Name + "." + name] = made
            QtCore.QTimer.singleShot(100, lambda: take_over(obj, tries + 1))
        return
    cancel.click()

    def start(left=10):
        if Gui.Control.activeDialog():
            if left > 0 and (native_panels() or _still_editing(obj)):
                # the click went to another box, or FreeCAD's panel is slow to go: close it here
                App.Console.PrintLog("FreeCAD takeover: closing FreeCAD's panel\n")
                try:
                    Gui.Control.closeDialog()
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:344", _fw_err)
                try:
                    Gui.getDocument(doc.Name).resetEdit()
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:348", _fw_err)
                QtCore.QTimer.singleShot(100, lambda: start(left - 1))
                return
            App.Console.PrintLog("FreeCAD takeover: a dialog is still open\n")
            return
        if fresh:
            Gui.Selection.clearSelection()
            for d, n in originals:
                try:
                    Gui.Selection.addSelection(d, n)
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:359", _fw_err)
            command = {MIRROR: "SWStyle_Mirror", LINEAR: "SWStyle_LinearPattern",
                       POLAR: "SWStyle_CircularPattern"}[type_id]
            run_native(command)
        else:
            feature = doc.getObject(name)
            if feature is not None:
                open_edit(feature)
    QtCore.QTimer.singleShot(0, start)


def take_over_hole(obj, tries=0):
    """Edit Feature on a Hole Wizard hole: FreeCAD's Hole panel goes, the Hole Wizard's Type tab comes."""
    from . import holespec
    try:
        doc, name = obj.Document, obj.Name
    except Exception:
        return
    cancel = _native_cancel()
    App.Console.PrintLog("FreeCAD takeover %s hole cancel=%s\n" % (name, cancel is not None))
    if cancel is None:
        if tries < 30 and _still_editing(obj):
            QtCore.QTimer.singleShot(100, lambda: take_over_hole(obj, tries + 1))
        return
    cancel.click()

    def start(left=10):
        if Gui.Control.activeDialog():
            if left > 0:
                try:
                    Gui.Control.closeDialog()
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:391", _fw_err)
                try:
                    Gui.getDocument(doc.Name).resetEdit()
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:395", _fw_err)
                QtCore.QTimer.singleShot(100, lambda: start(left - 1))
                return
            return
        feature = doc.getObject(name)
        if feature is not None:
            holespec.edit(feature)
    QtCore.QTimer.singleShot(0, start)


def _still_editing(obj):
    try:
        gdoc = Gui.getDocument(obj.Document.Name)
        edit = gdoc.getInEdit()
        return edit is not None and editobj.of(edit) is obj
    except Exception:
        return False


class _AppObserver:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in (MIRROR, LINEAR, POLAR) and not obj.Document.Restoring:
                _created[obj.Document.Name + "." + obj.Name] = time.time()
        except Exception as _fw_err:
            _fw_log("pmtakeover.py:420", _fw_err)


class _GuiObserver:
    def slotInEdit(self, view_provider):
        try:
            obj = view_provider.Object
        except Exception:
            return
        if obj.TypeId in (MIRROR, LINEAR, POLAR) and enabled():
            QtCore.QTimer.singleShot(0, lambda: take_over(obj))
            return
        try:
            from . import holespec
            if holespec.edits(obj):
                QtCore.QTimer.singleShot(0, lambda: take_over_hole(obj))
        except Exception as _fw_err:
            _fw_log("pmtakeover.py:437", _fw_err)


def _has_body():
    ""
    try:
        from . import refplane
        return App.ActiveDocument is not None and refplane.body_of(App.ActiveDocument) is not None
    except Exception:
        return False


def run_native(name):
    original = getattr(Gui.runCommand, "freeworks_takeover_original", Gui.runCommand)
    _passing[0] = True
    try:
        original(name, 0)
    finally:
        _passing[0] = False


def _hook_commands():
    if not hasattr(Gui.runCommand, "freeworks_takeover_original"):
        original = Gui.runCommand

        def run_command(name, *args, **kw):
            if name in COMMANDS and not _passing[0] and enabled() and not Gui.Control.activeDialog() \
                    and COMMANDS[name] in Gui.listCommands() and _has_body():
                return original(COMMANDS[name], *args, **kw)
            return original(name, *args, **kw)
        for attr in dir(original):      # keep the marks of earlier wrappers
            if attr.startswith("swstyle_") or attr.startswith("freeworks_"):
                try:
                    setattr(run_command, attr, getattr(original, attr))
                except Exception as _fw_err:
                    _fw_log("pmtakeover.py:472", _fw_err)
        run_command.freeworks_takeover_original = original
        Gui.runCommand = run_command
    for name in COMMANDS:
        try:
            actions = Gui.Command.get(name).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action is None or action.property("freeworks_takeover"):
                continue
            try:
                action.triggered.disconnect()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s not hooked: %s\n" % (name, error))
                continue
            action.setProperty("freeworks_takeover", True)
            action.triggered.connect(lambda checked=False, n=name: Gui.runCommand(n, 0))


def _patch_pages():
    ""
    try:
        from . import mirrorpm, patternpm
    except Exception:
        return
    for cls in (mirrorpm.MirrorPanel, patternpm.PatternPanel):
        if getattr(cls, "_freeworks_esc", False):
            continue
        init = cls.__init__

        def wrapped(self, *args, _init=init, **kw):
            _init(self, *args, **kw)
            hook_escape(self)
        cls.__init__ = wrapped
        cls._freeworks_esc = True


def _own_pages():
    ""
    try:
        from . import patterns
        for spec in (patterns.LINEAR, patterns.CIRCULAR, patterns.MIRROR):
            spec.panel = edit_panel
        from . import simplefeature as sf
        if not getattr(sf.View, "_freeworks_edit", False):
            # a file saved clean gets its view class back without attach(): the view then knows
            # no Object, finds no Spec and opened the generic page (C13-06 on a saved pattern)
            original = sf.View.setEdit

            def set_edit(self, vobj, mode=0, _original=original):
                if getattr(self, "Object", None) is None:
                    try:
                        self.Object = vobj.Object
                    except Exception as _fw_err:
                        _fw_log("pmtakeover.py:527", _fw_err)
                return _original(self, vobj, mode)
            sf.View.setEdit = set_edit
            sf.View._freeworks_edit = True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: own pattern pages not hooked: %s\n" % error)


def install():
    _hook_commands()
    _patch_pages()
    _own_pages()
    if _observers:
        return
    a, g = _AppObserver(), _GuiObserver()
    App.addDocumentObserver(a)
    Gui.addDocumentObserver(g)
    _observers.extend([a, g])
