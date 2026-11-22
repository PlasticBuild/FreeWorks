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
from PySide import QtCore, QtWidgets

from . import asmcore as ac


def _cm():
    from . import configmanager
    return configmanager


def part_doc(comp):
    from . import asmmenu
    try:
        return asmmenu.part_document(comp)
    except Exception:
        return None


def publishing(comp):
    """(part document, table, [(alias, control)]) when comp's part publishes parameters, else None."""
    cm = _cm()
    if not hasattr(cm, "published"):
        return None
    doc = part_doc(comp)
    if doc is None:
        return None
    try:
        items = cm.published(doc)
        t = cm.table(doc)
    except Exception:
        return None
    if not items or t is None:
        return None
    return doc, t, items


class ConfigPublisherPanel:
    """The component's published parameters, each as its List or Number control; the
    configuration they pick is shown under them."""

    def __init__(self, asm, comp):
        from . import asmpm as pm
        cm = _cm()
        self.asm, self.comp = asm, comp
        self.doc, self.t, items = publishing(comp)
        self.start = self.t.active()
        values = {a: v for _c, a, v in cm.parameters(self.t)}
        box, lay = pm._box("Configuration Publisher", "Configuration Publisher")
        lay.addWidget(QtWidgets.QLabel(comp.Label))
        form = QtWidgets.QFormLayout()
        self.inputs, self.reads = {}, {}
        for alias, kind in items:
            vals = values.get(alias, {})
            label, w, read = cm.publisher_control(self.doc, self.t, alias, kind, vals, vals.get(self.start), self.changed)
            w.setObjectName("FW_Publisher_%s" % alias)
            self.inputs[alias], self.reads[alias] = w, read
            form.addRow(label + ":", w)
        lay.addLayout(form)
        self.result = QtWidgets.QLabel("Configuration: %s" % self.start)
        self.result.setObjectName("FW_PublisherConfiguration")
        lay.addWidget(self.result)
        self.form = [box]

    def wanted(self):
        return {a: read() for a, read in self.reads.items()}

    def changed(self):
        cm = _cm()
        name = cm.pick_configuration(self.t, self.wanted())
        if name and name != self.t.active():
            cm.show(self.t, name)
            self.doc.recompute()
            self.asm.Document.recompute()
        self.result.setText("Configuration: %s" % self.t.active())
        return name

    def accept(self):
        Gui.Control.closeDialog()
        return True

    def reject(self):
        if self.t.active() != self.start:
            _cm().show(self.t, self.start)
            self.doc.recompute()
            self.asm.Document.recompute()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _order(text):
    try:
        return (0, float(text), "")
    except ValueError:
        return (1, 0.0, text)


OPEN = []


def show_for(comp):
    """Opens the Configuration Publisher panel for comp; None when its part publishes nothing
    or another PropertyManager is busy."""
    from . import asmpm as pm
    asm = ac.assembly_of(comp.Document)
    if asm is None or publishing(comp) is None:
        return None
    if Gui.Control.activeDialog():
        if isinstance(pm.OPEN, ConfigPublisherPanel) and pm.OPEN.comp is comp:
            return pm.OPEN
        if not isinstance(pm.OPEN, ConfigPublisherPanel) or not pm.close_open():
            return None
    panel = ConfigPublisherPanel(asm, comp)
    pm._track(panel)
    Gui.Control.showDialog(panel)
    OPEN[:] = [panel]
    return panel


def _after_insert(panel, tries=40):
    """The Insert Component PM placed components: once it closes, the last published one gets its panel."""
    if Gui.Control.activeDialog():
        if tries > 0 and getattr(panel, "_fw_published", None):
            QtCore.QTimer.singleShot(100, lambda: _after_insert(panel, tries - 1))
        return
    comp = getattr(panel, "_fw_published", None)
    panel._fw_published = None
    try:
        if comp is not None and comp.Document.getObject(comp.Name) is comp:
            show_for(comp)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Configuration Publisher: %s\n" % error)


class _Watch:
    """A component picked in an assembly, with no PropertyManager open: its Configuration Publisher."""

    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, lambda: _picked(doc))


def _picked(docname):
    try:
        if Gui.Control.activeDialog() and not isinstance(_pm_open(), ConfigPublisherPanel):
            return
        sel = Gui.Selection.getSelectionEx(docname)
        doc = App.getDocument(docname)
        asm = ac.assembly_of(doc)
        if asm is None or len(sel) != 1:
            return
        names = {c.Name for c in ac.components(asm)}
        s = sel[0]
        name = s.ObjectName if s.ObjectName in names else None
        for sub in s.SubElementNames or ():
            head = sub.split(".")[0]
            if head in names:
                name = head
        if name is not None:
            show_for(doc.getObject(name))
    except Exception as _fw_err:
        _fw_log("asmpublisher.py:206", _fw_err)


def _pm_open():
    from . import asmpm
    return asmpm.OPEN


def install():
    from . import asmpm
    cls = asmpm.InsertComponentPanel
    if getattr(cls, "_fw_publisher", False):
        return
    def wrap(method):
        def wrapped(self, *a, **k):
            before = {c.Name for c in ac.components(self.asm)}
            n = len(getattr(self, "placed", []) or [])
            out = method(self, *a, **k)
            try:
                new = list((getattr(self, "placed", []) or [])[n:])
                new += [c for c in ac.components(self.asm) if c.Name not in before and c not in new]
            except Exception:
                new = []
            new = [c for c in new if publishing(c) is not None]
            if new:
                self._fw_published = new[-1]
                QtCore.QTimer.singleShot(50, lambda: _after_insert(self))
            return out
        wrapped.__name__ = method.__name__
        return wrapped

    cls.place = wrap(cls.place)
    cls.accept = wrap(cls.accept)
    cls._fw_publisher = True
    if not getattr(Gui, "_fw_publisher_watch", None):
        Gui._fw_publisher_watch = _Watch()
        Gui.Selection.addObserver(Gui._fw_publisher_watch)
