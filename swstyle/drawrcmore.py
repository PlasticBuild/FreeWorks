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


def _asm():
    from . import asmdrawing
    return asmdrawing


def exploded_choice(view):
    """(is exploded now, the exploded view name to show) or None when the view's assembly has none."""
    try:
        A = _asm()
        asm = A.assembly_of_view(view)
        if asm is None:
            return None
        views = A.exploded_views(asm)
        if not views:
            return None
        cur = A.view_state(view)[2]
        return bool(cur), (cur or views[0].Name)
    except Exception:
        return None


def set_exploded(view, on):
    got = exploded_choice(view)
    if got is None:
        return False
    doc = view.Document
    doc.openTransaction("Show in Exploded State" if on else "Show in Collapsed State")
    try:
        _asm().apply_view(view, exploded=got[1] if on else "")
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


def _item(view):
    from . import rcmenus
    got = exploded_choice(view)
    if got is None:
        return None
    if got[0]:
        return rcmenus.action("ShowCollapsedState", "Show in Collapsed State", lambda: set_exploded(view, False))
    return rcmenus.action("ShowExplodedState", "Show in Exploded State", lambda: set_exploded(view, True))


def _insert(out, item):
    if item is None:
        return out
    at = next((i + 1 for i, it in enumerate(out) if getattr(it, "key", "") in ("HideView", "Hide")), None)
    return out + [item] if at is None else out[:at] + [item] + out[at:]


def edit_view(v):
    ""
    from . import drawselect
    return drawselect.open_for(v)


def zoom_to_sheet(page):
    ""
    from . import drawings as D, newdoc
    try:
        newdoc.show_sheet(page)
    except Exception as _fw_err:
        _fw_log("drawrcmore.py:89", _fw_err)
    from PySide import QtCore
    QtCore.QTimer.singleShot(150, lambda: D.fit_page(page))
    return True


def _rerun(out, key, fn):
    for it in out:
        if getattr(it, "key", "") == key:
            it.run = fn
    return out


def install():
    try:
        from . import drawmenu
    except Exception:
        return False
    if getattr(drawmenu, "_fw_rcmore", False):
        return True
    view0, tree0, sheet0 = drawmenu.view_items, drawmenu.tree_view_items, drawmenu.tree_sheet_items

    def view_items(v, edge=None):
        out = view0(v, edge)
        if edge is None:
            try:
                out = _insert(out, _item(v))
            except Exception as error:
                App.Console.PrintLog("FreeCAD: view menu: %s\n" % error)
        return out

    def tree_view_items(v, view=None):
        out = tree0(v, view)
        try:
            out = _insert(out, _item(v))
            out = _rerun(out, "EditFeature", lambda: edit_view(v))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: view menu: %s\n" % error)
        return out

    def tree_sheet_items(page, view=None):
        out = sheet0(page, view)
        try:
            out = _rerun(out, "ZoomToSelection", lambda: zoom_to_sheet(page))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sheet menu: %s\n" % error)
        return out
    drawmenu.view_items, drawmenu.tree_view_items = view_items, tree_view_items
    drawmenu.tree_sheet_items = tree_sheet_items
    drawmenu._fw_rcmore = True
    return True
