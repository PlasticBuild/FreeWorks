# SPDX-License-Identifier: LGPL-2.1-or-later
"""A change count per document, for answers the FeatureManager asks on every paint of every row
(a mate's error or missing-reference mark, whether a row is a component). They change only when
the document does: an object made or deleted, a recompute, a joint's or group's property; so an
answer is kept while the count stays the same, instead of for a fixed time. In a 300-component
assembly the time-based answers were worked out again hundreds of times during one rebuild."""

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

_GEN = {}
_observer = []
_WATCH = ("Group", "LinkedObject", "Reference1", "Reference2", "Suppressed", "Activated", "FwMateError", "FwMateType",
          "Visibility", "JointType", "ObjectToGround", "Label", "Rigid", "FwComponents", "FwComponentFolder")


def gen(doc):
    if not _observer:
        install()
        return -1           # no observer yet: never kept
    return _GEN.get(doc.Name, 0)


def bump(doc=None, rebuilt=False):
    if doc is None:
        for k in list(_GEN):
            _GEN[k] += 1
        for k in list(_TOPO):
            _TOPO[k] += 1
    else:
        _GEN[doc.Name] = _GEN.get(doc.Name, 0) + 1
        if not rebuilt:
            _TOPO[doc.Name] = _TOPO.get(doc.Name, 0) + 1


_TOPO = {}      # as _GEN, but a rebuild alone (a drag step solves and rebuilds) leaves it


def topo(doc):
    """The document's change count, not counting rebuilds: for answers that depend only on which
    objects there are and the watched properties (which mates connect what)."""
    if not _observer:
        install()
        return -1
    return _TOPO.get(doc.Name, 0)


_ran = set()        # documents in which an object rebuilt since their before-recompute signal
_busy = set()       # documents between their before-recompute and recomputed signals


def recomputing(doc):
    try:
        # asmpkg364: FreeCAD's Document has a Recomputing flag, no State list (the test always raised)
        return doc.Name in _busy or bool(getattr(doc, "Recomputing", False))
    except Exception:
        return False


_frozen = []         # FeatureManager trees with painting held during an assembly's rebuild
_timer = []


def _trees():
    try:
        import FreeCADGui as Gui
        from . import fmtree
        return [t for t in Gui.getMainWindow().findChildren(fmtree.FeatureTree) if t.isVisible()]
    except Exception:
        return []


def _freeze(doc):
    ""


    try:
        from . import asmcore as ac
        if ac.assembly_of(doc) is None:
            return
    except Exception:
        return
    for t in _trees():
        if t.updatesEnabled():
            t.setUpdatesEnabled(False)
            _frozen.append(t)
    App.Console.PrintLog("FreeCAD: tree held for the rebuild (%d)\n" % len(_frozen))
    if _frozen and not _timer:
        try:
            from PySide import QtCore
            tm = QtCore.QTimer()
            tm.setInterval(300)
            tm.timeout.connect(_thaw_check)
            tm.start()
            _timer.append(tm)
        except Exception:
            _thaw()


_hold = []          # the debounce timer of hold()


def hold(doc, ms=200):
    """A batch of inserts or mates (a script, Pack and Go, a pattern): the tree's painting waits
    till they stop coming for ms, instead of repainting every row after each one."""
    if not App.GuiUp:
        return
    try:
        from PySide import QtCore
    except Exception:
        return
    if not _frozen:
        _freeze(doc)
    if not _frozen:
        return
    if not _hold:
        tm = QtCore.QTimer()
        tm.setSingleShot(True)
        tm.timeout.connect(_hold_done)
        _hold.append(tm)
    _hold[0].start(ms)


def _hold_done():
    if _busy and any(d in App.listDocuments() for d in _busy):
        _hold[0].start(100)
        return
    _thaw()


def _thaw_check():
    if _busy and any(d in App.listDocuments() for d in _busy):
        return          # still rebuilding (this timer also runs inside FreeCAD's progress loop)
    if _hold and _hold[0].isActive():
        return          # a batch of inserts still coming (hold)
    _thaw()


_held = {}          # model -> [(first, last, roles)] row changes held during an assembly rebuild


def _patch_rows():
    """The FeatureManager's per-row updates wait for the end of a rebuild (each one re-measured
    and re-drew rows; a rebuild of a 300-component assembly sent thousands)."""
    try:
        from . import fmtree
    except Exception:
        return
    M = fmtree.Model
    if getattr(M, "_fw_gen_rows", False):
        return
    data0 = M._data

    def _data(self, first, last, roles=()):
        if _frozen:
            try:
                _held.setdefault(self, []).append((QPersistent(first), QPersistent(last), tuple(roles or ())))
                return
            except Exception as _fw_err:
                _fw_log("asmgen.py:153", _fw_err)
        return data0(self, first, last, roles)
    _data.__wrapped__ = data0
    M._data = _data
    M._fw_gen_rows = True


_OVERLAY = {}       # (document, joint) -> (change count, overlays)
OVERLAY_HOLD = []   # a drag's mates switched off for the drag (asmisland): the marks as before it


def restamp_overlays(doc, old, new):
    """The marks worked out at change count old hold at new (asmisland put the mates back as
    they were)."""
    for k, v in list(_OVERLAY.items()):
        if k[0] == doc.Name and v[0] == old:
            _OVERLAY[k] = (new, v[1])


_CONNECTED = {}     # (document, assembly) -> (change count, names of the parts joined to a fixed one)


def _connected(asm, g):
    """The parts held through mates by a fixed component, worked out once per change count (as
    FreeCAD's isPartConnected, which walks every mate again for each mate row: 1.7 s at 300 mates)."""
    import UtilsAssembly
    key = (asm.Document.Name, asm.Name)
    hit = _CONNECTED.get(key)
    if g >= 0 and hit is not None and hit[0] == g:
        return hit[1]
    group = [o for o in asm.Group if o.TypeId == "Assembly::JointGroup"]
    joints = group[0].Group if group else []
    seen, edges = set(), {}
    for j in joints:
        if getattr(j, "Suppressed", False) or not hasattr(j, "JointType"):
            if hasattr(j, "ObjectToGround") and not getattr(j, "Suppressed", False) and j.ObjectToGround is not None:
                seen.add(j.ObjectToGround.Name)
            continue
        ends = []
        for prop in ("Reference1", "Reference2"):
            ref = getattr(j, prop, None)
            part = UtilsAssembly.getMovingPart(ref) if ref else None
            if part is not None:
                ends.append(part.Name)
        if len(ends) == 2:
            edges.setdefault(ends[0], set()).add(ends[1])
            edges.setdefault(ends[1], set()).add(ends[0])
    todo = list(seen)
    while todo:
        n = todo.pop()
        for m in edges.get(n, ()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    if g >= 0:
        _CONNECTED[key] = (g, seen)
    return seen


def _overlay_fast(vp, obj, g):
    """FreeCAD's mate row mark (Part_Detached when the moving part is held by nothing fixed),
    from _connected; None to ask FreeCAD."""
    try:
        import UtilsAssembly
        import FreeCADGui as Gui
        if g < 0 or not hasattr(obj, "Reference1"):
            return None
        asm = obj.Proxy.getAssembly(obj)
        if asm is None:
            return None
        part = UtilsAssembly.getMovingPart(obj.Reference1)
        if part is None:
            return {}
        if part.Name in _connected(asm, g):
            return {}
        return {Gui.IconPosition.BottomLeft: "Part_Detached"}
    except Exception as _fw_err:
        _fw_log("asmgen.py:overlay", _fw_err)
        return None


def _patch_overlays():
    """FreeCAD's mate row asks the solver, on every icon update, whether the moving part is
    connected to a fixed one (the detached mark): a walk of the whole mate graph each time,
    0.7 s of a 301-part rebuild. The answer changes only with the mates and fixed parts, so it is
    kept while the document's change count stays the same."""
    try:
        import JointObject
    except Exception:
        return
    VP = getattr(JointObject, "ViewProviderJoint", None)
    if VP is None or getattr(VP, "_fw_gen_overlay", False):
        return
    icons0 = VP.getOverlayIcons

    def getOverlayIcons(self):
        try:
            obj = self.app_obj
            doc = obj.Document
            key = (doc.Name, obj.Name)
            g = topo(doc)
            had = _OVERLAY.get(key)
            if g >= 0 and had is not None and (had[0] == g or OVERLAY_HOLD):
                return dict(had[1])
        except Exception:
            return icons0(self)
        out = _overlay_fast(self, obj, g)
        if out is None:
            out = icons0(self)
        if g >= 0:
            _OVERLAY[key] = (g, dict(out or {}))
        return out
    getOverlayIcons.__wrapped__ = icons0
    VP.getOverlayIcons = getOverlayIcons
    VP._fw_gen_overlay = True


_SHARED = {}        # the axis colours (from View preferences) -> the marker geometry all mates share


def _patch_markers():
    """FreeCAD builds a full coordinate-system marker (a disc, three axes, colours, scales) three
    times for every mate when a file opens: 606 markers, 1.4 s of a 301-part open, for markers
    shown only when a mate is picked or edited. The geometry is the same for every marker, so the
    mates share one copy and each keeps its own place (transform) and pick style. A mate whose
    axis colours are changed gets its own copy again."""
    try:
        import JointObject
        import SoSwitchMarker as SM
        from pivy import coin
        import UtilsAssembly
        import FreeCADGui as Gui
    except Exception:
        return
    Base = getattr(SM, "SoSwitchMarker", None)
    if Base is None or getattr(JointObject, "_fw_shared_marker", False) or JointObject.SoSwitchMarker is not Base:
        return

    class SharedMarker(Base):
        def __init__(self, vobj):
            coin.SoSwitch.__init__(self)
            self.axis_thickness = 3
            self.scaleFactor = 40
            view = App.ParamGet("User parameter:BaseApp/Preferences/View")
            key = (view.GetUnsigned("AxisXColor", 0xCC333300), view.GetUnsigned("AxisYColor", 0x33CC3300),
                   view.GetUnsigned("AxisZColor", 0x3333CC00))
            parts = _SHARED.get(key)
            if parts is None:
                parts = _SHARED[key] = self._geometry(key)
                for node in parts:
                    node.ref()      # held for the session: a closed document's markers must not free it
            (self.x_axis_so_color, self.y_axis_so_color, self.z_axis_so_color, self.draw_style) = parts[:4]
            self.app_obj = vobj.Object
            self.gui_doc = Gui.getDocument(self.app_obj.Document)
            self.transform = coin.SoTransform()
            self.pick = coin.SoPickStyle()
            self.setPickableState(True)
            self._jcs = coin.SoAnnotation()
            self._jcs.addChild(self.transform)
            self._jcs.addChild(self.pick)
            for sep in parts[4:]:
                self._jcs.addChild(sep)
            self.addChild(self._jcs)
            self.whichChild = coin.SO_SWITCH_NONE
            self._own = False

        def _geometry(self, key):
            colours = []
            for c in key:
                node = coin.SoBaseColor()
                node.rgb.setValue(UtilsAssembly.color_from_unsigned(c))
                colours.append(node)
            self.x_axis_so_color, self.y_axis_so_color, self.z_axis_so_color = colours
            self.draw_style = coin.SoDrawStyle()
            self.draw_style.style = coin.SoDrawStyle.LINES
            self.draw_style.lineWidth = self.axis_thickness
            seps = [self.plane_sep(0.4, 15),
                    self.line_sep([0.5, 0, 0], [1, 0, 0], colours[0]),
                    self.line_sep([0, 0.5, 0], [0, 1, 0], colours[1]),
                    self.line_sep([0, 0, 0], [0, 0, 1], colours[2])]
            return tuple(colours) + (self.draw_style,) + tuple(seps)

        def onChanged(self, vp, prop):
            if prop in ("color_X_axis", "color_Y_axis", "color_Z_axis") and not self._own:
                try:
                    self._unshare()
                except Exception as _fw_err:
                    _fw_log("asmgen.py:267", _fw_err)
            return Base.onChanged(self, vp, prop)

        def _unshare(self):
            old = [tuple(n.rgb.getValues()[0].getValue()) for n in
                   (self.x_axis_so_color, self.y_axis_so_color, self.z_axis_so_color)]
            parts = self._geometry((0, 0, 0))
            for node, rgb in zip(parts[:3], old):
                node.rgb.setValue(*rgb)
            while self._jcs.getNumChildren() > 2:
                self._jcs.removeChild(2)
            for sep in parts[4:]:
                self._jcs.addChild(sep)
            self._own = True

    JointObject.SoSwitchMarker = SharedMarker
    JointObject._fw_shared_marker = True


def QPersistent(index):
    from PySide import QtCore
    return QtCore.QPersistentModelIndex(index)


def _flush():
    from PySide import QtCore
    items = list(_held.items())
    _held.clear()
    for model, rows in items:
        if len(rows) > 40 and _repaint_all(model):
            continue        # many rows changed (a rebuild): one repaint of the tree, as each row would have
        seen = set()
        for first, last, roles in rows:
            if not first.isValid() or not last.isValid():
                continue
            key = (first.row(), last.row(), first.internalId(), roles)
            if key in seen:
                continue
            seen.add(key)
            try:
                type(model)._data.__wrapped__(model, QtCore.QModelIndex(first), QtCore.QModelIndex(last), roles)
            except Exception as _fw_err:
                _fw_log("asmgen.py:309", _fw_err)


def _repaint_all(model):
    """One change for every row: the tree repaints what it shows (each row asks its data again)
    instead of thousands of single-row changes after a big rebuild."""
    try:
        from PySide import QtCore
        root = QtCore.QModelIndex()
        n = model.rowCount(root)
        cols = max(1, model.columnCount(root))
        if n <= 0:
            return True
        model.dataChanged.emit(model.index(0, 0, root), model.index(n - 1, cols - 1, root), [])
        for t in _trees():
            try:
                t.viewport().update()
            except Exception as _fw_err:
                _fw_log("asmgen.py:327", _fw_err)
        return True
    except Exception:
        return False


def _thaw():
    try:
        _flush()
    except Exception as _fw_err:
        _fw_log("asmgen.py:337", _fw_err)
    while _frozen:
        t = _frozen.pop()
        try:
            t.setUpdatesEnabled(True)
            t.viewport().update()
        except Exception as _fw_err:
            _fw_log("asmgen.py:344", _fw_err)
    while _timer:
        try:
            _timer.pop().stop()
        except Exception as _fw_err:
            _fw_log("asmgen.py:349", _fw_err)


class _Observer:
    def slotBeforeRecomputeDocument(self, doc):
        _busy.add(doc.Name)
        _ran.discard(doc.Name)
        try:
            if any("Touched" in o.State or o.mustExecute() for o in doc.Objects):
                _ran.add(doc.Name)      # something to rebuild (it may fail: still counted)
        except Exception:
            _ran.add(doc.Name)
        _freeze(doc)

    def slotRecomputedObject(self, obj):
        try:
            _ran.add(obj.Document.Name)
        except Exception as _fw_err:
            _fw_log("asmgen.py:367", _fw_err)

    def slotCreatedObject(self, obj):
        bump(obj.Document)

    def slotDeletedObject(self, obj):
        bump(obj.Document)

    def slotChangedObject(self, obj, prop):
        if prop in _WATCH:
            bump(obj.Document)

    def slotRecomputedDocument(self, doc):
        _busy.discard(doc.Name)
        if doc.Name in _ran:
            bump(doc, rebuilt=True)     # a rebuild with nothing to rebuild (Ctrl+B on an unchanged model) keeps the answers
        _ran.discard(doc.Name)
        if _frozen and not recomputing(doc) and not (_hold and _hold[0].isActive()):
            _thaw()

    def slotFinishRestoreDocument(self, doc):
        bump(doc)

    def slotDeletedDocument(self, doc):
        _GEN.pop(doc.Name, None)
        _TOPO.pop(doc.Name, None)
        for k in [k for k in _OVERLAY if k[0] == doc.Name]:
            _OVERLAY.pop(k, None)
        _busy.discard(doc.Name)
        bump()          # another document's links may now be missing

    def slotCreatedDocument(self, doc):
        bump()
        # FreeCAD 1.1 does not call slotFinishRestoreDocument on Python observers: a file opening
        # shows only here, before its objects load. Count it again once the loading is over.
        try:
            after_load(doc.Name, bump)
            from . import asmcore
            after_load(doc.Name, asmcore.after_open)     # fixed flexible subassemblies held again
        except Exception as _fw_err:
            _fw_log("asmgen.py:406", _fw_err)


def after_load(name, fn, tries=200):
    """fn(doc) once the document name has finished loading (FreeCAD 1.1 gives Python observers
    no slotFinishRestoreDocument). Used by the observers that need the loaded file."""
    from PySide import QtCore

    def go(left=tries):
        doc = App.listDocuments().get(name)
        if doc is None:
            return
        if bool(getattr(doc, "Restoring", False)) and left > 0:
            QtCore.QTimer.singleShot(50, lambda: go(left - 1))
            return
        fn(doc)
    QtCore.QTimer.singleShot(0, go)


def _later(name):
    doc = App.listDocuments().get(name)
    if doc is not None:
        bump(doc)


def install():
    _patch_rows()
    _patch_overlays()
    _patch_markers()
    try:
        from . import asmlook
        asmlook.install()       # assembly PropertyManagers keep the pane's width
    except Exception as _fw_err:
        _fw_log("asmgen.py:439", _fw_err)
    try:
        from . import asmfastmate
        asmfastmate.install()
    except Exception as _fw_err:
        _fw_log("asmgen.py:444", _fw_err)
    try:
        from . import asmtreeorder
        asmtreeorder.install()
    except Exception as _fw_err:
        _fw_log("asmgen.py:449", _fw_err)
    try:
        from . import asmextref
        asmextref.install_freeze()
    except Exception as _fw_err:
        _fw_log("asmgen.py:454", _fw_err)
    try:
        from . import asmsketch
        asmsketch.install()     # Sketch in an assembly: an assembly layout sketch on the picked plane
    except Exception as _fw_err:
        _fw_log("asmgen.py:459", _fw_err)
    try:
        from . import asmcyldrag
        asmcyldrag.install()
    except Exception:
        pass
    try:
        from . import asmtesscache
        asmtesscache.install()  # Large Design Review: the parts' display meshes kept when an assembly is saved
    except Exception as _fw_err:
        _fw_log("asmgen.py:asmtesscache", _fw_err)
    try:
        from . import asmthread
        asmthread.install()     # Toolbox fasteners: Thread Display (Simplified / Cosmetic / Schematic)
    except Exception as _fw_err:
        _fw_log("asmgen.py:464", _fw_err)
    if not _observer:
        _observer.append(_Observer())
        App.addDocumentObserver(_observer[0])
