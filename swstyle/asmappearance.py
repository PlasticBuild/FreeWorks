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
from PySide import QtCore, QtGui, QtWidgets

from . import asmcore as ac

PROP = "FwAppearance"
LAST = {}


def _ap():
    from . import appearance
    return appearance


# ---------------------------------------------------------------- the component level
class ComponentTarget:
    """appearance.Target's shape for one component of an assembly (component level)."""
    level = "component"

    def __init__(self, comp):
        self.comp = comp
        self.body, self.obj, self.sub = comp, None, ""

    def key(self):
        return "component:" + self.comp.Name

    def name(self):
        return self.comp.Label

    def bodies(self):
        return []

    def same(self, other):
        return isinstance(other, ComponentTarget) and other.comp == self.comp


def own(comp):
    """The component's own appearance (r, g, b, t[, light...]) or None."""
    text = getattr(comp, PROP, "") or ""
    return _ap().decode(text, True) if text else None


def _source_colour(comp):
    try:
        src = comp.LinkedObject
        body = _ap().body_of(src) or src
        bs = _ap().bodies(body.Document)
        if bs:
            return tuple(_ap().current_colour(_ap().Target("part", bs[0]), True))
        vo = src.ViewObject
        return tuple((vo.ShapeColor or (0.8, 0.8, 0.8))[:3]) + (vo.Transparency / 100.0,)
    except Exception:
        return (0.8, 0.8, 0.8, 0.0)


def colour_of(comp):
    return own(comp) or _source_colour(comp)


def paint(comp):
    """Puts the component's own appearance on the screen (or takes it off)."""
    vo = comp.ViewObject
    if vo is None:
        return
    look = own(comp)
    try:
        from . import asmmenu
        see_through = asmmenu.transparent(comp)
    except Exception:
        see_through = False
    if look is None:
        if not see_through:
            vo.OverrideMaterial = False
        return
    m = App.Material()
    m.DiffuseColor = tuple(look[:3])
    t = look[3] if len(look) > 3 else 0.0
    if see_through:
        try:
            from . import asmmenu
            t = max(t, asmmenu.TRANSPARENCY)
        except Exception as _fw_err:
            _fw_log("asmappearance.py:109", _fw_err)
    m.Transparency = t
    vo.ShapeMaterial = m
    vo.OverrideMaterial = True


def set_colour(comp, rgbt):
    if PROP not in comp.PropertiesList:
        comp.addProperty("App::PropertyString", PROP, "FreeCAD", "Component appearance (this assembly only)")
        comp.setPropertyStatus(PROP, "Hidden")
    setattr(comp, PROP, _ap().encode(rgbt))
    paint(comp)


def clear_colour(comp):
    if PROP in comp.PropertiesList and getattr(comp, PROP):
        setattr(comp, PROP, "")
    paint(comp)


def open_component_page(asm, comps):
    ap = _ap()
    targets = [ComponentTarget(c) for c in comps]
    LAST["page"] = targets
    if not targets:

        # component picked or inserted afterwards can be coloured from it
        def show_empty():
            panel = ap.AppearancePanel(asm.Document, "part", [])
            _component_panel(panel, [])
            try:
                panel.list.addItem(asm.Label)
            except Exception as _fw_err:
                _fw_log("asmappearance.py:142", _fw_err)
            Gui.Control.showDialog(panel)
            LAST["panel"] = panel
        QtCore.QTimer.singleShot(0, show_empty)
        return targets

    def show():
        panel = ap.AppearancePanel(asm.Document, "part", targets)
        _component_panel(panel, targets)
        Gui.Control.showDialog(panel)
        LAST["panel"] = panel
    QtCore.QTimer.singleShot(0, show)
    return targets


def _component_panel(panel, targets):
    """The PM on the component level: the level buttons stand for the part's levels, so they
    are off; the list names the components; Cancel puts their looks back."""
    before = {t.comp.Name: getattr(t.comp, PROP, "") or "" for t in targets}
    for b in getattr(panel, "level_buttons", {}).values():
        b.setChecked(False)
        b.setEnabled(False)
    try:
        panel.list.clear()
        for t in targets:
            panel.list.addItem(t.name())
        panel.remove_button.setEnabled(any(own(t.comp) is not None for t in targets))
    except Exception as _fw_err:
        _fw_log("asmappearance.py:170", _fw_err)
    panel._show = lambda: None
    panel.addSelection = lambda *a: None
    reject0 = panel.reject

    def reject():
        ok = reject0()
        for t in targets:
            try:
                if PROP in t.comp.PropertiesList:
                    setattr(t.comp, PROP, before.get(t.comp.Name, ""))
                paint(t.comp)
            except Exception as _fw_err:
                _fw_log("asmappearance.py:183", _fw_err)
        return ok
    panel.reject = reject


# ---------------------------------------------------------------- appearance.py hooks
def _patch():
    ap = _ap()
    if getattr(ap, "_fw_asm", False):
        return
    apply0, remove0, colour0, activated0 = ap.apply, ap.remove, ap.current_colour, ap.AppearanceCommand.Activated

    def apply(targets, rgbt):
        mine = [t for t in targets if isinstance(t, ComponentTarget)]
        for t in mine:
            set_colour(t.comp, rgbt)
        rest = [t for t in targets if not isinstance(t, ComponentTarget)]
        return apply0(rest, rgbt) if rest else None

    def remove(targets):
        for t in targets:
            if isinstance(t, ComponentTarget):
                clear_colour(t.comp)
        rest = [t for t in targets if not isinstance(t, ComponentTarget)]
        return remove0(rest) if rest else None

    def current_colour(target, full=False):
        if isinstance(target, ComponentTarget):
            look = colour_of(target.comp)
            return tuple(look) if full else tuple(look[:4])
        return colour0(target, full)

    def activated(self):
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is not None and not ap.bodies(asm.Document):
            edit_appearance(asm)
            return
        return activated0(self)

    ap.apply, ap.remove, ap.current_colour = apply, remove, current_colour
    ap.AppearanceCommand.Activated = activated
    ap._fw_asm = True


# ---------------------------------------------------------------- picks and the drop-down
def picks(asm):
    """[(component, part object or None, element)] for what is picked in the assembly."""
    comps = list(ac.components(asm))
    out = []
    for entry in Gui.Selection.getSelectionEx(asm.Document.Name, 0):
        obj = entry.Object
        for sub in (entry.SubElementNames or ("",)):
            if obj in comps and not sub:
                out.append((obj, None, ""))
                continue
            try:
                ref = ac.reference(asm, obj, sub) if sub else None
            except Exception:
                ref = None
            if ref is None:
                if obj in comps:
                    out.append((obj, None, ""))
                continue
            comp, inner = ref
            if comp not in comps:
                continue
            src = getattr(comp, "LinkedObject", None)
            part_obj, leaf = src, ""
            if inner:
                path = inner.split(".")
                leaf = path[-1]
                src_doc = getattr(src, "Document", None)
                for name in reversed(path[:-1]):       # the deepest part object named in the path
                    o = src_doc.getObject(name) if src_doc is not None and name else None
                    if o is not None:
                        part_obj = o
                        break
            if part_obj is not None and part_obj.TypeId == "PartDesign::Body" and leaf.startswith("Face"):
                found = _maker(part_obj, leaf)                       # the feature that made the face
                if found is not None:
                    part_obj, leaf = found
            out.append((comp, part_obj, leaf))
    return out


def _maker(body, face_name):
    """(feature, its face name) for the first feature of the body whose shape has the face."""
    import Part
    try:
        face = body.Shape.getElement(face_name)
        probe = Part.Vertex(face.CenterOfMass)
    except Exception:
        return None
    for feat in getattr(body, "Group", []):
        if not _ap()._solid_feature(feat):
            continue
        try:
            for i, f in enumerate(feat.Shape.Faces):
                if type(f.Surface) is type(face.Surface) and abs(f.Area - face.Area) < 1e-6 * max(1.0, face.Area) \
                        and f.distToShape(probe)[0] < 1e-6:
                    return feat, "Face%d" % (i + 1)
        except Exception:
            continue
    return None


def menu_for(asm, comp, part_obj=None, sub=""):
    ""

    ap = _ap()
    menu = None
    if part_obj is None:
        src = getattr(comp, "LinkedObject", None)
        part_obj = ap.body_of(src) or src
        sub = ""
    try:
        has_level = part_obj is not None and (ap.body_of(part_obj) is not None or ap.target_for("part", part_obj, sub))
    except Exception:
        has_level = False
    if has_level:
        try:
            menu = ap.menu_for(part_obj.Document, [(part_obj, sub)])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component appearance menu: %s\n" % error)
            menu = None
    if menu is None:
        menu = QtWidgets.QMenu(Gui.getMainWindow())
        menu.setObjectName("SWAppearanceMenu")
    # Component (<name>) goes after the part's rows, before Remove Appearance
    before = None
    for a in menu.actions():
        if a.isSeparator():
            before = a
            break
    act = QtGui.QAction(ap._swatch(colour_of(comp)[:4]), "Component (%s)" % comp.Label, menu)
    act.setObjectName("SWAppearance_component")
    act.triggered.connect(lambda _c=False: open_component_page(asm, [comp]))
    if before is not None:
        menu.insertAction(before, act)
    else:
        menu.addAction(act)
    flyout = menu.findChild(QtWidgets.QMenu, "SWAppearanceRemove")
    if flyout is None:
        menu.addSeparator()
        flyout = menu.addMenu("Remove Appearance")
        flyout.setObjectName("SWAppearanceRemove")
    if own(comp) is not None:
        rm = flyout.addAction(ap._swatch(own(comp)[:4]), "Component (%s)" % comp.Label)
        rm.setObjectName("SWAppearanceRemove_component")
        rm.triggered.connect(lambda _c=False: _remove_with_undo(asm, comp))
        flyout.setEnabled(True)
    LAST["menu"] = menu
    return menu


def _remove_with_undo(asm, comp):
    doc = asm.Document
    doc.openTransaction("Remove Appearance")
    try:
        clear_colour(comp)
    finally:
        doc.commitTransaction()


def edit_appearance(asm, comp=None, popup=True):
    """Edit Appearance in an assembly: the drop-down for the pick, or the component page for
    every component with nothing picked."""
    found = picks(asm)
    if comp is not None:
        found = [p for p in found if p[0] == comp] or [(comp, None, "")]
    if not found:
        return open_component_page(asm, list(ac.components(asm)))
    c, obj, sub = found[0]
    menu = menu_for(asm, c, obj, sub)
    if popup:
        menu.popup(QtGui.QCursor.pos())
    return menu


def after_restore(doc):
    """Saved component appearances come back on open."""
    try:
        asm = ac.assembly_of(doc)
        for c in (ac.components(asm) if asm is not None else []):
            if getattr(c, PROP, ""):
                paint(c)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: component appearance: %s\n" % error)


class _Restore:
    def slotFinishRestoreDocument(self, doc):
        QtCore.QTimer.singleShot(0, lambda: after_restore(doc))

    def slotCreatedDocument(self, doc):
        # FreeCAD 1.1 never calls slotFinishRestoreDocument on Python observers
        try:
            from . import asmgen
            asmgen.after_load(doc.Name, after_restore)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: component appearance: %s\n" % error)


_OBS = []


def install():
    _patch()
    if not _OBS:
        o = _Restore()
        App.addDocumentObserver(o)
        _OBS.append(o)
