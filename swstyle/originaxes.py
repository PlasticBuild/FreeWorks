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
from PySide import QtCore

from . import paths

PARAM = "OriginAxesHidden"   # addon parameter (default on)
_allowed = set()             # (document name, axis name) the person showed
_patched = {}
_active = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def _origin_of(obj):
    try:
        return next((p for p in obj.InList if p.isDerivedFrom("App::Origin")), None)
    except Exception:
        return None


def is_origin_axis(obj):
    try:
        return obj.isDerivedFrom("App::Line") and _origin_of(obj) is not None
    except Exception:
        return False


def is_origin_part(obj):
    try:
        return obj.isDerivedFrom("App::Origin") or _origin_of(obj) is not None
    except Exception:
        return False


def allow(obj, on=True):
    """The person showed (on) or hid this origin, axis, plane or point."""
    if not is_origin_part(obj):
        return
    key = (obj.Document.Name, obj.Name)
    if on:
        _allowed.add(key)
    else:
        _allowed.discard(key)


def _picked(obj):
    try:
        for s in Gui.Selection.getSelectionEx(obj.Document.Name):
            if s.Object is obj or (_origin_of(obj) is not None and s.Object is _origin_of(obj)):
                return True
            if any(obj.Name + "." in sub or sub.endswith(obj.Name) for sub in s.SubElementNames):
                return True
    except Exception as _fw_err:
        _fw_log("originaxes.py:90", _fw_err)
    return False


def _wrap(module, name, marker):
    original = getattr(module, name, None)
    if original is None or name in _patched:
        return

    def wrapped(*args, **kwargs):
        _guard.append(1)           # its own Visibility changes are not Hide/Show Items
        try:
            result = original(*args, **kwargs)
        finally:
            _guard.pop()
        try:
            marker(*args, **kwargs)
        except Exception as _fw_err:
            _fw_log("originaxes.py:108", _fw_err)
        return result

    _patched[name] = (module, original)
    setattr(module, name, wrapped)


def _mark_view_types(key, on, doc=None):
    from . import viewtypes
    for o in viewtypes.objects_of(key, doc):
        allow(o, on)


def _mark_feature(obj, on):
    allow(obj, on)


_KEYS = (("App::Plane", ("Planes", "PrimaryPlanes")), ("App::Line", ("Axes",)), ("App::Point", ("Origins",)))
_guard = []                  # set while this module changes Visibility itself


def _flag_on(obj):
    """The document's View > Hide/Show setting for this origin item's type was set to shown."""
    try:
        from . import viewtypes
        meta = obj.Document.Meta
        for tid, keys in _KEYS:
            if obj.isDerivedFrom(tid):
                return any(meta.get(viewtypes.FLAG + k) == "1" for k in keys)
    except Exception as _fw_err:
        _fw_log("originaxes.py:138", _fw_err)
    return False


def _toggled(doc_name, name, now):
    """Hide/Show Items on a picked origin item (after FreeCAD flipped its Visibility to now)."""
    doc = App.listDocuments().get(doc_name)
    obj = doc.getObject(name) if doc is not None else None
    origin = _origin_of(obj) if obj is not None else None
    if origin is None or origin.ViewObject is None:
        return
    _guard.append(1)
    try:
        if not origin.ViewObject.Visibility:
            # nothing of it was on screen: the person asked to see this item
            for f in origin.OriginFeatures:
                f.ViewObject.Visibility = f is obj
            origin.ViewObject.Visibility = True
            allow(obj, True)
        elif now:
            allow(obj, True)
        else:
            allow(obj, False)
    finally:
        _guard.pop()
    if _active is not None:
        _active.soon()


class _DocObserver:
    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, obj, prop):
        if prop != "Visibility":
            return
        try:
            tid = obj.TypeId
        except Exception:
            return
        if is_origin_part(obj):
            if not _guard and obj.ViewObject is not None and not Gui.Control.activeDialog() and _picked(obj):
                if obj.isDerivedFrom("App::Origin"):
                    allow(obj, bool(obj.ViewObject.Visibility))
                else:   # Hide/Show Items with the item picked: the person's own, done after FreeCAD's change
                    QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, n=obj.Name,
                                             v=bool(obj.ViewObject.Visibility): _toggled(d, n, v))
            self.owner.soon()

    def slotFinishRestoreDocument(self, doc):
        _diag_later(6000, "opened %s" % doc.Name)
        _diag_later(30000, "opened %s +30s" % doc.Name)
        for key in [k for k in _allowed if k[0] == doc.Name]:
            _allowed.discard(key)
        self.owner.soon()

    def slotDeletedDocument(self, doc):
        for key in [k for k in _allowed if k[0] == doc.Name]:
            _allowed.discard(key)


class OriginAxes(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.hidden = 0            # for checks
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.check)
        self._observer = _DocObserver(self)
        App.addDocumentObserver(self._observer)
        try:
            from . import viewtypes
            _wrap(viewtypes, "set_shown", _mark_view_types)
        except Exception as _fw_err:
            _fw_log("originaxes.py:213", _fw_err)
        try:
            from . import contextbar
            _wrap(contextbar, "show_origin_feature", _mark_feature)
        except Exception as _fw_err:
            _fw_log("originaxes.py:218", _fw_err)
        self.soon()

    def soon(self, ms=0):
        self._timer.start(ms)

    def check(self):
        if not enabled():
            return
        _guard.append(1)
        try:
            self._check()
        finally:
            _guard.pop()

    def _check(self):
        try:
            busy = Gui.Control.activeDialog()
        except Exception:
            busy = False
        if not busy:
            try:
                from . import sketchstart
                busy = sketchstart._active is not None and not getattr(sketchstart._active, "done", False)
            except Exception as _fw_err:
                _fw_log("originaxes.py:243", _fw_err)
        if busy:
            self.soon(400)         # a task dialog may be showing them to pick from; look again
            return
        for doc in list(App.listDocuments().values()):
            for obj in doc.Objects:
                try:
                    if not obj.isDerivedFrom("App::Origin") or obj.ViewObject is None or not obj.ViewObject.Visibility:
                        continue
                    kept = [o for o in [obj] + list(obj.OriginFeatures) if (doc.Name, o.Name) in _allowed
                            or (o is not obj and o.ViewObject.Visibility and _flag_on(o))]
                    if not kept:
                        obj.ViewObject.Visibility = False
                        self.hidden += 1
                except Exception as _fw_err:
                    _fw_log("originaxes.py:258", _fw_err)
            for obj in doc.Objects:
                if not is_origin_axis(obj) or obj.ViewObject is None:
                    continue
                if obj.ViewObject.Visibility and (doc.Name, obj.Name) not in _allowed and not _flag_on(obj):
                    try:
                        obj.ViewObject.Visibility = False
                        self.hidden += 1
                    except Exception as _fw_err:
                        _fw_log("originaxes.py:267", _fw_err)

    def remove(self):
        self._timer.stop()
        try:
            App.removeDocumentObserver(self._observer)
        except Exception as _fw_err:
            _fw_log("originaxes.py:274", _fw_err)
        for name, (module, original) in list(_patched.items()):
            setattr(module, name, original)
        _patched.clear()


def start():
    global _active
    if _active is None:
        _active = OriginAxes()
        _diag_later(20000, "startup +20s")
    return _active


def stop():
    global _active
    if _active is not None:
        _active.remove()
        _active.deleteLater()
        _active = None


# ------------------------------------------------------------------ diag (temporary, fix03)
DIAG_PARAM = "OriginAxesDiag"      # addon parameter (off; set true to log the lines drawn in the view)


def _diag_paths():
    import os
    return [os.path.join(App.getUserAppDataDir(), "axes_diag.txt")]


def write_diag(reason=""):
    import time
    from pivy import coin
    out = ["axes_diag %s reason=%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), reason)]
    p = out.append
    try:
        p("activeDialog=%r active=%r hidden=%r allowed=%r" % (Gui.Control.activeDialog(), _active is not None,
                                                              getattr(_active, "hidden", None), sorted(_allowed)))
    except Exception as e:
        p("state err %r" % e)
    try:
        from . import sketchstart
        p("sketchstart._active=%r" % sketchstart._active)
    except Exception as e:
        p("sketchstart err %r" % e)
    try:
        from . import planes
        p("planes enabled=%r" % planes.enabled())
    except Exception as e:
        planes = None
        p("planes err %r" % e)
    for doc in App.listDocuments().values():
        p("== doc %s (%s)" % (doc.Name, doc.FileName))
        try:
            if planes is not None:
                p("shown_planes=%r picked=%r" % ([o.Name for o in planes.shown_planes(doc.Name)],
                                                 [o.Name for o in planes.picked_planes(doc.Name)]))
        except Exception as e:
            p("planes state err %r" % e)
        for o in doc.Objects:
            t = o.TypeId
            if any(k in t for k in ("Origin", "Line", "Plane", "Point", "Coordinate", "Datum", "Body", "Sketch")):
                vo = o.ViewObject
                p("  %s %s '%s' vis=%r in=%s" % (o.Name, t, o.Label, vo.Visibility if vo else None, [i.Name for i in o.InList]))
        gdoc = Gui.getDocument(doc.Name)
        owners = {}
        for o in doc.Objects:
            try:
                owners[o.ViewObject.RootNode] = o
            except Exception as _fw_err:
                _fw_log("originaxes.py:349", _fw_err)
        for vi, view in enumerate(gdoc.mdiViewsOfType("Gui::View3DInventor") if hasattr(gdoc, "mdiViewsOfType") else [gdoc.ActiveView]):
            try:
                viewer = view.getViewer()
                roots = [("scene", view.getSceneGraph())]
                try:
                    roots.append(("render", viewer.getSoRenderManager().getSceneGraph()))
                except Exception as _fw_err:
                    _fw_log("originaxes.py:357", _fw_err)
                try:
                    p("view%d axisCross=%r" % (vi, view.hasAxisCross()))
                except Exception as _fw_err:
                    _fw_log("originaxes.py:361", _fw_err)
                region = viewer.getSoRenderManager().getViewportRegion()
            except Exception as e:
                p("view err %r" % e)
                continue
            seen = set()
            for rname, root in roots:
                for cls in (coin.SoLineSet, coin.SoIndexedLineSet, getattr(coin, "SoAxisCrossKit", None)):
                    if cls is None:
                        continue
                    sa = coin.SoSearchAction()
                    sa.setType(cls.getClassTypeId())
                    sa.setInterest(coin.SoSearchAction.ALL)
                    sa.setSearchingAll(True)
                    sa.apply(root)
                    paths = sa.getPaths()
                    for i in range(paths.getLength()):
                        path = paths[i]
                        tail = path.getTail()
                        key = (rname, int(tail.this) if hasattr(tail, "this") else id(tail))
                        owner = None
                        names = []
                        for j in range(path.getLength()):
                            n = path.getNode(j)
                            if owner is None:
                                for rn, o in owners.items():
                                    try:
                                        if rn == n:
                                            owner = o
                                            break
                                    except Exception as _fw_err:
                                        _fw_log("originaxes.py:392", _fw_err)
                            nm = str(n.getName())
                            names.append(n.getTypeId().getName().getString() + (":" + nm if nm else ""))
                        try:
                            bb = coin.SoGetBoundingBoxAction(region)
                            bb.apply(path)
                            box = bb.getBoundingBox()
                            lo, hi = box.getMin().getValue(), box.getMax().getValue()
                            size = "bbox %s..%s" % (tuple(round(x, 1) for x in lo), tuple(round(x, 1) for x in hi))
                        except Exception as e:
                            size = "bbox err %r" % e
                        p("  [%s] %s owner=%s %s :: %s" % (rname, cls.__name__, owner.Name if owner else None, size,
                                                         " / ".join(names[-8:])))
    text = "\n".join(out) + "\n"
    for path in _diag_paths():
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception as _fw_err:
            _fw_log("originaxes.py:411", _fw_err)
    return text


def _diag_later(ms, reason):
    if not paths.params().GetBool(DIAG_PARAM, False):
        return
    def run():
        try:
            write_diag(reason)
        except Exception as e:
            for path in _diag_paths():
                try:
                    open(path, "a").write("diag failed %r\n" % e)
                except Exception as _fw_err:
                    _fw_log("originaxes.py:426", _fw_err)
    QtCore.QTimer.singleShot(ms, run)
