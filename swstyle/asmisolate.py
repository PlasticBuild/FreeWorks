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

from . import asmcore as ac

MODES = ("Wireframe", "Hidden", "Transparent")
STATE = {"iso": None}


def _holder(obj):
    for p in getattr(obj, "InList", []) or []:
        if ac.is_subassembly(p) and obj in ac.sub_components(p):
            return p
    return None


def _units(asm, keep):
    """The components the isolate looks at: the top ones, and inside a subassembly that holds a
    kept component its own components instead of it."""
    holders = set()
    for c in keep:
        h = _holder(c)
        while h is not None:
            holders.add(h)
            h = _holder(h)

    def walk(cs):
        out = []
        for c in cs:
            if c in holders:
                out += walk(ac.sub_components(c))
            else:
                out.append(c)
        return out
    return walk(ac.components(asm)), holders


class Isolate:
    def __init__(self, asm, keep, including_suppressed=False):
        self.asm = asm
        self.keep = list(keep)
        self.saved = {}         # name: (visibility, display mode, override, material)
        self.mode = "Hidden"
        self.resolved = []      # Isolate including suppressed: resolved for the isolate
        if including_suppressed:
            from . import asmcomp
            for c in self.keep:
                if asmcomp.is_suppressed(c):
                    asmcomp.suppress(c, False)
                    self.resolved.append(c)
            if self.resolved:
                asm.Document.recompute()
        self.units, self.holders = _units(asm, self.keep)
        for c in list(self.units) + list(self.holders):
            vo = c.ViewObject
            if vo is None:
                continue
            self.saved[c.Name] = (vo.Visibility, getattr(vo, "DisplayMode", None),
                                  getattr(vo, "OverrideMaterial", False), getattr(vo, "ShapeMaterial", None))
        self.bar = None
        self.apply()
        self._show_bar()

    def others(self):
        return [c for c in self.units if c not in self.keep and c.ViewObject is not None]

    def apply(self, mode=None):
        """The removed components shown as mode."""
        from . import asmtools
        _settle()
        self.mode = mode or self.mode
        self._put_back(self.others())
        for c in list(self.keep) + list(self.holders):
            c.ViewObject.Visibility = True
        for c in self.others():
            vo = c.ViewObject
            if self.mode == "Hidden" or not hasattr(vo, "OverrideMaterial"):
                vo.Visibility = self.mode != "Hidden" and self._wire(vo)
            elif self.mode == "Wireframe":
                # a component (a link) has no wireframe mode of its own: its faces fully
                # see-through leave its edges drawn, the wireframe look
                vo.Visibility = True
                asmtools._fade(c, 1.0)
            else:
                vo.Visibility = True
                asmtools._fade(c)

    @staticmethod
    def _wire(vo):
        try:
            if "Wireframe" in vo.listDisplayModes():
                vo.DisplayMode = "Wireframe"
                return True
        except Exception as _fw_err:
            _fw_log("asmisolate.py:121", _fw_err)
        return True

    def _put_back(self, comps):
        for c in comps:
            was = self.saved.get(c.Name)
            vo = c.ViewObject
            if was is None or vo is None:
                continue
            vis, dmode, override, mat = was
            try:
                if dmode is not None and vo.DisplayMode != dmode:
                    vo.DisplayMode = dmode
                if mat is not None:
                    vo.ShapeMaterial = mat
                vo.OverrideMaterial = override
                vo.Visibility = vis
            except Exception as _fw_err:
                _fw_log("asmisolate.py:139", _fw_err)

    def save_display_state(self, name=None):
        """The isolated look as a new display state; the active one keeps its own look."""
        from . import displaystates as ds
        doc = self.asm.Document
        if not ds.names(doc):

            # it keeps the look from before Isolate, and the isolated look is the next one
            _settle()
            self._put_back(list(self.units) + list(self.holders))
            ds.ensure_default(doc)
            self.apply()
        data = ds._data(doc)
        data.setdefault("order", [])
        data.setdefault("states", {})
        name = (name or "").strip() or ds._next_name(doc)
        if name in data["states"]:
            raise ValueError("There is already a display state named %s" % name)
        data["states"][name] = ds.capture(doc)
        data["order"].append(name)
        ds._save(doc, data)
        try:
            from . import configmanager
            configmanager.refresh_all()
        except Exception as _fw_err:
            _fw_log("asmisolate.py:158", _fw_err)
        return name

    def exit(self):
        _settle()               # Isolate's fade still running would hide the components again after this
        self._put_back(list(self.units) + list(self.holders))
        if self.resolved:
            from . import asmcomp
            for c in self.resolved:
                try:
                    asmcomp.suppress(c, True)
                except Exception as error:
                    App.Console.PrintWarning("FreeCAD: Exit Isolate: %s\n" % error)
            self.resolved = []
            self.asm.Document.recompute()
        if self.bar is not None:
            try:
                self.bar.hide()
                self.bar.deleteLater()
            except Exception as _fw_err:
                _fw_log("asmisolate.py:178", _fw_err)
            self.bar = None
        if STATE["iso"] is self:
            STATE["iso"] = None

    def _show_bar(self):
        mw = Gui.getMainWindow()
        gl = [w for w in mw.findChildren(QtWidgets.QWidget) if w.inherits("QOpenGLWidget") and w.isVisible()]
        view = max(gl, key=lambda w: w.width() * w.height()) if gl else None
        bar = QtWidgets.QFrame(view.parentWidget() if view is not None else mw)
        bar.setObjectName("SWIsolateBar")
        bar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.addWidget(QtWidgets.QLabel("Isolate"))
        self.combo = QtWidgets.QComboBox()
        self.combo.setObjectName("SWIsolateVisibility")
        self.combo.setToolTip("Visibility of Removed Components")
        self.combo.addItems(MODES)
        self.combo.setCurrentText(self.mode)
        self.combo.currentTextChanged.connect(self.apply)
        lay.addWidget(self.combo)
        save = QtWidgets.QPushButton("Save as Display State")
        save.setObjectName("SWIsolateSaveDisplayState")
        save.clicked.connect(lambda: self.save_display_state())
        lay.addWidget(save)
        button = QtWidgets.QPushButton("Exit Isolate")
        button.setObjectName("SWExitIsolate")
        button.clicked.connect(self.exit)
        lay.addWidget(button)
        bar.adjustSize()
        bar.move(12, 48)
        bar.show()
        bar.raise_()
        self.bar = bar


def _settle():
    """View > Transitions fades still running end now (optionsextras5's hide fade, viewspeeds' see-through)."""
    import importlib
    for name in ("optionsextras5", "viewspeeds"):
        try:
            getattr(importlib.import_module("." + name, __package__), "settle", lambda: None)()
        except Exception as _fw_err:
            _fw_log("asmisolate.py:222", _fw_err)


class _SaveWatch:
    ""


    def slotStartSaveDocument(self, doc, filename):
        iso = STATE.get("iso")
        try:
            mine = iso is not None and iso.asm.Document is doc
        except Exception:       # ReferenceError: the isolated assembly's document was closed
            STATE.pop("iso", None)
            return
        if not mine:
            return
        _settle()
        iso._put_back(list(iso.units) + list(iso.holders))
        iso._saving = True

    def slotFinishSaveDocument(self, doc, filename):
        iso = STATE.get("iso")
        if iso is None or not getattr(iso, "_saving", False):
            return
        iso._saving = False
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda: STATE.get("iso") is iso and iso.apply())


_save_watch = None


def watch_saves():
    global _save_watch
    if _save_watch is None:
        _save_watch = _SaveWatch()
        App.addDocumentObserver(_save_watch)


def isolate(comps, including_suppressed=False):
    comps = [c for c in comps if c is not None]
    if not comps:
        return None
    asm = ac.assembly_of(comps[0].Document)
    if asm is None:
        return None
    if STATE["iso"] is not None:
        STATE["iso"].exit()
    watch_saves()
    STATE["iso"] = Isolate(asm, comps, including_suppressed)
    return STATE["iso"]


def _mated(asm, joint):
    ""
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if not ref or ref[0] is None:
            continue
        subs = ref[1] if len(ref) > 1 else []
        hit = ac.reference(asm, ref[0], subs[0]) if subs and subs[0] else None
        c = hit[0] if hit else ref[0]
        if c is not None and c not in out and (c in ac.components(asm) or _holder(c) is not None):
            out.append(c)
    return out


def picked(asm):
    comps = []
    mates = ac.mates(asm)
    for s in Gui.Selection.getSelectionEx("", 0):
        if s.Object in mates:
            comps += [c for c in _mated(asm, s.Object) if c not in comps]
            continue
        for sub in s.SubElementNames or [""]:
            ref = ac.reference(asm, s.Object, sub) if sub else None
            c = ref[0] if ref else (s.Object if (s.Object in ac.components(asm) or _holder(s.Object) is not None) else None)
            if c is not None and c not in comps:
                comps.append(c)
    return comps


def isolate_including_suppressed():
    """View > Display > Isolate including suppressed."""
    asm = ac.assembly_of(App.ActiveDocument)
    if asm is None:
        return None
    comps = picked(asm)
    return isolate(comps, True) if comps else None


def exit_isolate():
    if STATE["iso"] is not None:
        STATE["iso"].exit()


def install():
    """The View's Isolate / Exit Isolate in an assembly: this Isolate (with its toolbar)."""
    from . import displayextras
    iso = displayextras.ISOLATE
    if getattr(iso, "_fw_asm", False):
        return
    start, leave = iso.start, iso.exit

    def start_(keep=None):
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is not None and keep is None:
            comps = picked(asm)
            if comps:
                return isolate(comps)
        return start(keep)

    def exit_():
        if STATE["iso"] is not None:
            return exit_isolate()
        return leave()
    iso.start, iso.exit = start_, exit_
    iso._fw_asm = True
    try:
        type(iso).on = property(lambda self: self.saved is not None or STATE["iso"] is not None)
    except Exception as _fw_err:
        _fw_log("asmisolate.py:320", _fw_err)
