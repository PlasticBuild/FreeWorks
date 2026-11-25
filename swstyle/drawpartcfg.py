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

KIND = "FwPartConfigShape"
IN_USE = "Use model's \"in-use\" or last saved configuration"
NAMED = "Use named configuration:"
_BUSY = [False]


# --------------------------------------------------------------------------- the part's configurations

def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def _table(doc):
    try:
        from . import configmanager
        return configmanager.table(doc)
    except Exception as _fw_err:
        _fw_log("drawpartcfg.py:51", _fw_err)
        return None


def is_assembly(doc):
    return doc is not None and any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects)


def configurations(doc):
    """([names], active) of a part document's configurations; ([], None) without a configuration table (and for
    assemblies, which asmdrawing handles)."""
    if doc is None or is_assembly(doc):
        return [], None
    t = _table(doc)
    if t is None:
        return [], None
    names = t.names()
    return names, (t.active() if names else None)


def _model_shapes(doc):
    from . import drawings as D
    return [o for o in D.model_shapes(doc) if getattr(o, "TypeId", "") != "Spreadsheet::Sheet"]


def config_shape(doc, name):
    """The part's shape as configuration name shows it (a copy), or None."""
    import Part
    t = _table(doc)
    if t is None or name not in t.names():
        return None
    active = t.active()
    _BUSY[0] = True
    try:
        if name != active:
            setattr(t.sheet, t.prop, name)
            doc.recompute()
        shapes = []
        for o in _model_shapes(doc):
            try:
                if not o.Shape.isNull():
                    shapes.append(o.Shape.copy())
            except Exception as _fw_err:
                _fw_log("drawpartcfg.py:92", _fw_err)
        return Part.makeCompound(shapes) if shapes else None
    finally:
        if name != active:
            try:
                setattr(t.sheet, t.prop, active)
                doc.recompute()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: configuration back to %s: %s\n" % (active, error))
        _BUSY[0] = False


# --------------------------------------------------------------------------- the configuration shapes
def is_config_shape(o):
    return o is not None and getattr(o, "SWKind", "") == KIND


def part_of(o):
    """The part document a configuration shape was read from (open), else None."""
    name, path = getattr(o, "SWPartDoc", ""), getattr(o, "SWPartFile", "")
    import os
    for d in App.listDocuments().values():
        try:
            if d.Name == name or (path and d.FileName and os.path.normcase(d.FileName) == os.path.normcase(path)):
                return d
        except Exception as _fw_err:
            _fw_log("drawpartcfg.py:118", _fw_err)
    return None


def shape_holder(drawing, doc, name):
    """The drawing's configuration shape of doc's configuration name (made, or read again)."""
    for o in drawing.Objects:
        if is_config_shape(o) and o.SWPartDoc == doc.Name and o.SWConfiguration == name:
            refresh(o)
            return o
    sh = config_shape(doc, name)
    if sh is None:
        return None
    o = drawing.addObject("Part::Feature", "ConfigShape")
    o.Label = "%s (%s)" % (doc.Label, name)
    for prop, val in (("SWKind", KIND), ("SWPartDoc", doc.Name), ("SWPartFile", doc.FileName or ""),
                      ("SWConfiguration", name)):
        o.addProperty("App::PropertyString", prop, "FreeCAD", "the part configuration this shape shows")
        setattr(o, prop, val)
    o.Shape = sh
    try:
        o.ViewObject.Visibility = False
        o.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("drawpartcfg.py:142", _fw_err)
    return o


def refresh(o):
    doc = part_of(o)
    if doc is None:
        return False
    sh = config_shape(doc, o.SWConfiguration)
    if sh is None:
        return False
    o.Shape = sh
    return True


def _raw(v):
    return _fw_xs(v) + list(getattr(v, "Source", []) or [])


def view_shape(v):
    for o in _raw(v):
        if is_config_shape(o):
            return o
    return None


def view_configuration(v):
    """(part document, configuration name or "" for in-use) of a part view."""
    o = view_shape(v)
    if o is not None:
        return part_of(o), o.SWConfiguration
    from . import drawviews as DV
    for s in DV.source_shapes(v):
        try:
            if configurations(s.Document)[0]:
                return s.Document, ""
        except Exception as _fw_err:
            _fw_log("drawpartcfg.py:179", _fw_err)
    return None, ""


def _children(v):
    ""
    try:
        from . import drawselect as DS
    except Exception:
        return []
    out = []
    for w in v.Document.Objects:
        if w is v or not w.isDerivedFrom("TechDraw::DrawViewPart"):
            continue
        try:
            if DS.parent_of(w) is v or getattr(w, "BaseView", None) is v:
                out.append(w)
        except Exception as _fw_err:
            _fw_log("drawpartcfg.py:197", _fw_err)
    return out


def _set_view(v, doc, holder, name):
    from . import drawings as D
    if holder is not None:
        v.Source = []
        v.XSource = [holder]
    else:
        v.Source = []
        D.link_source(v, _model_shapes(doc))
    if "SWConfiguration" not in v.PropertiesList:
        v.addProperty("App::PropertyString", "SWConfiguration", "FreeCAD", "Drawing View option")
    v.SWConfiguration = name


def apply_view(v, name):
    """The view (and the views made from it) shows the part in configuration name ("" or the active one: the
    part as it is)."""
    doc, _cur = view_configuration(v)
    if doc is None:
        return False
    names, active = configurations(doc)
    drawing = v.Document
    holder = None
    if name and name != active and name in names:
        holder = shape_holder(drawing, doc, name)
        if holder is None:
            return False
    else:
        name = active or ""
    olds = set()
    todo, seen = [v], set()
    while todo:
        w = todo.pop(0)
        if w.Name in seen:
            continue
        seen.add(w.Name)
        old = view_shape(w)
        if old is not None:
            olds.add(old.Name)
        _set_view(w, doc, holder, name)
        todo += _children(w)
    for n in olds:                         # a configuration shape no view shows any more goes
        o = drawing.getObject(n)
        if o is not None and not any(o in _raw(w) for w in drawing.Objects if w.isDerivedFrom("TechDraw::DrawView")):
            drawing.removeObject(n)
    drawing.recompute()
    return True


def _fill(combo, doc, current=""):
    names, active = configurations(doc)
    if not names:
        return False
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(names)
    combo.setCurrentText(current or active)
    combo.blockSignals(False)
    return True


# --------------------------------------------------------------------------- the drawing code asks for the part
class _Mapped(list):
    """source_shapes' answer for a configuration view: the part's bodies; .raw what the view draws."""
    raw = ()


def _patch_drawviews():
    from . import drawings as D
    from . import drawviews as DV
    if getattr(DV, "_fw_partcfg", False):
        return
    DV._fw_partcfg = True
    src0, centre0, link0 = DV.source_shapes, DV.model_centre, D.link_source

    def source_shapes(v):
        got = src0(v)
        if not any(is_config_shape(o) for o in got):
            return got
        out = _Mapped()
        for o in got:
            doc = part_of(o) if is_config_shape(o) else None
            out += _model_shapes(doc) if doc is not None else [o]
        out.raw = list(got)
        return out

    def model_centre(v):
        o = view_shape(v)
        if o is None:
            return centre0(v)
        return o.Shape.BoundBox.Center

    def link_source(view, shapes):
        if isinstance(shapes, _Mapped):      # a view made from a configuration view shows the same configuration
            shapes = shapes.raw
        return link0(view, shapes)

    DV.source_shapes, DV.model_centre, D.link_source = source_shapes, model_centre, link_source


def _patch_model_view():
    from . import drawings as D
    cls = D.ModelViewPanel
    if getattr(cls, "_fw_partcfg", False):
        return
    cls._fw_partcfg = True
    go0, place0 = cls.go_page, cls._place

    def go_page(self, n):
        go0(self, n)
        if n == 2 and self.source() is not None and not is_assembly(self.source()):
            _fill(self.config, self.source())

    def _place(self, p):
        src = self.source()
        names, active = configurations(src) if src is not None else ([], None)
        want = self.config.currentText() if names else ""
        if not names or not want or want == active or want not in names:
            return place0(self, p)
        holder = shape_holder(self.doc, src, want)
        if holder is None:
            return place0(self, p)
        ms0 = D.model_shapes
        name = src.Name
        D.model_shapes = lambda doc: [holder] if getattr(doc, "Name", None) == name else ms0(doc)
        try:
            return place0(self, p)
        finally:
            D.model_shapes = ms0

    cls.go_page, cls._place = go_page, _place


def _patch_view_pm():
    from . import drawselect as DS
    cls = DS.DrawingViewPanel
    if getattr(cls, "_fw_partcfg", False):
        return
    cls._fw_partcfg = True
    build0 = cls.build

    def build(self):
        build0(self)
        v = self.view
        doc, cur = view_configuration(v)
        if doc is None or is_assembly(doc) or not _fill(self.config, doc, cur):
            return
        linked = DS.parent_of(v) is not None or v.TypeId in (
            "TechDraw::DrawViewSection", "TechDraw::DrawViewDetail", "TechDraw::DrawComplexSection")
        if linked:
            self.config.setItemText(self.config.currentIndex(), self.config.currentText() + " <Link to parent>")
            self.config.setEnabled(False)
            return
        self.config.currentIndexChanged.connect(
            lambda *_: self.change(lambda: apply_view(self.view, self.config.currentText())))

    cls.build = build


# --------------------------------------------------------------------------- the part rebuilt: its shapes again
class _Observer:
    def slotRecomputedDocument(self, doc):
        if _BUSY[0]:
            return
        try:
            if not configurations(doc)[0]:
                return
            for d in App.listDocuments().values():
                for o in d.Objects:
                    if is_config_shape(o) and part_of(o) is doc:
                        QtCore.QTimer.singleShot(0, lambda o=o: _later(o))
        except Exception as _fw_err:
            _fw_log("drawpartcfg.py:372", _fw_err)


def _later(o):
    try:
        if o.Document is not None and refresh(o):
            o.Document.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: configuration shape: %s\n" % error)


_OBS = []


def install():
    for fn in (_patch_drawviews, _patch_model_view, _patch_view_pm):
        try:
            fn()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: part configurations in drawings: %s\n" % error)
    if not _OBS:
        _OBS.append(_Observer())
        App.addDocumentObserver(_OBS[0])
