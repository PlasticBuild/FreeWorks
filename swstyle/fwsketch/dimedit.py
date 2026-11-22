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

import FreeCADGui as Gui

try:
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtWidgets

STEP = "Modify sketch constraints"


def edited_sketch():
    gdoc = Gui.ActiveDocument
    vp = gdoc.getInEdit() if gdoc else None
    if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
        return None, None
    return gdoc, vp.Object


def _subs(sketch):
    """Sub-elements of the sketch under the pointer; else, when the first click of the
    double-click picked exactly one item, that one."""
    try:
        from .toolbase import preselected_subs
        subs = preselected_subs(sketch)
        if subs:
            return subs
        picked = [sub for s in Gui.Selection.getSelectionEx(sketch.Document.Name)
                  if s.ObjectName == sketch.Name for sub in s.SubElementNames]
        return picked if len(picked) == 1 else []
    except Exception:
        return []


def preselected_dimension(sketch):
    """Index of the dimension under the pointer (or just picked by the first click), or None."""
    from .modifybox import DIMENSIONAL
    subs = _subs(sketch)
    sub = subs[0] if subs else ""
    if not sub.startswith("Constraint"):
        return None
    try:
        index = int(sub[len("Constraint"):]) - 1
        return index if sketch.Constraints[index].Type in DIMENSIONAL else None
    except Exception:
        return None


def edit(sketch, index):
    """The Modify box for dimension index, as one undo step; True when the value was kept."""
    from . import modifybox, trace
    try:
        from .. import dimensionpm
        if dimensionpm.read_only(sketch, index):
            modifybox.status("The dimension is read only (Dimension PropertyManager > Other > Read only).")
            return False
    except Exception as _fw_err:
        _fw_log("fwsketch/dimedit.py:78", _fw_err)
    try:
        if not sketch.Constraints[index].Driving:

            modifybox.status("A driven dimension cannot be changed: make it driving to edit it.")
            return False
    except Exception as _fw_err:
        _fw_log("fwsketch/dimedit.py:85", _fw_err)
    trace.note("dimedit open %s %d" % (sketch.Name, index))
    doc = sketch.Document
    doc.openTransaction(STEP)
    try:
        box = modifybox.ModifyBox(sketch, index)
        box.own_transaction = True     # opened just above for the box alone
        ok = box.run()
        try:
            sketch.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/dimedit.py:94", _fw_err)
        return ok
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


class DimensionEditWatcher(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.swallow_release = False
        self.opened = []                 # (sketch name, index) per box, for tests
        self._app = QtWidgets.QApplication.instance()
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonRelease))   # one application filter (fix65)

    def stop(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/dimedit.py:112", _fw_err)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        try:
            return self._filter(obj, event)
        except Exception:
            import traceback
            import FreeCAD as App
            App.Console.PrintError("FreeCAD Modify box: %s" % traceback.format_exc())
            return False

    def _filter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # a stale wrapper (a QWidgetItem) when a page re-lays its rows
        t = event.type()
        if t == QtCore.QEvent.MouseButtonRelease and self.swallow_release:
            if event.button() == QtCore.Qt.LeftButton:
                self.swallow_release = False
                return True
            return False
        if t != QtCore.QEvent.MouseButtonDblClick or event.button() != QtCore.Qt.LeftButton:
            return False
        from . import tool
        if tool.active() is not None:
            return False
        gdoc, sketch = edited_sketch()
        if sketch is None:
            return False
        try:
            if obj is not gdoc.ActiveView.graphicsView().viewport():
                return False
        except (AttributeError, RuntimeError):
            return False
        index = preselected_dimension(sketch)
        if index is None:
            return False
        self.swallow_release = True
        self.opened.append((sketch.Name, index))
        QtCore.QTimer.singleShot(0, lambda: edit(sketch, index))
        return True


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = DimensionEditWatcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None


def watcher():
    return _watcher
