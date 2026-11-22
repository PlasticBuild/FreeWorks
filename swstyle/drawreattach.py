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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import drawings as D

COMMAND = "FreeWorks_DrawDanglingAnnotations"
DRAG_PX = 6


def _bad_index(dim):
    """The index (in References2D order, flattened) of the first lost reference, else 0."""
    from . import drawmaint as DMT
    n = 0
    for view, subs in list(getattr(dim, "References2D", []) or []):
        for sub in (subs if isinstance(subs, (list, tuple)) else (subs,)):
            if view is None or not sub or not DMT._ref_ok(dim, view, sub):
                return n
            n += 1
    return 0


def fits(dim, view, sub):
    """True when the view's edge sub suits the dimension: a circle for a radius or diameter, a straight edge for a
    length."""
    try:
        e = view.getEdgeByIndex(int(sub[4:])) if sub.startswith("Edge") else None
    except Exception:
        e = None
    if sub.startswith("Vertex"):
        return dim.Type not in ("Radius", "Diameter")
    if e is None:
        return False
    circle = type(e.Curve).__name__ == "Circle"
    if dim.Type in ("Radius", "Diameter"):
        return circle
    return not circle or len(list(dim.References2D or [])) > 1


def reattach_to(dim, view, sub):
    """Puts the dimension's lost reference (the first one, when none is lost) on the view's edge or point sub;
    its colour comes back and it is no longer dangling. True when done."""
    if dim is None or view is None or not sub or not fits(dim, view, sub):
        return False
    from . import drawmaint as DMT
    refs = []
    for v, subs in list(dim.References2D or []):
        for s in (subs if isinstance(subs, (list, tuple)) else (subs,)):
            refs.append((v, s))
    if not refs:
        return False
    k = _bad_index(dim)
    refs[k] = (view, sub)
    doc = dim.Document
    doc.openTransaction("Reattach")
    try:
        dim.References2D = refs
        if "SWRefPrints" in dim.PropertiesList:
            dim.SWRefPrints = []                    # remembered again on what it is on now
        DMT._paint(dim, False)
        DMT._hide(dim, False)
        dim.recompute()
    finally:
        doc.commitTransaction()
    try:
        DMT.keep_references(dim)
    except Exception as _fw_err:
        _fw_log("drawreattach.py:88", _fw_err)
    return True


# --------------------------------------------------------------------------- drag onto an edge
class _Drag:
    dim = None          # (document name, dimension name, X, Y, press point)

    @staticmethod
    def handle(obj, event):
        try:
            t = event.type()
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                return False
            if event.button() != QtCore.Qt.LeftButton:
                return False
            view = obj.parentWidget() if isinstance(obj, QtWidgets.QWidget) else None
            if view is None or "QGVPage" not in view.metaObject().className():
                return False
            from . import drawmenu, drawmaint as DMT
            page = drawmenu._page()
            if page is None:
                return False
            pos = event.pos()
            if t == QtCore.QEvent.MouseButtonPress:
                _Drag.dim = None
                kind, o = drawmenu.under(view, pos, page)
                if kind == "dimension" and o is not None and ("SWDangleColor" in o.PropertiesList or DMT.is_dangling(o)):
                    _Drag.dim = (o.Document.Name, o.Name, float(o.X), float(o.Y), QtCore.QPoint(pos))
                return False
            got = _Drag.dim
            _Drag.dim = None
            if got is None or (pos - got[4]).manhattanLength() < DRAG_PX:
                return False
            target = None
            for kind, o, extra in drawmenu.hits(view, pos, page):
                if kind == "edge" and extra is not None:
                    target = (o, "Edge%d" % extra)
                    break
            if target is None:
                return False
            QtCore.QTimer.singleShot(0, lambda g=got, tg=target: _drop(g, tg))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: reattach drag: %s\n" % error)
        return False


def _drop(got, target):
    doc = App.listDocuments().get(got[0])
    dim = doc.getObject(got[1]) if doc is not None else None
    if dim is None:
        return
    if reattach_to(dim, target[0], target[1]):
        dim.X, dim.Y = got[2], got[3]           # the text stays where it was: only its end moved
        doc.recompute()
        _status("Dimension attached to %s." % target[1])
    else:
        _status("That edge does not suit this dimension.")


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 4000)
    except Exception as _fw_err:
        _fw_log("drawreattach.py:152", _fw_err)


# --------------------------------------------------------------------------- Dangling Annotations dialog
class DanglingDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.doc = doc
        self.setObjectName("SWDanglingAnnotations")
        self.setWindowTitle("Dangling Annotations")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Annotations whose model geometry is gone. Drag one onto an edge to "
                                       "attach it again.", self))
        self.list = QtWidgets.QTreeWidget(self)
        self.list.setObjectName("SWDanglingList")
        self.list.setHeaderLabels(["Annotation", "View", "Type"])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("Select", self.select), ("Reattach", self.reattach), ("Delete", self.delete),
                         ("Close", self.accept)):
            b = QtWidgets.QPushButton(text, self)
            b.setObjectName("SWDangling" + text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.fill()

    def fill(self):
        from . import drawmaint as DMT
        self.list.clear()
        for o in DMT.dangling(self.doc):
            refs = list(o.References2D or [])
            view = refs[0][0].Label if refs and refs[0][0] is not None else "-"
            it = QtWidgets.QTreeWidgetItem([o.Label, view, o.Type])
            it.setData(0, QtCore.Qt.UserRole, o.Name)
            self.list.addTopLevelItem(it)

    def picked(self):
        out = []
        for it in self.list.selectedItems():
            o = self.doc.getObject(it.data(0, QtCore.Qt.UserRole))
            if o is not None:
                out.append(o)
        return out

    def select(self):
        Gui.Selection.clearSelection()
        for o in self.picked():
            Gui.Selection.addSelection(self.doc.Name, o.Name)

    def reattach(self):
        self.select()
        _status("Drag the dimension onto the edge it goes on.")

    def delete(self):
        objs = self.picked()
        if not objs:
            return
        self.doc.openTransaction("Delete")
        try:
            for o in objs:
                self.doc.removeObject(o.Name)
        finally:
            self.doc.commitTransaction()
        self.doc.recompute()
        self.fill()


def show_dangling(doc=None):
    page = D.active_page()
    doc = doc or (page.Document if page is not None else None)
    if doc is None:
        return None
    dlg = DanglingDialog(doc)
    dlg.setModal(False)
    dlg.show()
    return dlg


class _Command:
    def GetResources(self):
        return {"MenuText": "Dangling Annotations...", "Pixmap": D.pixmap("TechDraw_DimensionRepair"),
                "ToolTip": "Lists the drawing's dangling dimensions (their model geometry is gone): select, "
                           "reattach or delete them."}

    def IsActive(self):
        return D.active_page() is not None

    def Activated(self):
        show_dangling()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Command())
    try:
        from . import events
        events.register("drawreattach.drag", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease),
                        _Drag.handle)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: reattach drag: %s\n" % error)
