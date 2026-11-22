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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Assembly"
MAGNET_PROP = "FwMagnetic"
V = App.Vector


def enabled():
    return App.ParamGet(PARAMS).GetBool("MagneticMates", True)


def set_enabled(on):
    App.ParamGet(PARAMS).SetBool("MagneticMates", bool(on))


def toggle():
    set_enabled(not enabled())


def snap_distance(comp):
    """How near two connection points must come: a tenth of the component's size, 2..25 mm."""
    try:
        d = comp.LinkedObject.Shape.BoundBox.DiagonalLength
    except Exception:
        d = 50.0
    return max(2.0, min(25.0, d * 0.1))


def _placement(comp):
    from . import asmexplode as ax
    try:
        return ax.gplacement(comp)
    except Exception:
        return comp.Placement


def points(comp):
    """[(element path in the component, global point)] of the component's published connection points."""
    from . import asmpublish as pb
    target = getattr(comp, "LinkedObject", None)
    if target is None:
        return []
    pl = _placement(comp)
    if not getattr(comp, "LinkTransform", False) and hasattr(target, "Placement"):
        pl = pl.multiply(target.Placement.inverse())
    out = []
    for asset in pb.assets(target.Document):
        for text in asset.ConnectionPoints:
            p = pb.point_of(target.Document, text)
            if p is None:
                continue
            name, _sep, sub = text.partition(":")
            path = sub if name == target.Name else "%s.%s" % (name, sub)
            out.append((path, pl.multVec(V(p))))
    return out


def magnetic_mates(asm):
    return [j for j in ac.mates(asm) if getattr(j, MAGNET_PROP, False)]


def _tied(asm, a, b):
    for j in magnetic_mates(asm):
        refs = {r[0].Name for r in (j.Reference1, j.Reference2) if r and r[0] is not None}
        if refs == {a.Name, b.Name}:
            return True
    return False


# [ and ]: which of the placed component's own points snaps (None: the nearest pair)
CYCLE = {"comp": None, "index": None, "last": None}    # last: (joint, comp, placement before the snap, time)
AGAIN_S = 30.0          # after a snap, [ / ] re-snap it for this long


def _chosen(comp, mine):
    i = CYCLE["index"]
    if i is None or CYCLE["comp"] != comp.Name or len(mine) < 2:
        return mine
    return [mine[i % len(mine)]]


def nearest(asm, comp):
    """(distance, my path, my point, other component, other path, other point) of the closest pair, or None."""
    mine = points(comp)
    if not mine:
        return None
    mine = _chosen(comp, mine)
    best = None
    for other in ac.components(asm):
        if other.Name == comp.Name:
            continue
        for opath, op in points(other):
            for path, p in mine:
                d = (op - p).Length
                if best is None or d < best[0]:
                    best = (d, path, p, other, opath, op)
    return best


def _next_name(asm):
    used = {j.Label for j in ac.mates(asm)}
    n = 1
    while "MagneticMate%d" % n in used:
        n += 1
    return "MagneticMate%d" % n


def _onto(comp, other, opath):
    """The pair for [ / ]: the chosen point of comp onto the same target point as before, at any distance."""
    mine = _chosen(comp, points(comp))
    theirs = [(q, op) for q, op in points(other) if q == opath]
    if not mine or not theirs:
        return None
    path, p = mine[0]
    return ((theirs[0][1] - p).Length, path, p, other, opath, theirs[0][1])


def snap(asm, comp, target=None):
    """Snap comp onto the nearest connection point within reach (target: (component, point path) to
    snap onto at any distance). Returns the new mate or None."""
    if comp is None or not enabled() or comp.Name in {c.Name for c in ac.grounded(asm)}:
        return None
    hit = nearest(asm, comp) if target is None else _onto(comp, *target)
    if hit is None:
        return None
    d, path, p, other, opath, op = hit
    if (target is None and d > snap_distance(comp)) or _tied(asm, comp, other):
        return None
    doc = asm.Document
    own = not doc.HasPendingTransaction       # inside Insert Components: part of its step
    if own:
        doc.openTransaction("Magnetic Mate")
    before = App.Placement(comp.Placement)
    try:
        pl = App.Placement(comp.Placement)
        pl.Base = pl.Base + (op - p)
        comp.Placement = pl
        joint = ac.add_mate(asm, "Coincident", (comp, path), (other, opath), name=_next_name(asm))
        if MAGNET_PROP not in joint.PropertiesList:
            joint.addProperty("App::PropertyBool", MAGNET_PROP, "FreeCAD", "Made by Magnetic Mate")
        setattr(joint, MAGNET_PROP, True)
    finally:
        if own:
            doc.commitTransaction()
    doc.recompute()
    CYCLE["last"] = (joint.Name, comp.Name, before, time.time())
    return joint


def _placing():
    """The component being placed now: Insert Components' preview, or the one being dragged."""
    try:
        from . import asmpm
        panel = asmpm.OPEN
        if isinstance(panel, asmpm.InsertComponentPanel) and panel.preview is not None:
            return panel.preview
    except Exception as _fw_err:
        _fw_log("asmmagnet.py:189", _fw_err)
    try:
        from . import asmui
        if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
            return asmui._dragged.get("comp")
    except Exception as _fw_err:
        _fw_log("asmmagnet.py:195", _fw_err)
    return None


def _say(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 4000)
    except Exception as _fw_err:
        _fw_log("asmmagnet.py:203", _fw_err)


def cycle(step=1):
    """[ (step -1) and ] (step +1): the next connection point of the component being placed, or
    the one that just snapped, snapped again on its next point. Returns the new mate, or True
    while placing, or None."""
    asm = ac.assembly_of(App.ActiveDocument)
    if asm is None or not enabled():
        return None
    comp = _placing()
    again = None
    if comp is None:
        last = CYCLE["last"]
        if last is None or time.time() - last[3] > AGAIN_S:
            return None
        joint = asm.Document.getObject(last[0])
        comp = asm.Document.getObject(last[1])
        if joint is None or comp is None:
            return None
        again = (joint, last[2])
    mine = points(comp)
    if len(mine) < 2:
        _say("%s has one connection point." % comp.Label)
        return None
    if CYCLE["comp"] != comp.Name or CYCLE["index"] is None:
        hit = nearest(asm, comp) if again is None else None
        used = getattr(again[0], "Reference1", None) if again else None
        start = 0
        paths = [p for p, _pt in mine]
        if again and used and used[0] is comp and used[1] and used[1][0] in paths:
            start = paths.index(used[1][0])
        elif hit is not None and hit[1] in paths:
            start = paths.index(hit[1])
        CYCLE["comp"], CYCLE["index"] = comp.Name, start
    CYCLE["index"] = (CYCLE["index"] + step) % len(mine)
    _say("Connection point %d of %d" % (CYCLE["index"] + 1, len(mine)))
    if again is None:
        return True
    joint, before = again
    target = None
    for r in (getattr(joint, "Reference1", None), getattr(joint, "Reference2", None)):
        if r and r[0] is not None and r[0] is not comp and r[1]:
            target = (r[0], r[1][0])
    if target is None:
        return None
    doc = asm.Document
    doc.openTransaction("Magnetic Mate")
    try:
        doc.removeObject(joint.Name)
        comp.Placement = before
        made = snap(asm, comp, target)
    finally:
        doc.commitTransaction()
    _say("Connection point %d of %d" % (CYCLE["index"] + 1, len(mine)))     # the solve's messages wrote over it
    return made


class _Keys(QtCore.QObject):
    """[ and ] in an assembly while a component is placed or just snapped."""

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # PySide hands a layout item here now and then while widgets are built
        t = event.type()
        if t not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            return False
        key = event.key()
        if key not in (QtCore.Qt.Key_BracketLeft, QtCore.Qt.Key_BracketRight):
            return False
        mods = event.modifiers()
        if (mods & QtCore.Qt.ControlModifier) and not (mods & QtCore.Qt.AltModifier):
            return False            # Ctrl+[ / Ctrl+] are other commands (AltGr+8/9 on a German keyboard is Ctrl+Alt)
        if isinstance(QtWidgets.QApplication.focusWidget(), (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox,
                                                            QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return False
        if _placing() is None and (CYCLE["last"] is None or time.time() - CYCLE["last"][3] > AGAIN_S):
            return False
        if t == QtCore.QEvent.ShortcutOverride:
            event.accept()
            return True
        try:
            cycle(-1 if key == QtCore.Qt.Key_BracketLeft else 1)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: magnetic mate points: %s\n" % error)
        return True


_keys = None


def after_drag():
    """After the drag button is let go: the dragged component snaps."""
    if QtWidgets.QApplication.mouseButtons() & QtCore.Qt.LeftButton:
        return                      # still dragging
    from . import asmui
    asm = ac.assembly_of(App.ActiveDocument)
    comp = asmui._dragged.get("comp")
    if asm is None or comp is None:
        return
    try:
        snap(asm, comp)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: magnetic mate: %s\n" % error)


def install():
    from . import asmui
    if getattr(asmui, "_fw_magnet", False):
        return
    old = asmui._path_after_drag

    def _path_after_drag():
        old()
        after_drag()
    asmui._path_after_drag = _path_after_drag
    global _keys
    if _keys is None:
        _keys = _Keys()
        try:
            # extapps/72: through the add-on's one dispatcher, for the two key event types it reads
            from . import events
            events.register("asmmagnet.keys", (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress), _keys.eventFilter)
        except Exception as _fw_err:
            App.Console.PrintLog("FreeWorks: magnetic mate keys: %s\n" % _fw_err)
            QtWidgets.QApplication.instance().installEventFilter(_keys)
    from . import asmpm
    panel = asmpm.InsertComponentPanel
    opts = panel._options

    def _options(self, comp):
        opts(self, comp)
        if comp is not None:
            try:
                snap(self.asm, comp)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: magnetic mate on insert: %s\n" % error)
    panel._options = _options
    asmui._fw_magnet = True
