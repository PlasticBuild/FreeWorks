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

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"
PREFS = "User parameter:BaseApp/Preferences"


def _mw():
    return Gui.getMainWindow()


# --------------------------------------------------------------------- Automatic Solve
def automatic_solve():
    return App.ParamGet(SKETCHER).GetBool("AutoRecompute", False)


class AutomaticSolve:
    def GetResources(self):
        return {"MenuText": "Automatic Solve", "Checkable": automatic_solve(), "CmdType": "ForEdit",
                "ToolTip": "On: the part follows each change in the sketch at once. Off: it waits for Rebuild."}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, checked=None):
        on = (not automatic_solve()) if checked is None else bool(checked)
        App.ParamGet(SKETCHER).SetBool("AutoRecompute", on)


# --------------------------------------------------------------------- Simplify
KINDS = (("Fillets", ("PartDesign::Fillet",), "fillet"),
         ("Chamfers", ("PartDesign::Chamfer",), "chamfer"),
         ("Holes and cuts", ("PartDesign::Hole", "PartDesign::Pocket", "PartDesign::Groove"), "cut"))


def _size(feature):
    """The size Simplify compares: a fillet's radius, a chamfer's size, a hole's diameter, else
    the largest side of what the feature took away."""
    try:
        if feature.TypeId == "PartDesign::Fillet":
            return float(feature.Radius)
        if feature.TypeId == "PartDesign::Chamfer":
            return float(feature.Size)
        if feature.TypeId == "PartDesign::Hole":
            return float(feature.Diameter)
        if feature.TypeId.startswith("PartDesign::FeaturePython") and hasattr(feature, "Radius"):
            return float(feature.Radius)
        sub = getattr(feature, "AddSubShape", None)
        if sub is not None and not sub.isNull():
            bb = sub.BoundBox
            return min(bb.XLength, bb.YLength, bb.ZLength) if feature.TypeId != "PartDesign::Pocket" else \
                max(bb.XLength, bb.YLength)
    except Exception as _fw_err:
        _fw_log("toolsextras.py:86", _fw_err)
    return None


def _kind(feature):
    for label, types, key in KINDS:
        if feature.TypeId in types:
            return key
    if getattr(feature, "SWStyleKind", "") in ("SetbackFillet", "MultiRadiusFillet") or \
            "Fillet" in feature.TypeId:
        return "fillet"
    return None


def small_features(doc, kinds, limit):
    """[(feature, kind, size)] of the part's features of those kinds smaller than limit."""
    out = []
    for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
        for f in body.Group:
            k = _kind(f)
            if k is None or k not in kinds:
                continue
            s = _size(f)
            if s is not None and s <= limit + 1e-9:
                out.append((f, k, s))
    return out


def set_suppressed(doc, features, on):
    doc.openTransaction("Suppress" if on else "Unsuppress")
    try:
        for f in features:
            if "Suppressed" in f.PropertiesList:
                f.Suppressed = on
        doc.recompute()
    finally:
        doc.commitTransaction()


class SimplifyDialog(QtWidgets.QDialog):
    def __init__(self, doc):
        super().__init__(_mw())
        self.doc = doc
        self.setWindowTitle("Simplify")
        self.setObjectName("SWSimplify")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Find features to simplify:", self))
        self.kinds = {}
        for label, _types, key in KINDS:
            c = QtWidgets.QCheckBox(label, self)
            c.setObjectName("SWSimplify_" + key)
            c.setChecked(True)
            lay.addWidget(c)
            self.kinds[key] = c
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Simplify factor (largest size, mm)", self))
        self.limit = QtWidgets.QDoubleSpinBox(self)
        self.limit.setObjectName("SWSimplifyLimit")
        self.limit.setRange(0.001, 10000.0)
        self.limit.setValue(self._default())
        row.addWidget(self.limit)
        lay.addLayout(row)
        find = QtWidgets.QPushButton("Find Now", self)
        find.setObjectName("SWSimplifyFind")
        find.clicked.connect(self.find)
        lay.addWidget(find)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWSimplifyResults")
        lay.addWidget(self.list)
        buttons = QtWidgets.QHBoxLayout()
        self.suppress = QtWidgets.QPushButton("Suppress", self)
        self.suppress.setObjectName("SWSimplifySuppress")
        self.suppress.clicked.connect(lambda: self.apply(True))
        self.unsuppress = QtWidgets.QPushButton("Unsuppress", self)
        self.unsuppress.setObjectName("SWSimplifyUnsuppress")
        self.unsuppress.clicked.connect(lambda: self.apply(False))
        close = QtWidgets.QPushButton("Close", self)
        close.clicked.connect(self.accept)
        for b in (self.suppress, self.unsuppress, close):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.found = []
        self.find()

    def _default(self):
        ""
        try:
            sizes = [o.Shape.BoundBox.DiagonalLength for o in self.doc.Objects
                     if o.TypeId == "PartDesign::Body" and not o.Shape.isNull()]
            return round(max(sizes) * 0.05, 2) if sizes else 5.0
        except Exception:
            return 5.0

    def find(self):
        kinds = [k for k, c in self.kinds.items() if c.isChecked()]
        self.found = small_features(self.doc, kinds, self.limit.value())
        self.list.clear()
        for f, k, s in self.found:
            item = QtWidgets.QListWidgetItem("%s  (%s, %.2f mm)%s" % (
                f.Label, k, s, "  suppressed" if getattr(f, "Suppressed", False) else ""))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.list.addItem(item)

    def chosen(self):
        return [self.found[i][0] for i in range(self.list.count())
                if self.list.item(i).checkState() == QtCore.Qt.Checked]

    def apply(self, on):
        picked = self.chosen()
        if picked:
            set_suppressed(self.doc, picked, on)
        self.find()


class Simplify:
    def GetResources(self):
        return {"MenuText": "Simplify...",
                "ToolTip": "Finds the small fillets, chamfers and holes and suppresses the ones ticked."}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and any(o.TypeId == "PartDesign::Body" for o in doc.Objects)

    def Activated(self):
        try:
            from . import simplify
            simplify.open_simplify(App.ActiveDocument)
        except Exception:
            SimplifyDialog(App.ActiveDocument).show()


# --------------------------------------------------------------------- Format Painter
def _picked_dimension():
    """(sketch, constraint index) of the one sketch dimension picked, else None."""
    try:
        from . import contextbar, rcmenus
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return None
        for sel in Gui.Selection.getSelectionEx():
            for sub in sel.SubElementNames:
                i = rcmenus.constraint_index(sub.split(".")[-1])
                if i is not None and sketch.Constraints[i].Type in rcmenus.DIMENSION_TYPES:
                    return sketch, i
    except Exception as _fw_err:
        _fw_log("toolsextras.py:232", _fw_err)
    return None


class FormatPainter:
    def GetResources(self):
        return {"MenuText": "Format Painter...", "CmdType": "ForEdit",
                "ToolTip": "Pick a dimension, then the dimensions to take its display."}

    def IsActive(self):
        try:
            from . import contextbar
            if contextbar.sketch_in_edit() is not None:
                return True
            return App.ActiveDocument is not None and not Gui.Control.activeDialog()
        except Exception:
            return False

    def Activated(self):
        from . import rcextras, contextbar
        if contextbar.sketch_in_edit() is None:
            open_format_painter()
            return
        hit = _picked_dimension()
        if hit is not None:
            rcextras.format_painter(*hit)
            return
        # tool first: the next dimension picked is the source, then the painter takes over
        _SourcePick.start()


class _SourcePick:
    active = []

    @classmethod
    def start(cls):
        cls.stop()
        watcher = cls()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(watcher)
        cls.active.append(watcher)
        try:
            _mw().statusBar().showMessage("Format Painter: pick the dimension to copy the format from", 8000)
        except Exception as _fw_err:
            _fw_log("toolsextras.py:276", _fw_err)

    @classmethod
    def stop(cls):
        while cls.active:
            try:
                Gui.Selection.removeObserver(cls.active.pop())
            except Exception as _fw_err:
                _fw_log("toolsextras.py:284", _fw_err)

    def addSelection(self, doc, name, sub, pnt):
        QtCore.QTimer.singleShot(0, self._check)

    def _check(self):
        hit = _picked_dimension()
        if hit is None:
            return
        _SourcePick.stop()
        from . import rcextras
        Gui.Selection.clearSelection()
        rcextras.format_painter(*hit)


# the PropertyManager outside a sketch
TOL_KINDS = ("Size", "Location", "Angle", "BasicLocation", "BasicSize", "Pattern", "Reference")


def _pmi(obj):
    return getattr(obj, "SWStyleKind", "") == "PMI"


def paint_annotation(src, dst):
    """The source annotation's tolerance (and the document's precision) onto dst."""
    from . import mbd
    if not (_pmi(src) and _pmi(dst)) or dst.Kind not in TOL_KINDS or src.Kind not in TOL_KINDS:
        return False
    dst.Plus, dst.Minus = src.Plus, src.Minus
    text = dst.Text or ""
    prefix = ""
    for p in ("S⌀", "⌀", "R"):
        if text.startswith(p):
            prefix = p
            break
    if dst.Kind.startswith("Basic"):
        dst.Text = mbd.basic_text(dst.Document, dst.Value, prefix)
    else:
        dst.Text = mbd._tol_text(dst.Value, src.Plus, src.Minus, prefix)
    dst.AutoText = dst.Text
    dst.touch()
    return True


def _look_target(obj, sub):
    from . import appearance
    if sub.startswith("Face"):
        return appearance.target_for("face", obj, sub)
    if obj is not None and obj.TypeId == "PartDesign::Body":
        return appearance.target_for("body", obj, "")
    return appearance.target_for("feature", obj, sub)


def paint_look(src, dst):
    """(obj, sub) -> (obj, sub): the source face's / feature's appearance onto the destination."""
    from . import appearance
    a, b = _look_target(*src), _look_target(*dst)
    if a is None or b is None:
        return False
    appearance.apply([b], appearance.current_colour(a, False))
    return True


def paint(src, dst):
    if _pmi(src[0]):
        return paint_annotation(src[0], dst[0])
    if _pmi(dst[0]):
        return False
    return paint_look(src, dst)


class FormatPainterPM:
    ""

    def __init__(self, doc):
        self.doc = doc
        self.source = None
        self.painted = []
        box = QtWidgets.QWidget()
        box.setWindowTitle("Source")
        box.setProperty("swstyle_pm_title", "Format Painter")
        lay = QtWidgets.QVBoxLayout(box)
        self.src_list = QtWidgets.QListWidget()
        self.src_list.setObjectName("SWFormatPainterSource")
        self.src_list.setFixedHeight(26)
        lay.addWidget(QtWidgets.QLabel("Pick the annotation, face or feature to copy the format from."))
        lay.addWidget(self.src_list)
        box2 = QtWidgets.QWidget()
        box2.setWindowTitle("Destination")
        lay2 = QtWidgets.QVBoxLayout(box2)
        self.dst_list = QtWidgets.QListWidget()
        self.dst_list.setObjectName("SWFormatPainterDestination")
        self.dst_list.setFixedHeight(80)
        lay2.addWidget(QtWidgets.QLabel("Pick the ones to paint: each takes the format as it is picked."))
        lay2.addWidget(self.dst_list)
        self.form = [box, box2]
        self._style()
        for sel in Gui.Selection.getSelectionEx(doc.Name, 0):        # pick first: the first pick is the source
            subs = sel.SubElementNames or ("",)
            self._picked(sel.Object, subs[0].split(".")[-1])
            break
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def _style(self):
        for lst, on in ((self.src_list, self.source is None), (self.dst_list, self.source is not None)):
            lst.setStyleSheet("QListWidget { background: %s; }" % ("#cce4f7" if on else "#ffffff"))

    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        last = (sub or "").split(".")[-1]
        if obj is not None and sub and "." in sub:
            for part in sub.split(".")[:-1]:
                o = self.doc.getObject(part)
                if o is not None:
                    obj = o
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked(obj, last), self, "src_list")

    def _picked(self, obj, sub):
        if obj is None:
            return
        label = obj.Label + (("@" + sub) if sub else "")
        if self.source is None:
            self.source = (obj, sub)
            self.src_list.clear()
            self.src_list.addItem(label)
        else:
            self.doc.openTransaction("Format Painter")
            try:
                ok = paint(self.source, (obj, sub))
            finally:
                self.doc.commitTransaction()
            self.doc.recompute()
            if ok:
                self.painted.append((obj, sub))
                self.dst_list.addItem(label)
            else:
                _mw().statusBar().showMessage("Format Painter: %s cannot take the format of %s" %
                                              (label, self.src_list.item(0).text()), 6000)
        self._style()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("toolsextras.py:429", _fw_err)

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self._close()
        return True

    def reject(self):
        self._close()
        return True

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("toolsextras.py:446", _fw_err)
        Gui.Control.closeDialog()


LAST_PAINTER = [None]


def open_format_painter(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    pm = FormatPainterPM(doc)
    Gui.Control.showDialog(pm)
    LAST_PAINTER[0] = pm
    return pm


# --------------------------------------------------------------------- Macro
HEADER = "# -*- coding: utf-8 -*-\nimport FreeCAD as App\nimport FreeCADGui as Gui\n\n"


def _macro_dir():
    path = App.ParamGet("User parameter:BaseApp/Preferences/Macro").GetString("MacroPath", "")
    return path or App.getUserMacroDir(True)


class MacroNew:
    def GetResources(self):
        return {"MenuText": "New...", "ToolTip": "Makes a new macro file and opens it to write."}

    def IsActive(self):
        return True

    def Activated(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(_mw(), "New Macro", os.path.join(_macro_dir(), "Macro1.FCMacro"),
                                                        "Macros (*.FCMacro *.py)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".FCMacro"
        if not os.path.exists(path):
            with open(path, "w") as out:
                out.write(HEADER)
        Gui.open(path)


class MacroEdit:
    def GetResources(self):
        return {"MenuText": "Edit...", "ToolTip": "Opens a macro file to change it."}

    def IsActive(self):
        return True

    def Activated(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(_mw(), "Edit Macro", _macro_dir(), "Macros (*.FCMacro *.py)")
        if path:
            Gui.open(path)


class MacroRun:
    ""


    def GetResources(self):
        return {"MenuText": "Run...", "ToolTip": "Runs a macro file."}

    def IsActive(self):
        return True

    def Activated(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(_mw(), "Run Macro", _macro_dir(), "Macros (*.FCMacro *.py)")
        if path:
            run_macro(path)


def run_macro(path):
    """Runs the macro file at path the way FreeCAD's Macros box does. True when it ran without an error."""
    import sys
    import __main__
    folder = os.path.dirname(os.path.abspath(path))
    added = folder not in sys.path
    if added:
        sys.path.insert(0, folder)          # a macro may import the modules beside it, as FreeCAD's Macros box allows
    try:
        with open(path, encoding="utf-8") as fh:
            code = compile(fh.read(), path, "exec")
        # FreeCAD's own macro runner uses the Python console's names: recorded macros call App. and Gui. without
        # importing them (rv28)
        names = dict(__main__.__dict__)
        names.update({"__file__": path, "__name__": "__main__", "App": App, "Gui": Gui})
        exec(code, names)
        ok = True
    except Exception as error:
        ok = False
        QtWidgets.QMessageBox.critical(_mw(), "Run Macro", "%s stopped with an error:\n%s" % (os.path.basename(path), error))
    finally:
        if added:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass
    try:
        from . import optionsextras4
        optionsextras4._after_run()         # Options > General > Stop VSTA debugger on macro exit
    except Exception as _fw_err:
        _fw_log("toolsextras.py:macro_run", _fw_err)
    return ok


class MacroStop:
    """Stop: FreeCAD 1.1 stops a recording from its Record box (no command of its own), so this opens that box and
    presses its Stop, or says nothing is being recorded (extapps91)."""

    def GetResources(self):
        return {"MenuText": "Stop", "ToolTip": "Stops recording the macro."}

    def IsActive(self):
        return True

    def Activated(self):
        import time
        self._started = time.time()
        QtCore.QTimer.singleShot(0, self._press)
        Gui.runCommand("Std_DlgMacroRecord", 0)

    def _edit(self):
        try:
            # BB39 OP-2: Options > General > Automatically edit macro after recording (Stop runs FreeCAD's record
            # command from here, so the hook on its menu action never fires)
            from . import optionsextras4
            optionsextras4._after_record()
        except Exception as _fw_err:
            _fw_log("toolsextras.py:macro stop edit", _fw_err)

    def _press(self):
        box = QtWidgets.QApplication.activeModalWidget()
        stop = box.findChild(QtWidgets.QPushButton, "buttonStop") if box is not None else None
        if stop is not None and stop.isEnabled():
            stop.click()
            box.close()
            self._edit()
            return
        if box is not None:
            box.close()
        elif _wrote_macro(getattr(self, "_started", 0)):
            # FreeCAD 1.1 stops a running recording from the record command itself, with no box: the macro is saved
            self._edit()
            return
        _mw().statusBar().showMessage("No macro is being recorded.", 5000)


def _wrote_macro(since):
    """True when a macro was saved in the macro folder after since (the record command just stopped a recording)."""
    try:
        from . import optionsextras4
        return optionsextras4._newest_macro(since - 1) is not None
    except Exception as _fw_err:
        _fw_log("toolsextras.py:wrote macro", _fw_err)
        return False


# --------------------------------------------------------------------- Save/Restore Settings
BASE = "User parameter:BaseApp"

CATEGORIES = ("System Options", "Toolbar layout", "Keyboard shortcuts", "Mouse gestures", "Menu customization")

_FW = ("Preferences", "Mod", "FreeWorks")


def _category(path, name):
    """The wizard row a parameter belongs to (path: group names under BaseApp, name: the entry)."""
    p = tuple(path)
    low = (name or "").lower()
    if p[:2] == ("Preferences", "Shortcut"):
        return "Keyboard shortcuts"
    if p[:3] == ("Preferences", "Mod", "SolidWorksStyle"):
        # Tools > Customize keeps every tab's choices in one group: sort them by the tab they come from
        if name.startswith(("Key.", "KeyOrig", "SearchKey.")):
            return "Keyboard shortcuts"
        if name.startswith(("Gesture.", "GestureCount")):
            return "Mouse gestures"
        if name.startswith("Menu.") or name == "CustomizeMenuItems":
            return "Menu customization"
        return "Toolbar layout"
    if p[:1] == ("Workbench",) or p[:2] == ("Preferences", "MainWindow"):
        return "Toolbar layout"
    if p[:3] == _FW or p[:3] == ("Preferences", "Mod", "SWStyle"):
        if low.startswith("mousegesture"):
            return "Mouse gestures"
        if "menu" in low:
            return "Menu customization"
        if any(k in low for k in ("toolbar", "commandmanager", "ribbon", "qat", "shortcutbar", "tab")):
            return "Toolbar layout"
    if p[:1] == ("Preferences",):
        return "System Options"
    return None


def _prune(root, keep):
    """Drops the entries (and emptied groups) whose row is not in keep."""
    def walk(group, path):
        for child in list(group):
            if child.tag == "FCParamGroup":
                walk(child, path + [child.get("Name")])
                if len(child) == 0 and _category(path + [child.get("Name")], "") not in keep:
                    group.remove(child)
            elif _category(path, child.get("Name")) not in keep:
                group.remove(child)
    for top in root.iter("FCParamGroup"):
        if top.get("Name") == "Root":
            walk(top, [])
            break


def save_settings(path, keep=CATEGORIES):
    import tempfile
    import xml.etree.ElementTree as ET
    tmp = os.path.join(tempfile.mkdtemp(prefix="freeworks-settings-"), "all.FCParam")
    App.ParamGet(BASE).Export(tmp)
    tree = ET.parse(tmp)
    _prune(tree.getroot(), set(keep))
    tree.write(path, encoding="UTF-8", xml_declaration=True)


def restore_settings(path, keep=CATEGORIES):
    import xml.etree.ElementTree as ET
    tree = ET.parse(path)
    root = tree.getroot()
    if not any(g.get("Name") == "Root" for g in root.iter("FCParamGroup")):
        App.ParamGet(PREFS).Import(path)       # a file saved by the older box (Preferences only)
        return
    _prune(root, set(keep))
    _drop_missing(root, set(keep))
    _apply(root)


def _entries(root):
    """{(group path, tag, name)} of a parameter tree's entries."""
    out = set()

    def walk(group, path):
        for child in group:
            if child.tag == "FCParamGroup":
                walk(child, path + (child.get("Name"),))
            else:
                out.add((path, child.tag, child.get("Name")))
    for top in root.iter("FCParamGroup"):
        if top.get("Name") == "Root":
            walk(top, ())
            break
    return out


def _drop_missing(root, keep):
    """Restore puts the kept rows back as they were saved: an entry set since then that the file
    does not have (a setting changed away from its default) goes, so the default comes back."""
    import tempfile
    import xml.etree.ElementTree as ET
    tmp = os.path.join(tempfile.mkdtemp(prefix="freeworks-settings-"), "now.FCParam")
    App.ParamGet(BASE).Export(tmp)
    now = ET.parse(tmp).getroot()
    _prune(now, keep)
    _remove(_entries(now) - _entries(root))


def _apply(root):
    """Each kept entry set one by one (a whole-file Import also drops what the file leaves out)."""
    def walk(group, path):
        grp = App.ParamGet("/".join([BASE] + path)) if path else App.ParamGet(BASE)
        for child in group:
            name, value = child.get("Name"), child.get("Value")
            if child.tag == "FCParamGroup":
                walk(child, path + [name])
            elif child.tag == "FCBool":
                grp.SetBool(name, value == "1")
            elif child.tag == "FCInt":
                grp.SetInt(name, int(value))
            elif child.tag == "FCUInt":
                grp.SetUnsigned(name, int(value))
            elif child.tag == "FCFloat":
                grp.SetFloat(name, float(value))
            elif child.tag == "FCText":
                grp.SetString(name, child.text or "")
    for top in root.iter("FCParamGroup"):
        if top.get("Name") == "Root":
            walk(top, [])
            break


def _remove(entries):
    rem = {"FCBool": "RemBool", "FCInt": "RemInt", "FCUInt": "RemUnsigned", "FCFloat": "RemFloat", "FCText": "RemString"}
    for path, tag, name in entries:
        if tag in rem and path:
            try:
                getattr(App.ParamGet("/".join((BASE,) + path)), rem[tag])(name)
            except Exception as _fw_err:
                _fw_log("toolsextras.py:657", _fw_err)


def reset_settings(keep=CATEGORIES, backup=None):
    ""

    import tempfile
    import xml.etree.ElementTree as ET
    if backup:
        save_settings(backup, keep)
    tmp = os.path.join(tempfile.mkdtemp(prefix="freeworks-settings-"), "now.FCParam")
    App.ParamGet(BASE).Export(tmp)
    now = ET.parse(tmp).getroot()
    _prune(now, set(keep))
    _remove(_entries(now))


SETTINGS_FILTER = "Settings (*.FCParam)"


class SettingsDialog(QtWidgets.QDialog):
    ""



    def __init__(self):
        super().__init__(_mw())
        self.setWindowTitle("Copy Settings Wizard")
        self.setObjectName("SWSaveRestoreSettings")
        self.resize(520, 380)
        lay = QtWidgets.QVBoxLayout(self)
        self.pages = QtWidgets.QStackedWidget(self)
        lay.addWidget(self.pages, 1)
        # ---- page 1: what to do
        first = QtWidgets.QWidget()
        fl = QtWidgets.QVBoxLayout(first)
        head = QtWidgets.QLabel("Copy your settings to a file, read them back from one, or set them back to "
                                "their defaults.", first)
        head.setWordWrap(True)
        fl.addWidget(head)
        self.save = QtWidgets.QRadioButton("Save Settings", first)
        self.save.setObjectName("SWSettingsSave")
        self.restore = QtWidgets.QRadioButton("Restore Settings", first)
        self.restore.setObjectName("SWSettingsRestore")
        self.reset = QtWidgets.QRadioButton("Reset Settings", first)
        self.reset.setObjectName("SWSettingsReset")
        self.save.setChecked(True)
        for radio, text in ((self.save, "Writes the chosen settings to a file you can take to another computer."),
                            (self.restore, "Reads settings back from a file saved here."),
                            (self.reset, "Sets the chosen settings back to how they were when the interface was installed.")):
            fl.addWidget(radio)
            note = QtWidgets.QLabel(text, first)
            note.setWordWrap(True)
            note.setContentsMargins(22, 0, 0, 6)
            fl.addWidget(note)
        fl.addStretch(1)
        self.pages.addWidget(first)
        # ---- page 2: the file and the settings
        second = QtWidgets.QWidget()
        sl = QtWidgets.QVBoxLayout(second)
        self.file_label = QtWidgets.QLabel("", second)
        sl.addWidget(self.file_label)
        row = QtWidgets.QHBoxLayout()
        self.backup = QtWidgets.QCheckBox("Back up current settings", second)
        self.backup.setObjectName("SWSettingsBackup")
        self.backup.setChecked(True)
        self.backup.toggled.connect(lambda on: self._path_row(self.mode() != "reset" or on))
        sl.addWidget(self.backup)
        self.path = QtWidgets.QLineEdit(os.path.join(os.path.expanduser("~"), "FreeCAD settings.FCParam"), second)
        self.path.setObjectName("SWSettingsFile")
        browse = QtWidgets.QPushButton("Browse...", second)
        browse.setObjectName("SWSettingsBrowse")
        self.browse = browse
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        sl.addLayout(row)
        group = QtWidgets.QGroupBox("Settings", second)
        gl = QtWidgets.QVBoxLayout(group)
        self.rows = {}
        for name in CATEGORIES:
            c = QtWidgets.QCheckBox(name, group)
            c.setObjectName("SWSettings_" + name.replace(" ", ""))
            c.setChecked(True)
            gl.addWidget(c)
            self.rows[name] = c
        sl.addWidget(group)
        self.note = QtWidgets.QLabel("", second)
        self.note.setObjectName("SWSettingsNote")
        self.note.setWordWrap(True)
        sl.addWidget(self.note)
        sl.addStretch(1)
        self.pages.addWidget(second)
        # ---- buttons
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.back_button = QtWidgets.QPushButton("< Back", self)
        self.back_button.setObjectName("SWSettingsBack")
        self.next_button = QtWidgets.QPushButton("Next >", self)
        self.next_button.setObjectName("SWSettingsNext")
        self.finish_button = QtWidgets.QPushButton("Finish", self)
        self.finish_button.setObjectName("SWSettingsFinish")
        cancel = QtWidgets.QPushButton("Cancel", self)
        cancel.setObjectName("SWSettingsCancel")
        helpb = QtWidgets.QPushButton("Help", self)
        helpb.setObjectName("SWSettingsHelp")
        for b in (self.back_button, self.next_button, self.finish_button, cancel, helpb):
            b.setAutoDefault(False)
            buttons.addWidget(b)
        lay.addLayout(buttons)
        self.back_button.clicked.connect(lambda: self.go(0))
        self.next_button.clicked.connect(lambda: self.go(1))
        self.finish_button.clicked.connect(self.run)
        cancel.clicked.connect(self.reject)
        helpb.clicked.connect(self._help)
        self.go(0)

    def _path_row(self, on):
        """The file box and Browse show only while a file is wanted (extapps91: not greyed)."""
        self.path.setVisible(bool(on))
        self.browse.setVisible(bool(on))

    def mode(self):
        return "save" if self.save.isChecked() else "restore" if self.restore.isChecked() else "reset"

    def go(self, page):
        self.pages.setCurrentIndex(page)
        self.note.setText("")
        mode = self.mode()
        if page == 1:
            self.file_label.setText({"save": "Save settings to:", "restore": "Restore settings from:",
                                     "reset": "Back up current settings to:"}[mode])
            self.backup.setVisible(mode != "save")
            self.backup.setText("Back up current settings first" if mode == "restore" else "Back up current settings")
            self._path_row(mode != "reset" or self.backup.isChecked())
            if mode != "restore" and self.path.text().endswith("settings.FCParam") and mode == "reset":
                self.path.setText(os.path.join(os.path.expanduser("~"), "FreeCAD settings backup.FCParam"))
        self.back_button.setVisible(page == 1)          # extapps91: no greyed buttons: each shows on its own page
        self.next_button.setVisible(page == 0)
        self.finish_button.setVisible(page == 1)
        self.finish_button.setDefault(page == 1)
        self.next_button.setDefault(page == 0)

    def chosen(self):
        return [n for n, c in self.rows.items() if c.isChecked()]

    def _browse(self):
        if self.mode() == "restore":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Restore Settings", self.path.text(), SETTINGS_FILTER)
        else:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Settings", self.path.text(), SETTINGS_FILTER)
        if path:
            self.path.setText(path)

    def _help(self):
        QtWidgets.QMessageBox.information(
            self, "Copy Settings Wizard",
            "Save Settings writes the ticked kinds of settings to a .FCParam file. Restore Settings reads such a "
            "file back (on this or another computer). Reset Settings puts the ticked kinds back to their "
            "defaults; tick Back up current settings to keep a file of them first.")

    def _backup_path(self, path):
        stem, ext = os.path.splitext(path)
        return stem + " (backup)" + (ext or ".FCParam")

    def run(self):
        mode = self.mode()
        path = self.path.text().strip()
        if mode != "reset" and not path:
            self.note.setText("Give a file.")
            return
        if not self.chosen():
            self.note.setText("Pick at least one kind of setting.")
            return
        try:
            if mode == "save":
                save_settings(path, self.chosen())
            elif mode == "restore":
                if not os.path.exists(path):
                    self.note.setText("There is no such file.")
                    return
                if self.backup.isChecked():
                    save_settings(self._backup_path(path), self.chosen())
                restore_settings(path, self.chosen())
                QtWidgets.QMessageBox.information(self, "Copy Settings Wizard",
                                                  "The settings are restored. Restart FreeCAD to see all of them.")
            else:
                if QtWidgets.QMessageBox.question(
                        self, "Copy Settings Wizard", "Set the ticked settings back to their defaults?",
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
                    return
                reset_settings(self.chosen(), path if self.backup.isChecked() and path else None)
                QtWidgets.QMessageBox.information(self, "Copy Settings Wizard",
                                                  "The settings are reset. Restart FreeCAD to see all of them.")
        except Exception as error:
            self.note.setText(str(error))
            return
        self.accept()


class SaveRestoreSettings:
    def GetResources(self):
        return {"MenuText": "Save/Restore Settings...",
                "ToolTip": "Saves the settings to a file, or reads them back from one."}

    def IsActive(self):
        return True

    def Activated(self):
        SettingsDialog().exec_()


# --------------------------------------------------------------------- Find and Replace Annotation
TEXT_PROPS = ("Text", "LabelText", "FormatSpec", "EditableTexts")


def annotation_texts(doc):
    """[(object, property, index or None, text)] for the text of the document's notes, labels,
    balloons and dimension formats."""
    out = []
    for obj in doc.Objects:
        for prop in TEXT_PROPS:
            if prop not in obj.PropertiesList:
                continue
            value = getattr(obj, prop)
            if isinstance(value, str):
                out.append((obj, prop, None, value))
            elif isinstance(value, (list, tuple)):
                out.extend((obj, prop, i, v) for i, v in enumerate(value) if isinstance(v, str))
            elif isinstance(value, dict):
                out.extend((obj, prop, k, v) for k, v in value.items() if isinstance(v, str))
    return out


def _matches(text, find, case, whole):
    import re
    flags = 0 if case else re.IGNORECASE
    pattern = r"\b%s\b" % re.escape(find) if whole else re.escape(find)
    return re.compile(pattern, flags)


def find_annotations(doc, find, case=False, whole=False):
    rx = _matches("", find, case, whole)
    return [hit for hit in annotation_texts(doc) if find and rx.search(hit[3])]


def replace_annotations(doc, find, repl, hits=None, case=False, whole=False):
    rx = _matches("", find, case, whole)
    hits = find_annotations(doc, find, case, whole) if hits is None else hits
    doc.openTransaction("Find and Replace Annotation")
    try:
        for obj, prop, key, text in hits:
            new = rx.sub(lambda _m: repl, text)
            value = getattr(obj, prop)
            if key is None:
                setattr(obj, prop, new)
            elif isinstance(value, dict):
                value = dict(value)
                value[key] = new
                setattr(obj, prop, value)
            else:
                value = list(value)
                value[key] = new
                setattr(obj, prop, value)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return len(hits)


class FindReplaceDialog(QtWidgets.QDialog):
    def __init__(self, doc):
        super().__init__(_mw())
        self.doc = doc
        self.setWindowTitle("Find and Replace Annotation")
        self.setObjectName("SWFindReplaceAnnotation")
        self.resize(480, 360)
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.find = QtWidgets.QLineEdit()
        self.repl = QtWidgets.QLineEdit()
        form.addRow("Find what:", self.find)
        form.addRow("Replace with:", self.repl)
        lay.addLayout(form)
        self.case = QtWidgets.QCheckBox("Match case")
        self.whole = QtWidgets.QCheckBox("Match whole word")
        lay.addWidget(self.case)
        lay.addWidget(self.whole)
        self.list = QtWidgets.QListWidget()
        lay.addWidget(self.list, 1)
        self.note = QtWidgets.QLabel("")
        lay.addWidget(self.note)
        row = QtWidgets.QHBoxLayout()
        for text, slot in (("Find Next", self.find_next), ("Replace", self.replace_one),
                           ("Replace All", self.replace_all), ("Close", self.close)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.find.textChanged.connect(lambda _t: self.search())
        self.case.toggled.connect(lambda _t: self.search())
        self.whole.toggled.connect(lambda _t: self.search())
        self.hits = []

    def search(self):
        self.hits = find_annotations(self.doc, self.find.text(), self.case.isChecked(), self.whole.isChecked())
        self.list.clear()
        for obj, prop, key, text in self.hits:
            self.list.addItem("%s: %s" % (obj.Label, text))
        self.note.setText("%d found" % len(self.hits) if self.find.text() else "")
        return self.hits

    def find_next(self):
        if not self.hits:
            self.search()
        if not self.hits:
            return
        row = (self.list.currentRow() + 1) % len(self.hits)
        self.list.setCurrentRow(row)
        obj = self.hits[row][0]
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj.Name)

    def replace_one(self):
        row = self.list.currentRow()
        if row < 0:
            self.find_next()
            row = self.list.currentRow()
        if 0 <= row < len(self.hits):
            replace_annotations(self.doc, self.find.text(), self.repl.text(), [self.hits[row]],
                                self.case.isChecked(), self.whole.isChecked())
        self.search()

    def replace_all(self):
        n = replace_annotations(self.doc, self.find.text(), self.repl.text(), None,
                                self.case.isChecked(), self.whole.isChecked())
        self.search()
        self.note.setText("%d replaced" % n)


class FindReplaceAnnotation:
    def GetResources(self):
        return {"MenuText": "Find and Replace Annotation...",
                "ToolTip": "Finds text in the notes and dimensions and replaces it."}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        try:        # the same window as the assembly's (simplify.py)
            from . import simplify
            simplify.open_find_replace(App.ActiveDocument)
        except Exception:
            FindReplaceDialog(App.ActiveDocument).show()


# --------------------------------------------------------------------- Area Hatch/Fill (sketch)
class SketchAreaHatch:
    def GetResources(self):
        return {"MenuText": "Area Hatch/Fill", "Pixmap": "TechDraw_TreeHatch",
                "ToolTip": "Fills the closed regions of the sketch.", "CmdType": "ForEdit"}

    def _sketch(self):
        try:
            from . import contextbar
            sketch = contextbar.sketch_in_edit()
        except Exception:
            sketch = None
        if sketch is None:
            picked = [s.Object for s in Gui.Selection.getSelectionEx() if s.Object.isDerivedFrom("Sketcher::SketchObject")]
            sketch = picked[0] if picked else None
        return sketch

    def IsActive(self):
        return self._sketch() is not None

    def Activated(self):
        sketch = self._sketch()
        if sketch is None:
            return
        from . import rcextras
        try:
            rcextras.area_hatch(sketch)
        except Exception as error:
            _mw().statusBar().showMessage("Area Hatch/Fill: %s" % error, 6000)


# --------------------------------------------------------------------- Add-Ins
WB_PREFS = "User parameter:BaseApp/Preferences/Workbenches"
GENERAL = "User parameter:BaseApp/Preferences/General"


def _csv(group, key):
    return [n for n in App.ParamGet(group).GetString(key, "").split(",") if n]


def addins():
    """[(name, title, active, start up)] for the installed workbenches."""
    disabled = set(_csv(WB_PREFS, "Disabled"))
    startup = set(_csv(GENERAL, "BackgroundAutoloadModules"))
    out = []
    for name, wb in sorted(Gui.listWorkbenches().items(), key=lambda kv: getattr(kv[1], "MenuText", kv[0]).lower()):
        if name == "NoneWorkbench":
            continue
        out.append((name, getattr(wb, "MenuText", name), name not in disabled, name in startup))
    return out


def set_addins(rows):
    """rows: [(name, active, start up)]."""
    disabled = [n for n, active, _s in rows if not active]
    startup = [n for n, active, s in rows if s and active]
    keep = [n for n in _csv(WB_PREFS, "Disabled") if n not in {r[0] for r in rows}]
    App.ParamGet(WB_PREFS).SetString("Disabled", ",".join(keep + disabled))
    App.ParamGet(GENERAL).SetString("BackgroundAutoloadModules", ",".join(startup))


class AddInsDialog(QtWidgets.QDialog):
    ""

    def __init__(self):
        super().__init__(_mw())
        self.setWindowTitle("Add-Ins")
        self.setObjectName("SWAddIns")
        self.resize(460, 520)
        lay = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTreeWidget()
        self.table.setObjectName("SWAddInsTable")
        self.table.setHeaderLabels(["Active Add-ins", "Start Up"])
        self.table.setRootIsDecorated(False)
        self.rows = addins()
        for name, title, active, start in self.rows:
            item = QtWidgets.QTreeWidgetItem([title, ""])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(0, QtCore.Qt.Checked if active else QtCore.Qt.Unchecked)
            item.setCheckState(1, QtCore.Qt.Checked if start else QtCore.Qt.Unchecked)
            item.setData(0, QtCore.Qt.UserRole, name)
            self.table.addTopLevelItem(item)
        self.table.resizeColumnToContents(0)
        lay.addWidget(self.table, 1)
        lay.addWidget(QtWidgets.QLabel("Changes to Active and Start Up apply when FreeCAD starts next."))
        row = QtWidgets.QHBoxLayout()
        store = QtWidgets.QPushButton("Addon Manager...")
        store.clicked.connect(self._store)
        row.addWidget(store)
        row.addStretch(1)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        row.addWidget(box)
        lay.addLayout(row)

    def chosen(self):
        out = []
        for i in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(i)
            out.append((item.data(0, QtCore.Qt.UserRole), item.checkState(0) == QtCore.Qt.Checked,
                        item.checkState(1) == QtCore.Qt.Checked))
        return out

    def accept(self):
        set_addins(self.chosen())
        super().accept()

    def _store(self):
        try:
            Gui.Command.get("Std_AddonMgr").run()
        except Exception:
            try:
                import AddonManager
                AddonManager.CommandAddonManager().Activated()
            except Exception as error:
                QtWidgets.QMessageBox.information(self, "Add-Ins", "The Addon Manager is not installed (%s)." % error)


class AddIns:
    def GetResources(self):
        return {"MenuText": "Add-Ins...", "Pixmap": "AddonManager", "CmdType": "ForEdit",
                "ToolTip": "Turns add-ins on and off, now and at start up."}

    def IsActive(self):
        return True

    def Activated(self):

        # box stays only as the fallback
        try:
            from . import addins
            addins.show()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Add-Ins box: %s\n" % error)
            AddInsDialog().exec_()


COMMANDS = {"SWStyle_AutomaticSolve": AutomaticSolve, "SWStyle_SketchAreaHatch": SketchAreaHatch,
            "SWStyle_AddIns": AddIns, "SWStyle_FindReplaceAnnotation": FindReplaceAnnotation, "SWStyle_Simplify": Simplify,
            "SWStyle_FormatPainter": FormatPainter, "SWStyle_MacroNew": MacroNew,
            "SWStyle_MacroEdit": MacroEdit, "SWStyle_MacroStop": MacroStop, "SWStyle_MacroRun": MacroRun,
            "SWStyle_SaveRestoreSettings": SaveRestoreSettings}


def register():
    try:
        from . import dialogsgrey       # extapps91: no greyed buttons in the File and Tools boxes
        dialogsgrey.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: dialogsgrey: %s\n" % error)
    for name, cls in COMMANDS.items():
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, cls())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (name, error))
    _register_states()


def _register_states():
    ""

    from . import checkstate
    checkstate.register("SWStyle_AutomaticSolve", automatic_solve)
    try:
        from . import viewsettings as VS
        for name, fn in ((VS.REALVIEW, VS.realview_on), (VS.AMBIENT, VS.ambient_on), (VS.SHADOW, VS.shadows_on),
                         (VS.PERSPECTIVE, VS.perspective_on)):
            checkstate.register(name, fn)
    except Exception as error:
        App.Console.PrintLog("FreeCAD view setting states: %s\n" % error)
    try:
        from . import pentools as PT
        for name, (_text, key, _default, _tip) in PT.SETTINGS.items():
            checkstate.register(name, lambda key=key: PT.setting(key))
    except Exception as error:
        App.Console.PrintLog("FreeCAD pen setting states: %s\n" % error)
