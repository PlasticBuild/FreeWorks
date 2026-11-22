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
from PySide import QtWidgets

from . import asmcore as ac

_installed = []
PICKING = []


def _plane_ref(obj, sub):
    """(support object, sub) when obj/sub is a plane or a flat face, else None."""
    if obj is None:
        return None
    leaf = sub.split(".")[-1] if sub else ""
    if not leaf:
        if obj.TypeId in ("App::Plane", "PartDesign::Plane") or obj.isDerivedFrom("App::Plane"):
            return obj, ""
        return None
    if not leaf.startswith("Face"):
        return None
    try:
        face = obj.getSubObject(sub)
        if face is None or face.Surface.TypeId != "Part::GeomPlane":
            return None
    except Exception:
        return None
    return obj, sub


def _resolve(obj, sub):
    """A pick as a sketch support: a flat face by its path, a plane (tree row or a path ending in
    the plane) by itself."""
    ref = _plane_ref(obj, sub)
    if ref is None and sub and not sub.split(".")[-1]:
        try:
            ref = _plane_ref(obj.getSubObject(sub, retType=1), "")
        except Exception:
            ref = None
    return ref


def make(asm, obj, sub):
    """A sketch in the assembly on obj/sub, opened for editing."""
    doc = asm.Document
    if sub and "." in sub and obj is asm:
        # a component's face picked through the assembly: support the component itself, as the
        # sketch lives in the assembly too (supporting the assembly would make a cycle)
        head, rest = sub.split(".", 1)
        child = doc.getObject(head)
        if child is not None and child in asm.Group:
            obj, sub = child, rest
    doc.openTransaction("Sketch")
    try:
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
        try:
            asm.addObject(sk)
        except Exception as _fw_err:
            _fw_log("asmsketch.py:75", _fw_err)
        try:
            sk.AttachmentSupport = [(obj, sub)]
        except Exception:
            sk.Support = [(obj, sub)]
        sk.MapMode = "FlatFace"
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    Gui.ActiveDocument.setEdit(sk.Name)
    return sk


def _planes(asm):
    out = []
    try:
        org = asm.Origin
        out = [o for o in org.OriginFeatures if o.TypeId == "App::Plane"]
    except Exception:
        for o in asm.Document.Objects:
            if o.TypeId == "App::Plane" and o in asm.OutListRecursive:
                out.append(o)
    return out


class _Pick:
    ""

    def __init__(self, asm):
        self.asm = asm
        self.shown = []
        for p in _planes(asm):
            try:
                if not p.ViewObject.Visibility:
                    p.ViewObject.Visibility = True
                    self.shown.append(p)
            except Exception as _fw_err:
                _fw_log("asmsketch.py:112", _fw_err)
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("FW_AsmSketchPick")
        self.form.setWindowTitle("Edit Sketch")
        lay = QtWidgets.QVBoxLayout(self.form)
        lab = QtWidgets.QLabel("Select a plane on which to create a sketch for the entity.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        Gui.Selection.addObserver(self)
        PICKING.append(self)

    def addSelection(self, doc, obj, sub, pnt):
        if self not in PICKING:
            return
        if not Gui.Control.activeDialog():
            self._end()         # the page was closed without Cancel (another command): stop waiting
            return
        ref = _resolve(App.getDocument(doc).getObject(obj), sub or "")
        if ref is None:
            return
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda: self._go(ref))

    def _go(self, ref):
        self._end()
        Gui.Control.closeDialog()
        make(self.asm, ref[0], ref[1])

    def _end(self):
        if self in PICKING:
            PICKING.remove(self)
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmsketch.py:143", _fw_err)
        for p in self.shown:
            try:
                p.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("asmsketch.py:148", _fw_err)
        self.shown = []

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Cancel

    def reject(self):
        self._end()
        Gui.Control.closeDialog()
        return True


def run(native):
    """True when the Sketch command was taken here (an assembly, no part edited in context)."""
    from . import sketchstart
    if native != sketchstart.NATIVE or App.ActiveDocument is None:
        return False
    asm = ac.assembly_of(App.ActiveDocument)
    if asm is None:
        return False
    try:
        from . import asmtools
        if asmtools.editing():
            return False        # a part edited in context: its own sketch, as before
    except Exception as _fw_err:
        _fw_log("asmsketch.py:173", _fw_err)
    gdoc = Gui.ActiveDocument
    if Gui.Control.activeDialog() or _editing_other(gdoc, asm):
        return False
    picks = [(s.Object, sub) for s in Gui.Selection.getSelectionEx("", 0) for sub in (s.SubElementNames or [""])]
    if len(picks) == 1:
        ref = _resolve(*picks[0])
        if ref is not None:
            make(asm, *ref)
            return True
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(_Pick(asm))
    return True


def _editing_other(gdoc, asm):
    """Something in edit other than the active assembly itself (FreeCAD keeps an active assembly in
    edit mode)."""
    if gdoc is None:
        return False
    vp = gdoc.getInEdit()
    if vp is None:
        return False
    return getattr(vp, "Object", None) is not asm and "Assembly" not in type(vp).__name__


def install():
    from . import sketchstart
    if _installed:
        return
    orig = sketchstart.run

    def run_wrapped(native):
        try:
            if run(native):
                return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: assembly sketch: %s\n" % error)
        return orig(native)
    run_wrapped.__wrapped__ = orig
    sketchstart.run = run_wrapped
    _installed.append(orig)
