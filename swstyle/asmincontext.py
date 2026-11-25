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

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

from . import asmcore as ac


def _context():
    """(assembly, component being edited, its body) or None."""
    try:
        from . import asmtools
        ed = asmtools.editing()
    except Exception as _fw_err:
        _fw_log("asmincontext.py:39", _fw_err)
        return None
    if not ed:
        return None
    asm, comp = ed[0], ed[1]
    try:
        body = comp.getLinkedObject(True)
    except Exception as _fw_err:
        _fw_log("asmincontext.py:47", _fw_err)
        return None
    if body is None or body.TypeId != "PartDesign::Body":
        return None
    return asm, comp, body


def _component_of(asm, obj, sub=""):
    """The component of asm that obj (and the sub path under it) names, or None."""
    comps = ac.components(asm)
    if obj in comps:
        return obj
    for part in (sub or "").split(".")[:-1]:
        found = asm.Document.getObject(part)
        if found in comps:
            return found
    return None


def solid_reference(asm, body, comp):
    """A reference in body to the whole of comp's part, where the assembly has comp (kept)."""
    from . import asmextref, asmrefopts
    for o in body.Group:
        if o.TypeId == "PartDesign::SubShapeBinder" and getattr(o, "FwRefComp", "") == comp.Name \
                and getattr(o, "FwWhole", False):
            return o
    target = comp.getLinkedObject(True)
    binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
    binder.Support = [(target, [""])]
    binder.Relative = False
    binder.Label = "Reference (%s)" % comp.Label
    for prop, typ in (("FwInContext", "App::PropertyBool"), ("FwRefComp", "App::PropertyString"),
                      ("FwWhole", "App::PropertyBool"), ("FwRefLabel", "App::PropertyString")):
        binder.addProperty(typ, prop, "FreeCAD", "In-context reference")
        binder.setEditorMode(prop, 2)
    binder.FwInContext, binder.FwRefComp, binder.FwWhole, binder.FwRefLabel = True, comp.Name, True, comp.Label
    asmextref._remember_context(binder, asm)
    if binder.ViewObject is not None:
        binder.ViewObject.Visibility = False
    if not asmrefopts.on(asmrefopts.ALLOW_EXTERNAL):
        binder.addProperty("App::PropertyBool", "FwNoReference", "FreeCAD", "A copy, not an external reference")
        binder.FwNoReference = True
    body.Document.recompute()
    asmextref.follow_binders(asm)
    body.Document.recompute()
    if getattr(binder, "FwNoReference", False):
        binder.BindMode = "Detached"
    return binder


def map_pick(obj, sub=""):
    """A whole-object pick made in the assembly while a part is edited there: the part's own
    reference to that component, or obj itself when nothing needs mapping."""
    ctx = _context()
    if ctx is None:
        return obj
    asm, comp, body = ctx
    other = _component_of(asm, obj, sub)
    if other is None or other is comp:
        return obj
    return solid_reference(asm, body, other)


def open_edit(asm, comp, obj):
    """The feature's PM, opened through the component while the part is edited in the assembly."""
    Gui.Selection.clearSelection()
    try:
        Gui.getDocument(asm.Document.Name).setEdit(asm, 0, "%s.%s." % (comp.Name, obj.Name))
        if Gui.Control.activeDialog():
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context edit: %s\n" % error)
    try:
        Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: in-context edit: %s\n" % error)
        from . import fwtell
        fwtell.tell("Could not open the feature for editing in the assembly.", error)
        return False


def install():
    from . import simplefeature as sf
    if getattr(sf, "_fw_incontext", False):
        return
    sf._fw_incontext = True
    pre0 = sf.preselected

    def preselected(spec):
        out = pre0(spec)
        if _context() is None or Gui is None:
            return out
        first = spec.first_pick or next((f.name for f in spec.fields if f.kind == "pick"), None)
        field = next((f for f in spec.fields if f.name == first), None)
        if field is None or field.what not in sf.WHOLE:
            return out
        picks = []
        for sel in Gui.Selection.getSelectionEx("", 0):
            for sub in sel.SubElementNames or [""]:
                mapped = map_pick(sel.Object, sub)
                if mapped is not sel.Object and mapped not in picks:
                    picks.append(mapped)
        if picks:
            out = dict(out or {})
            out[first] = picks if field.many else picks[0]
        return out
    sf.preselected = preselected

    make0 = sf.make

    def make(spec, doc=None, picks=None, edit=True, **values):
        ctx = _context()
        if ctx is None or not edit or not App.GuiUp:
            return make0(spec, doc, picks, edit, **values)
        asm, comp, body = ctx
        obj = make0(spec, body.Document, picks, False, **values)
        if obj is not None:
            open_edit(asm, comp, obj)
        return obj
    sf.make = make

    dbl0 = sf.View.doubleClicked

    def doubleClicked(self, vobj):
        ctx = _context()
        obj = vobj.Object
        if ctx is not None and obj.Document is ctx[2].Document and obj.Document is not App.ActiveDocument:
            return open_edit(ctx[0], ctx[1], obj)
        return dbl0(self, vobj)
    sf.View.doubleClicked = doubleClicked

    P = sf.Panel
    add0 = P.addSelection

    def addSelection(self, doc, name, sub, point):
        ctx = _context()
        try:
            own = self._alive()
        except Exception:
            own = None
        if ctx is None or own is None or doc == own or self.active is None or doc != ctx[0].Document.Name:
            return add0(self, doc, name, sub, point)
        field = next((f for f in self.spec.fields if f.name == self.active), None)
        if field is None or field.what not in sf.WHOLE:
            return add0(self, doc, name, sub, point)
        top = App.getDocument(doc).getObject(name)
        mapped = map_pick(top, sub)
        if mapped is top:
            return add0(self, doc, name, sub, point)

        def take(binder=mapped, field=field):
            if self._alive() is None:
                return
            Gui.Selection.clearSelection()
            current = getattr(self.obj, field.name)
            if field.many:
                items = list(current or [])
                items = [i for i in items if i != binder] if binder in items else items + [binder]
                setattr(self.obj, field.name, items)
            else:
                setattr(self.obj, field.name, None if current == binder else binder)
            try:
                self._changed()
            except Exception:
                self.obj.Document.recompute()
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, take)
    P.addSelection = addSelection
