""
















import FreeCAD as App
from PySide import QtCore

STOCK = "Sketch recompute"
_watch = [None]
_busy = [False]
_known = {}         # document name -> {sketch name: state} at the last rebuild or step


def _names():
    names = {STOCK}
    try:
        names.add(QtCore.QCoreApplication.translate("Command", STOCK))
    except Exception:
        pass
    return names


def _is_rebuild(name):
    return name in _names()


def _sketch_states(doc):
    """{sketch name: its geometry and dimensions}, to tell which sketch a step changed."""
    out = {}
    for o in doc.Objects:
        try:
            if o.TypeId != "Sketcher::SketchObject":
                continue
            out[o.Name] = (tuple(repr(g) for g in o.Geometry), tuple((c.Type, c.Value) for c in o.Constraints))
        except Exception:
            continue
    return out


def _in_edit(doc):
    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(doc.Name)
        return gdoc is not None and gdoc.getInEdit() is not None
    except Exception:
        return False


def _follow(doc_name, undo):
    if _busy[0]:
        return
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    _busy[0] = True
    try:
        if undo:
            # the rebuild step was just undone: the change under it goes with it
            if doc.RedoNames and _is_rebuild(doc.RedoNames[0]) and doc.UndoNames:
                doc.undo()
        else:
            # the change was just redone: the rebuild that followed it comes back too
            if doc.RedoNames and _is_rebuild(doc.RedoNames[0]):
                doc.redo()
        if not _in_edit(doc):
            known = _known.get(doc.Name)
            now = _sketch_states(doc)
            if known is not None:
                objs = [doc.getObject(n) for n, state in now.items() if known.get(n) != state]
                objs = [o for o in objs if o is not None]
                if objs:
                    for o in objs:
                        o.touch()
                    doc.recompute()
            _known[doc.Name] = now
    except Exception as error:
        App.Console.PrintLog("FreeCAD: undo after closing a sketch: %s\n" % error)
    finally:
        _busy[0] = False
    try:
        import FreeCADGui as Gui
        Gui.updateGui()
    except Exception:
        pass


class _Watch:
    def slotUndoDocument(self, doc):
        self._later(doc, True)

    def slotRedoDocument(self, doc):
        self._later(doc, False)

    def slotRecomputedDocument(self, doc):
        if _busy[0]:
            return
        try:
            _known[doc.Name] = _sketch_states(doc)
        except Exception:
            pass

    def slotDeletedDocument(self, doc):
        try:
            _known.pop(doc.Name, None)
        except Exception:
            pass

    @staticmethod
    def _later(doc, undo):
        if _busy[0]:
            return
        try:
            name = doc.Name
        except Exception:
            return
        # after FreeCAD has finished its own step
        QtCore.QTimer.singleShot(0, lambda: _follow(name, undo))


def start():
    if _watch[0] is None:
        try:
            w = _Watch()
            App.addDocumentObserver(w)
            _watch[0] = w
        except Exception as error:
            App.Console.PrintLog("FreeCAD: no undo watch for closing a sketch: %s\n" % error)
            _watch[0] = False
