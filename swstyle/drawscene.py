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


from PySide import QtCore, QtWidgets

USER = 65536                     # QGraphicsItem.UserType
FACE_TYPE = USER + 20            # TechDraw's view face (QGIFace)
LABEL_TYPE = USER + 3            # TechDraw's view-name label under a view frame (QGCustomLabel)
_HOOKED = {}


MODE = {"on": False, "run": None, "seen": False, "ticks": 0}


def faces_pickable():
    ""

    if MODE["on"]:
        return True
    try:
        from . import selfilter as SF
        s = SF.state()
        return bool(s.filtering() and "face" in s.allowed_kinds())
    except Exception:
        return False


def _poke_all():
    for t in list(_HOOKED.values()):
        t.poke()


def face_mode(run=None, interactive=False):
    ""



    MODE.update(on=True, run=run, seen=False, ticks=0)
    _observe()
    _poke_all()
    if interactive:
        QtCore.QTimer.singleShot(300, _watch_tool)
    try:
        import FreeCADGui as Gui
        if run:
            Gui.getMainWindow().statusBar().showMessage("Pick a face in a drawing view", 0)
    except Exception as _fw_err:
        _fw_log("drawscene.py:face_mode", _fw_err)


def face_mode_off():
    if MODE["on"]:
        MODE.update(on=False, run=None, seen=False, ticks=0)
        _poke_all()


def _tool_cursor():
    """True while a FreeCAD drawing tool's own (bitmap) cursor is on a sheet."""
    try:
        for t in list(_HOOKED.values()):
            for gv in t.scene.views():
                if gv.viewport().cursor().shape() == QtCore.Qt.BitmapCursor:
                    return True
    except Exception as _fw_err:
        _fw_log("drawscene.py:cursor", _fw_err)
    return False


def _watch_tool():
    if not MODE["on"] or MODE["run"]:
        return
    MODE["ticks"] += 1
    busy = _tool_cursor()
    if busy:
        MODE["seen"] = True
    if (MODE["seen"] and not busy) or (not MODE["seen"] and MODE["ticks"] > 10) or MODE["ticks"] > 3000:
        face_mode_off()
        return
    QtCore.QTimer.singleShot(300, _watch_tool)


class _Picks:
    def addSelection(self, doc, obj, sub, pos):
        cmd = MODE["run"]
        face = str(sub or "").split(".")[-1].startswith("Face")
        if face and not faces_pickable() and _is_view(doc, obj):

            def to_view():
                try:
                    import FreeCADGui as Gui
                    Gui.Selection.removeSelection(doc, obj, sub)
                    Gui.Selection.addSelection(doc, obj)
                except Exception as _fw_err:
                    _fw_log("drawscene.py:to_view", _fw_err)
            QtCore.QTimer.singleShot(0, to_view)
            return
        if not (MODE["on"] and cmd and face):
            return

        def go():
            face_mode_off()
            try:
                import FreeCADGui as Gui
                Gui.runCommand(cmd, 0)
            except Exception as _fw_err:
                _fw_log("drawscene.py:run", _fw_err)
        QtCore.QTimer.singleShot(0, go)

    def clearSelection(self, doc):
        if MODE["on"] and MODE["run"]:
            face_mode_off()


def _is_view(doc, name):
    try:
        import FreeCAD as App
        o = App.getDocument(doc).getObject(name)
        return o is not None and o.isDerivedFrom("TechDraw::DrawViewPart")
    except Exception:
        return False


_OBSERVER = []


def _observe():
    if _OBSERVER:
        return
    try:
        import FreeCADGui as Gui
        _OBSERVER.append(_Picks())
        Gui.Selection.addObserver(_OBSERVER[0])
    except Exception as _fw_err:
        _fw_log("drawscene.py:observe", _fw_err)


def _kept_boxes(doc):
    """Sheet boxes (mm) of doc's views whose faces carry something (a section cut, a hatch or fill): their faces
    are drawn as TechDraw draws them."""
    out = []
    if doc is None:
        return out
    hatched = set()
    for o in doc.Objects:
        if o.TypeId in ("TechDraw::DrawHatch", "TechDraw::DrawGeomHatch"):
            src = getattr(o, "Source", None)
            try:
                for s in (src if isinstance(src, (list, tuple)) else [src]):
                    v = s[0] if isinstance(s, tuple) else s
                    if v is not None:
                        hatched.add(v.Name)
            except Exception as _fw_err:
                _fw_log("drawscene.py:hatched", _fw_err)
    try:
        from . import drawmenu
        for o in doc.Objects:
            if o.isDerivedFrom("TechDraw::DrawViewPart") and (o.isDerivedFrom("TechDraw::DrawViewSection")
                                                             or o.Name in hatched):
                b = drawmenu.view_box(o)
                if b is not None:
                    out.append(b)
    except Exception as _fw_err:
        _fw_log("drawscene.py:kept", _fw_err)
    return out


def tidy(scene, doc=None):
    ""


    if scene is None:
        return 0
    pick = faces_pickable()
    kept = _kept_boxes(doc)
    rez = None
    n = 0
    for it in scene.items():
        try:
            t = it.type()
        except Exception:
            continue
        if t == FACE_TYPE:
            keep = pick
            if not keep and kept:
                if rez is None:
                    from . import drawings as D
                    rez = D.REZ
                c = it.sceneBoundingRect().center()
                x, y = c.x() / rez, -c.y() / rez
                keep = any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in kept)
            want = 1.0 if keep else 0.0
            if it.opacity() != want:
                it.setOpacity(want)
                n += 1
        elif t == LABEL_TYPE:
            if it.opacity() != 0.0:
                it.setOpacity(0.0)
                n += 1
    return n


class _Tidier(QtCore.QObject):
    """Runs tidy shortly after the sheet is painted (a view drawn again shows as a paint of the sheet window).
    Not QGraphicsScene.changed: with that signal connected Qt works out the bounding box of the whole view
    for each line TechDraw adds to it, so drawing a view cost the square of its line count (a 50-part view
    with 1000 lines: 25 s instead of 1 s; Draft quality, 5000 lines: 5 minutes). After a pass that changed
    nothing the next one waits ten times as long as that pass took, so hovering a big sheet stays light."""
    def __init__(self, scene, doc=None, gv=None):
        super().__init__(scene)
        self.scene = scene
        self.doc = doc
        self.rest = 0.0
        self.last = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.run)
        if gv is not None:
            try:
                gv.viewport().installEventFilter(self)
            except Exception as _fw_err:
                _fw_log("drawscene.py:filter", _fw_err)

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.Paint:
                self.poke()
        except Exception as _fw_err:
            _fw_log("drawscene.py:paint", _fw_err)
        return False

    def poke(self, *args):
        if not self.timer.isActive():
            import time
            wait = self.last + self.rest - time.perf_counter()
            self.timer.start(max(60, int(wait * 1000)))

    def run(self):
        import time
        t0 = time.perf_counter()
        try:
            n = tidy(self.scene, self.doc)
        except Exception as _fw_err:
            _fw_log("drawscene.py:run", _fw_err)
            n = 0
        self.last = time.perf_counter()
        self.rest = 0.0 if n else 10.0 * (self.last - t0)


def regroup(doc):
    ""


    if doc is None:
        return 0
    n = 0
    try:
        import FreeCADGui as Gui
        gd = Gui.getDocument(doc.Name)
        was = gd.Modified if gd is not None else None
    except Exception:
        gd, was = None, None
    for o in doc.Objects:
        try:
            for prop in o.PropertiesList:
                if o.getGroupOfProperty(prop) == "FreeWorks":
                    o.setGroupOfProperty(prop, "FreeCAD")
                    n += 1
        except Exception as _fw_err:
            _fw_log("drawscene.py:regroup", _fw_err)
    if gd is not None and was is not None and gd.Modified != was:
        gd.Modified = was
    return n


def hook(gv, page=None):
    """Watch the scene of a sheet's graphics view gv (TechDraw's QGVPage); page: its sheet (its drawing's old
    property groups are renamed, see regroup)."""
    if page is not None:
        try:
            regroup(page.Document)
        except Exception as _fw_err:
            _fw_log("drawscene.py:hook regroup", _fw_err)
    try:
        scene = gv.scene()
    except Exception:
        return False
    if scene is None or id(scene) in _HOOKED:
        return False
    _HOOKED[id(scene)] = _Tidier(scene, page.Document if page is not None else None, gv)
    try:
        scene.destroyed.connect(lambda *a, k=id(scene): _HOOKED.pop(k, None))
    except Exception as _fw_err:
        _fw_log("drawscene.py:hook", _fw_err)
    _watch_filters()
    _observe()
    _HOOKED[id(scene)].run()
    return True


_WATCHING = []


def _watch_filters():
    """A Selection Filter pressed or released: every watched sheet's faces follow at once."""
    if _WATCHING:
        return
    try:
        from . import selfilter as SF
        SF.state().changed.connect(lambda *a: _poke_all())
        _WATCHING.append(True)
    except Exception as _fw_err:
        _fw_log("drawscene.py:filters", _fw_err)
