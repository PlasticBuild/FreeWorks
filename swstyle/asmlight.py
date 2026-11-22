# SPDX-License-Identifier: LGPL-2.1-or-later
""



















_FW_SEEN = set()



def _qt_safe(fn):
    """A tree Model override that never lets an error out into Qt (FreeCAD on Windows aborts):
    rows of objects deleted while a document closes give no data."""
    def data(self, index, role=0):
        try:
            return fn(self, index, role)
        except Exception as error:
            if not isinstance(error, (ReferenceError, RuntimeError)):
                App.Console.PrintLog("FreeCAD: tree row: %r\n" % (error,))
            return None
    return data

def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

Qt = QtCore.Qt
PARAM = "User parameter:BaseApp/Preferences/Mod/SWStyle/Assembly"
STAMP_PROP = "FwLightStamp"

AUTO_LIGHT = "PerfAutoLightweight"
RESOLVE_SUBS = "PerfAlwaysResolveSubs"
CHECK_OOD = "PerfCheckOutOfDate"
RESOLVE_MODE = "PerfResolveLightweight"
REBUILD_ON_LOAD = "PerfRebuildOnLoad"
RESOLVE_ON_EXPAND = "PerfResolveOnExpand"
                                            # 2026 added the option to keep it lightweight
CHECK_CHOICES = ("Don't Check", "Indicate", "Always Resolve")
RESOLVE_CHOICES = ("Prompt", "Always")
REBUILD_CHOICES = ("Prompt", "Always", "Never")
RESOLVE_TEXT = "This operation requires the lightweight component to be resolved. Resolve it now?"
REBUILD_TEXT = "The assembly has components that need to be rebuilt. Rebuild the assembly now?"
ASK = {"answer": None}          # a check's answer for the boxes (None: show them)
LAST = {}


def _p():
    return App.ParamGet(PARAM)


def auto_lightweight():
    return _p().GetBool(AUTO_LIGHT, False)


def always_resolve_subs():
    return _p().GetBool(RESOLVE_SUBS, True)


def check_out_of_date():
    v = _p().GetString(CHECK_OOD, CHECK_CHOICES[0])
    return v if v in CHECK_CHOICES else CHECK_CHOICES[0]


def resolve_on_expand():
    return _p().GetBool(RESOLVE_ON_EXPAND, True)


def resolve_mode():
    v = _p().GetString(RESOLVE_MODE, RESOLVE_CHOICES[0])
    return v if v in RESOLVE_CHOICES else RESOLVE_CHOICES[0]


def mark_cosmetic():
    ""
    from . import paths
    return not paths.params().GetBool("SmartSavePrompts", True)


def set_mark_cosmetic(on):
    from . import paths
    paths.params().SetBool("SmartSavePrompts", not bool(on))


def rebuild_on_load():
    v = _p().GetString(REBUILD_ON_LOAD, REBUILD_CHOICES[0])
    return v if v in REBUILD_CHOICES else REBUILD_CHOICES[0]


# ---------------------------------------------------------------- state
def _part_doc(comp):
    linked = getattr(comp, "LinkedObject", None)
    d = getattr(linked, "Document", None)
    return d if d is not None and d is not comp.Document else None


def _file_time(d):
    try:
        return os.path.getmtime(d.FileName) if d is not None and d.FileName else 0.0
    except OSError:
        return 0.0


def is_lightweight(comp):
    from . import asmcomp
    return asmcomp.is_lightweight(comp)


def stamp(comp):
    """Keep the part file's time with the lightweight component."""
    if STAMP_PROP not in comp.PropertiesList:
        comp.addProperty("App::PropertyFloat", STAMP_PROP, "FreeCAD", "Part file time when made lightweight")
        comp.setEditorMode(STAMP_PROP, 2)
    setattr(comp, STAMP_PROP, _file_time(_part_doc(comp)))
    try:
        comp.purgeTouched()
    except Exception as _fw_err:
        _fw_log("asmlight.py:131", _fw_err)


def out_of_date(comp):
    """A lightweight component whose part changed since: its file is newer, or it has unsaved changes."""
    if not is_lightweight(comp):
        return False
    d = _part_doc(comp)
    if d is None:
        return False
    try:
        if any("Touched" in o.State for o in d.Objects):
            return True
    except Exception as _fw_err:
        _fw_log("asmlight.py:145", _fw_err)
    kept = getattr(comp, STAMP_PROP, 0.0) or 0.0
    return bool(kept) and _file_time(d) > kept + 1e-3


def set_lightweight(comp, on=True):
    from . import asmcomp
    asmcomp.set_lightweight(comp, on)
    if on:
        stamp(comp)
    return True


def lightweight_components(asm):
    return [c for c in ac.components(asm) if is_lightweight(c)]


def resolved_components(asm):
    from . import asmcomp
    return [c for c in ac.components(asm) if not is_lightweight(c) and not asmcomp.is_suppressed(c)]


def set_all(asm, lightweight):
    """Set Resolved to Lightweight / Set Lightweight to Resolved on the top assembly."""
    doc = asm.Document
    todo = resolved_components(asm) if lightweight else lightweight_components(asm)
    if lightweight and always_resolve_subs():
        todo = [c for c in todo if not ac.is_subassembly(c)]
    doc.openTransaction("Set Resolved to Lightweight" if lightweight else "Set Lightweight to Resolved")
    try:
        for c in todo:
            set_lightweight(c, lightweight)
    finally:
        doc.commitTransaction()
    _refresh()
    return todo


def _refresh():
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmlight.py:188", _fw_err)


def _ask(title, text):
    if ASK["answer"] is not None:
        LAST["asked"] = text
        return ASK["answer"]
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setWindowTitle(title)
    box.setIcon(QtWidgets.QMessageBox.Question)
    box.setText(text)
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    return box.exec() == QtWidgets.QMessageBox.Yes


def ensure_resolved(comps, title="FreeCAD"):
    """An operation that needs the full component: lightweight ones resolve (Prompt asks first).
    False when the user said no."""
    light = [c for c in comps if c is not None and is_lightweight(c)]
    if not light:
        return True
    if resolve_mode() == "Prompt" and not _ask("Resolve Lightweight", RESOLVE_TEXT):
        return False
    for c in light:
        set_lightweight(c, False)
    _refresh()
    return True


# ---------------------------------------------------------------- expanding a row
def expanded_component(view, index):
    """The component a tree row stands for (the FeatureManager's model or FreeCAD's tree)."""
    try:
        model = view.model()
        node = model.node(index) if hasattr(model, "node") else None
        obj = getattr(node, "obj", None) if node is not None else None
        if obj is None:
            from . import fmtree, asmui
            doc = App.ActiveDocument
            text = str(index.data(Qt.DisplayRole) or "")
            obj = fmtree._object(doc, asmui.plain(text)) if doc is not None and text else None
        if obj is not None and getattr(obj, "TypeId", "") in ("App::Link", "Assembly::AssemblyLink"):
            return obj
    except (RuntimeError, ReferenceError) as _fw_err:
        _fw_log("asmlight.py:232", _fw_err)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: expanded row: %s\n" % error)
    return None


def on_expanded(view, index):
    ""

    if not resolve_on_expand():
        return False
    comp = expanded_component(view, index)
    if comp is None or not is_lightweight(comp):
        return False
    set_lightweight(comp, False)
    QtCore.QTimer.singleShot(0, _refresh)
    return True


def attach_expand(views):
    for view in views:
        try:
            if view is None or view.property("fw_light_expand"):
                continue
            view.setProperty("fw_light_expand", True)
            view.expanded.connect(lambda index, v=view: on_expanded(v, index))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: expand hook: %s\n" % error)


# ---------------------------------------------------------------- on open
def after_open(doc, chosen=None):
    """Performance > Assemblies rows when an assembly opens."""
    asm = ac.assembly_of(doc)
    if asm is None:
        return {}
    out = {}
    comps = ac.components(asm)
    need = _needs_rebuild(doc)
    if auto_lightweight() and chosen in (None, "Resolved"):
        made = []
        for c in comps:
            if is_lightweight(c) or (always_resolve_subs() and ac.is_subassembly(c)):
                continue
            set_lightweight(c, True)
            made.append(c.Name)
        out["lightweight"] = made
    for c in comps:
        if is_lightweight(c) and STAMP_PROP not in c.PropertiesList:
            stamp(c)
    if check_out_of_date() == "Always Resolve":
        stale = [c for c in comps if out_of_date(c)]
        for c in stale:
            set_lightweight(c, False)
        out["resolved"] = [c.Name for c in stale]
    mode = rebuild_on_load()
    if chosen == "Large Design Review":
        mode = "Never"                  # Large Design Review loads nothing to rebuild (its own row updates)
    if need and (mode == "Always" or (mode == "Prompt" and _ask("Rebuild", REBUILD_TEXT))):
        doc.recompute()
        out["rebuilt"] = True
    else:
        out["rebuilt"] = False
    out["needed"] = bool(need)
    LAST["open"] = out
    return out


def _needs_rebuild(doc):
    docs = [doc]
    asm = ac.assembly_of(doc)
    for c in ac.components(asm) if asm is not None else []:
        d = _part_doc(c)
        if d is not None and d not in docs:
            docs.append(d)
    own = ("Assembly::AssemblyObject", "Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup")
    try:
        # FreeCAD touches the assembly object itself when it loads: not a component out of date
        # open127: a component whose part file was not found is File Not Found's question, not a rebuild
        return any(("Error" in o.State or ("Touched" in o.State and o.TypeId not in own and not
                                           getattr(o, "Proxy", None).__class__.__name__.startswith("Joint")))
                   and not _file_not_found(o)
                   for d in docs for o in d.Objects)
    except Exception:
        return False


def _file_not_found(o):
    try:
        return o.isDerivedFrom("App::Link") and o.LinkedObject is None
    except Exception:
        return False


# ---------------------------------------------------------------- tree icons
_ICONS = {}


def feather_icon(base, red=False):
    ""
    if not isinstance(base, QtGui.QIcon) or base.isNull():
        return base
    key = (base.cacheKey(), red)
    if key in _ICONS:
        return _ICONS[key]
    icon = QtGui.QIcon()
    for size in (16, 24, 32):
        src = base.pixmap(size, size)
        if src.isNull():
            continue
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.drawPixmap(QtCore.QRect(0, 0, size, size), src)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = size * 0.62
        x0, y0 = size - s, 0.0
        vane = QtGui.QPainterPath()             # the feather's vane, tip at the upper right
        vane.moveTo(x0 + s * 0.08, y0 + s * 0.92)
        vane.cubicTo(x0 + s * 0.10, y0 + s * 0.40, x0 + s * 0.50, y0 + s * 0.05, x0 + s * 0.96, y0 + s * 0.04)
        vane.cubicTo(x0 + s * 0.92, y0 + s * 0.50, x0 + s * 0.60, y0 + s * 0.88, x0 + s * 0.08, y0 + s * 0.92)
        colour = QtGui.QColor("#d22b2b") if red else QtGui.QColor("#6fa8dc")
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 220), max(1.0, size / 16.0)))
        p.setBrush(colour)
        p.drawPath(vane)
        pen = QtGui.QPen(QtGui.QColor("#24425f") if not red else QtGui.QColor("#6b0d0d"), max(0.8, size / 20.0))
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(x0 + s * 0.02, y0 + s * 0.98), QtCore.QPointF(x0 + s * 0.80, y0 + s * 0.20))
        p.end()
        icon.addPixmap(pm)
    _ICONS[key] = icon
    return icon


def _compose(base, key, paint):
    if not isinstance(base, QtGui.QIcon) or base.isNull():
        return base
    key = (base.cacheKey(), key)
    if key in _ICONS:
        return _ICONS[key]
    icon = QtGui.QIcon()
    for size in (16, 24, 32):
        src = base.pixmap(size, size)
        if src.isNull():
            continue
        pm = QtGui.QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        paint(p, src, size)
        p.end()
        icon.addPixmap(pm)
    _ICONS[key] = icon
    return icon


def envelope_icon(base):
    ""
    def paint(p, src, size):
        p.setOpacity(0.5)
        p.drawPixmap(QtCore.QRect(0, 0, size, size), src)
        p.setOpacity(1.0)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceAtop)
        p.fillRect(QtCore.QRect(0, 0, size, size), QtGui.QColor(115, 166, 255, 150))
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        pen = QtGui.QPen(QtGui.QColor("#3d7be0"), max(1.0, size / 16.0), Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QtCore.QRectF(0.5, 0.5, size - 1, size - 1))
    return _compose(base, "envelope", paint)


def speedpak_icon(base, stale=False):
    """A SpeedPak component's icon: the SpeedPak mark (a small box with a bolt) at its lower right;
    red while the SpeedPak is out of date."""
    def paint(p, src, size):
        p.drawPixmap(QtCore.QRect(0, 0, size, size), src)
        r = size * 0.55
        box = QtCore.QRectF(size - r, size - r, r - 0.5, r - 0.5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 230), max(1.0, size / 16.0)))
        p.setBrush(QtGui.QColor("#d22b2b") if stale else QtGui.QColor("#1f6fd1"))
        p.drawRoundedRect(box, r * 0.18, r * 0.18)
        bolt = QtGui.QPolygonF([QtCore.QPointF(box.left() + r * 0.58, box.top() + r * 0.12),
                                QtCore.QPointF(box.left() + r * 0.28, box.top() + r * 0.55),
                                QtCore.QPointF(box.left() + r * 0.50, box.top() + r * 0.55),
                                QtCore.QPointF(box.left() + r * 0.40, box.top() + r * 0.90),
                                QtCore.QPointF(box.left() + r * 0.74, box.top() + r * 0.42),
                                QtCore.QPointF(box.left() + r * 0.52, box.top() + r * 0.42)])
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffd34d"))
        p.drawPolygon(bolt)
    return _compose(base, ("speedpak", stale), paint)


def marks_of(obj):
    """[(mark, tip)] for a component row: envelope, speedpak / speedpak-stale, lightweight /
    outofdate."""
    out = []
    if obj is None:
        return out
    try:
        from . import asminsert, asmspeedpak
        if asminsert.is_envelope(obj):
            out.append(("envelope", "Envelope"))
        if asmspeedpak.is_speedpak(getattr(obj, "LinkedObject", None)):
            stale = False
            try:
                target = obj.LinkedObject
                stale = getattr(target, asmspeedpak.STAMP_PROP, "") != _sp_stamp(asmspeedpak, target)
            except Exception as _fw_err:
                _fw_log("asmlight.py:433", _fw_err)
            out.append(("speedpak-stale", "SpeedPak (out of date)") if stale else ("speedpak", "SpeedPak"))
    except ReferenceError:
        return []
    except Exception as _fw_err:
        _fw_log("asmlight.py:438", _fw_err)
    m = mark_of(obj)
    if m:
        out.append((m, "Lightweight (out of date)" if m == "outofdate" else "Lightweight"))
    return out


_SP_STAMPS = {}


def _sp_stamp(sp, target):
    """The SpeedPak's part stamp, worked out at most every 2 s per SpeedPak (the tree paints often)."""
    import time
    now = time.monotonic()
    key = (target.Document.Name, target.Name)
    hit = _SP_STAMPS.get(key)
    if hit is None or now - hit[0] > 2.0:
        hit = (now, sp.stamp(sp.own(target)))
        _SP_STAMPS[key] = hit
    return hit[1]


def decorate(icon, marks):
    for m, _tip in marks:
        if m == "envelope":
            icon = envelope_icon(icon)
        elif m.startswith("speedpak"):
            icon = speedpak_icon(icon, stale=(m == "speedpak-stale"))
        elif m in ("lightweight", "outofdate"):
            icon = feather_icon(icon, red=(m == "outofdate"))
    return icon


def mark_of(obj):
    """None, "lightweight" or "outofdate" for a tree row's object."""
    try:
        if obj is None or not is_lightweight(obj):
            return None
        if check_out_of_date() == "Indicate" and out_of_date(obj):
            return "outofdate"
        return "lightweight"
    except ReferenceError:
        return None


def _patch_tree():
    from . import fmtree
    if getattr(fmtree.Model, "_fw_light", False):
        return
    data0 = fmtree.Model.data

    def data(self, index, role=Qt.DisplayRole):
        value = data0(self, index, role)
        if role not in (Qt.DecorationRole, Qt.ToolTipRole) or not index.isValid():
            return value
        try:
            node = self.node(index)
            obj = getattr(node, "obj", None) if node is not None and node is not self.part else None
            if obj is None or getattr(obj, "TypeId", "") not in ("App::Link", "Assembly::AssemblyLink"):
                return value
            marks = marks_of(obj)
            if not marks:
                return value
            if role == Qt.ToolTipRole:
                text = ", ".join(t for _m, t in marks)
                return "%s\n%s" % (value, text) if value else text
            if isinstance(value, QtGui.QIcon):
                return decorate(value, marks)
        except (RuntimeError, ReferenceError):
            pass                    # a row of an object deleted while the tree repaints (document closing)
        except Exception as error:
            if "deleted object" not in str(error):
                App.Console.PrintLog("FreeCAD: lightweight icon: %s\n" % error)
        return value

    fmtree.Model.data = _qt_safe(data)
    fmtree.Model._fw_light = True


# ---------------------------------------------------------------- menus and Edit Part
def top_items(asm):
    return [("LightweightToResolved", "Set Lightweight to Resolved", lambda: set_all(asm, False),
             bool(lightweight_components(asm))),
            ("ResolvedToLightweight", "Set Resolved to Lightweight", lambda: set_all(asm, True),
             bool(resolved_components(asm)))]


def _patch_menus():
    from . import asmmenu
    if getattr(asmmenu, "_fw_light", False):
        return
    entries0 = asmmenu.menu_entries

    def menu_entries(original, shell, target, view):
        items = entries0(original, shell, target, view)
        try:
            if asmmenu.kind(target) == "assembly":
                asm = ac.assembly_of(target.Document)
                if asm is not None:
                    items = list(items)
                    at = next((i + 1 for i, it in enumerate(items) if it[0] is None and it[1]), 0)
                    items[at:at] = top_items(asm) + [("-", None, None, False)]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: lightweight menu: %s\n" % error)
        return items

    asmmenu.menu_entries = menu_entries
    asmmenu._fw_light = True


def _patch_edit():
    from . import asmtools
    if getattr(asmtools, "_fw_light", False):
        return
    edit0 = asmtools.edit_component

    def edit_component(asm, comp, *more, **named):
        if not ensure_resolved([comp], "Edit Part"):
            return None
        return edit0(asm, comp, *more, **named)

    asmtools.edit_component = edit_component
    asmtools._fw_light = True


def _patch_lightweight_stamp():
    """Set to Lightweight from anywhere keeps the part file's time with the component."""
    from . import asmcomp
    if getattr(asmcomp, "_fw_light", False):
        return
    set0 = asmcomp.set_lightweight

    def set_lightweight_(comp, on=True):
        done = set0(comp, on)
        if on:
            try:
                stamp(comp)
            except Exception as _fw_err:
                _fw_log("asmlight.py:576", _fw_err)
        return done

    asmcomp.set_lightweight = set_lightweight_
    asmcomp._fw_light = True


def _patch_open():
    from . import asmldr
    if getattr(asmldr, "_fw_light", False):
        return
    apply0 = asmldr.apply_mode

    def apply_mode(doc, mode):
        done = apply0(doc, mode)
        try:
            after_open(doc, mode)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Performance on open: %s\n" % error)
        return done

    asmldr.apply_mode = apply_mode
    asmldr._fw_light = True


# ---------------------------------------------------------------- Options > Performance
def performance_rows():
    from .optionspages import BoolFn, Combo
    return ("Assemblies", [
        BoolFn(AUTO_LIGHT, "Automatically load components lightweight", auto_lightweight,
               lambda v: _p().SetBool(AUTO_LIGHT, bool(v)), "An opened assembly's components load lightweight"),
        BoolFn(RESOLVE_SUBS, "Always resolve sub-assemblies", always_resolve_subs,
               lambda v: _p().SetBool(RESOLVE_SUBS, bool(v)), "Sub-assemblies stay resolved when their parts load lightweight"),
        Combo(CHECK_OOD, "Check out-of-date lightweight components:", [(c, c) for c in CHECK_CHOICES],
              check_out_of_date, lambda v: _p().SetString(CHECK_OOD, v),
              "Indicate: a red feather on the component; Always Resolve: resolved on open"),
        Combo(RESOLVE_MODE, "Resolve lightweight components:", [(c, c) for c in RESOLVE_CHOICES],
              resolve_mode, lambda v: _p().SetString(RESOLVE_MODE, v),
              "An operation that needs the whole component asks first, or just resolves it"),
        BoolFn(RESOLVE_ON_EXPAND, "Resolve lightweight components when expanded in the FeatureManager design tree",
               resolve_on_expand, lambda v: _p().SetBool(RESOLVE_ON_EXPAND, bool(v)),
               "Off: expanding a lightweight component's row lists it without resolving it (large assemblies stay quick)"),
        BoolFn("SmartSavePrompts", "Mark assembly as modified when cosmetic changes are made to referenced documents",
               mark_cosmetic, set_mark_cosmetic,
               "Off: hiding, showing or recolouring components doesn't ask to save the assembly"),
        Combo(REBUILD_ON_LOAD, "Rebuild assembly on load:", [(c, c) for c in REBUILD_CHOICES],
              rebuild_on_load, lambda v: _p().SetString(REBUILD_ON_LOAD, v),
              "An assembly that needs a rebuild when it opens"),
    ])


def _patch_options():
    from . import optionspages
    if getattr(optionspages, "_fw_asm_perf", False):
        return
    perf0 = optionspages._performance

    def _performance():
        sections = perf0()
        try:
            group = performance_rows()
            at = next((i for i, s in enumerate(sections) if s[0] == "Save"), len(sections))
            sections.insert(at, group)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Performance assemblies rows: %s\n" % error)
        return sections

    optionspages._performance = _performance
    optionspages._fw_asm_perf = True


def install():
    for fn in (_patch_lightweight_stamp, _patch_tree, _patch_menus, _patch_edit, _patch_open, _patch_options):
        try:
            fn()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: lightweight (%s): %s\n" % (fn.__name__, error))
