# SPDX-License-Identifier: LGPL-2.1-or-later
""




import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui


def _name(d):
    if d.prop is not None:
        from . import featuredimshow as fds
        own = [x for x in fds.SHOWN.dims if x.prop is not None and x.obj is d.obj] or [d]
        n = next((i for i, x in enumerate(own) if x.prop == d.prop), 0) + 1
        return "D%d@%s" % (n, d.obj.Label)
    try:
        from . import configtable
        sw = next((s for i, s, _n in configtable.dimension_names(d.obj) if i == d.index), None)
    except Exception:
        sw = None
    return "%s@%s" % (sw or "D%d" % (d.index + 1), d.obj.Label)


def _feature(d):
    from . import featuredimshow as fds
    doc = d.obj.Document
    name = fds.SHOWN.feature
    f = doc.getObject(name) if name else None
    return f or d.obj


def _toggle_driven(d):
    sk = d.obj
    doc = sk.Document
    doc.openTransaction("Driven")
    try:
        sk.setDriving(d.index, not sk.Constraints[d.index].Driving)
        doc.recompute()
    finally:
        doc.commitTransaction()
    from . import featuredimshow as fds
    fds.SHOWN.again()


def _value(d):
    try:
        if d.prop is None:
            from . import rcextras
            return rcextras.value_text(d.obj, d.index)
        v = getattr(d.obj, d.prop)
        q = getattr(v, "UserString", None)
        if q:
            return q.split(" ")[0]
        return "%g" % float(v)
    except Exception:
        return ""


def _feature_key(d):
    return "%s.%s" % (d.obj.Name, d.prop)


def _feature_flag_items(d):
    """Mark For Drawing, Display Options > and Select Annotation View for a feature's own dimension
    (an extrude's depth): kept on the feature, as rcextras keeps them on a sketch."""
    from . import rcmenus, rcextras
    obj, key = d.obj, d.prop

    def tx(name, body):
        doc = obj.Document
        doc.openTransaction(name)
        try:
            body()
        finally:
            doc.commitTransaction()

    marks = rcextras._flags(obj, rcmenus.MARK_PROP)
    mark = rcmenus.action("MarkForDrawing", rcmenus.T_MARK_FOR_DRAWING, lambda: tx(
        "Mark For Drawing", lambda: rcextras._set_flags(obj, rcmenus.MARK_PROP,
                                                        [m for m in marks if m != key] if key in marks else marks + [key])),
        checked=key not in marks)
    flags = rcextras._flags(obj, rcextras.DISPLAY_PROP)

    def flip(f):
        k = "%s:%s" % (key, f)
        now = rcextras._flags(obj, rcextras.DISPLAY_PROP)
        tx(dict(rcextras.DISPLAY_FLAGS).get(f, f), lambda: rcextras._set_flags(
            obj, rcextras.DISPLAY_PROP, [x for x in now if x != k] if k in now else now + [k]))
    opts = rcmenus.submenu("DisplayOptions", rcextras.T_DISPLAY_OPTIONS,
                           [rcmenus.action(f, t, lambda f=f: flip(f), checked="%s:%s" % (key, f) in flags)
                            for f, t in rcextras.DISPLAY_FLAGS])

    def view():
        from PySide import QtWidgets
        views = list(rcextras.ANNOTATION_VIEWS)
        choice, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Select Annotation View",
                                                    "Annotation view:", views, 0, False)
        if ok:
            now = [v for v in rcextras._flags(obj, rcextras.VIEW_PROP) if not v.startswith(key + ":")]
            tx("Select Annotation View", lambda: rcextras._set_flags(
                obj, rcextras.VIEW_PROP, now + ([key + ":" + choice] if choice != rcextras.UNASSIGNED else [])))
    return mark, opts, rcmenus.action("SelectAnnotationView", rcextras.T_ANNOT_VIEW, view)


def _annotations(d):
    """Annotations > as read on the part (49a): Note... to Datum Target..., Cosmetic Thread... /
    Insert Block, Format Painter. Placed at the dimension's point."""
    from . import rcmenus, rcextras
    sketch = d.prop is None
    target = d.obj

    def add(kind):
        if sketch:
            return rcextras.add_annotation(d.obj, d.index, kind)
        orig = rcextras._anchor
        rcextras._anchor = lambda _s, _i: App.Vector(*d.point) if d.point is not None else App.Vector()
        try:
            return rcextras.add_annotation(target, None, kind)
        finally:
            rcextras._anchor = orig
    items = [rcmenus.action(key, text, lambda k=key: add(k), icon=rcextras._icon(text.rstrip("."), "ANNOTATIONS_" + key.upper()))
             for key, text, _d in rcextras.ANNOTATIONS]
    items += [rcmenus.entry("CosmeticThread", "Cosmetic Thread..."), rcmenus.separator(),
              rcmenus.entry("InsertBlock", "Insert Block")]
    if sketch:
        items.append(rcmenus.action("FormatPainter", "Format Painter", lambda: rcextras.format_painter(d.obj, d.index),
                                    icon=rcextras._icon("Format Painter", "FORMAT_PAINTER")))
    return rcmenus.submenu("Annotations", rcextras.T_ANNOTATIONS, items)


def _short(item):
    if item is not None:
        item.more = False          # Configure Dimension is in the part's short menu (49a), unlike the sketch's
    return item


def items(d):
    ""





    from . import rcmenus, rcextras, equations, featuredimshow as fds
    obj, path = fds.path_of(d)
    linked = equations.linked_name(obj, path)
    named = "%s(%s)" % (_name(d), _value(d))
    sketch = d.prop is None
    out = []
    if not sketch:
        out.append(rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other))
    try:
        from . import partextras as px
    except Exception:
        px = None
    out += [rcmenus.action("ContourSelect", rcmenus.T_CONTOUR_SELECT, px.contour_select_tool, more=True) if px else None,
            rcmenus.selection_tools_menu(), rcmenus.zoom_menu(), rcextras.set_view_menu(True), rcmenus.recent_menu(),
            rcmenus.header("Dimension (%s)" % named, "HeaderDimension"),
            rcmenus.action("LinkValues", rcextras.T_LINK_VALUES, lambda: fds.link_dialog(d))]
    if linked is not None:
        out.append(rcmenus.action("UnlinkValue", "Unlink Value",
                                  lambda: fds._do(obj.Document, "Unlink Value", lambda: equations.unlink_value(obj, path))))
    if sketch:
        sk, i = d.obj, d.index
        out += [rcmenus.action("ReverseDirection", rcextras.T_REVERSE, lambda: rcextras.reverse_direction(sk, i))
                if rcextras.can_reverse(sk, i) else None,
                rcmenus.action("Driven", rcmenus.T_DRIVEN, lambda: _toggle_driven(d), checked=not d.driving),
                rcmenus.action("MarkForDrawing", rcmenus.T_MARK_FOR_DRAWING,
                               lambda: rcmenus.toggle_mark_for_drawing(sk, i), checked=rcmenus.marked_for_drawing(sk, i)),
                _short(rcmenus._configure_dimension(sk, i)),
                rcextras.display_options_menu(sk, i),
                rcmenus.entry("SmartDimension", "Smart Dimension"),
                _annotations(d),
                rcmenus.header("%s (%s)" % (rcmenus.T_SELECTED, named), "HeaderSelected"),
                rcmenus.action("HideDimension", rcmenus.T_HIDE, fds.SHOWN.hide),
                rcmenus.action("SelectAnnotationView", rcextras.T_ANNOT_VIEW, lambda: rcextras.select_annotation_view(sk, i))]
    else:
        mark, opts, view = _feature_flag_items(d)
        feature = _feature(d)
        try:
            from . import configtable
            conf = rcmenus.action("ConfigureDimension", rcmenus.T_CONFIGURE_DIMENSION,
                                  lambda: configtable.configure_feature(feature))
        except Exception:
            conf = None
        out += [mark, conf, opts, rcmenus.entry("SmartDimension", "Smart Dimension"), _annotations(d),
                rcmenus.header("%s (%s)" % (rcmenus.T_SELECTED, named), "HeaderSelected"),
                rcmenus.action("HideDimension", rcmenus.T_HIDE, fds.SHOWN.hide), view]
    return [i for i in out if i is not None]


def dim_menu(d, global_pos=None):
    from . import rcmenus, featuredimshow as fds
    menu = rcmenus.show(rcmenus.Builder("PartDimension", items(d), chevron=True), global_pos or QtGui.QCursor.pos())
    fds.LAST_MENU[0] = menu
    return menu


def install():
    try:
        from . import featuredimshow
    except Exception:
        return
    if getattr(featuredimshow.dim_menu, "_fw_sw", False):
        return
    dim_menu._fw_sw = True
    featuredimshow._dim_menu_short = featuredimshow.dim_menu
    featuredimshow.dim_menu = dim_menu
