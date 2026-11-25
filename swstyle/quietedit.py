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

_before = {}


def _touched(doc):
    out = set()
    for o in doc.Objects:
        try:
            if "Touched" in o.State:
                out.add(o.Name)
        except Exception as _fw_err:
            _fw_log("quietedit.py:35", _fw_err)
    return out


def note(obj):
    """Call at the start of the edit (a slotInEdit): which features needed a rebuild already."""
    try:
        doc = obj.Document
        _before[(doc.Name, obj.Name)] = (_touched(doc), App.getActiveTransaction())
    except Exception as _fw_err:
        _fw_log("quietedit.py:45", _fw_err)


def close(obj):
    """Close the native panel of obj quietly. True when done; False leaves the panel to its Cancel."""
    import FreeCADGui as Gui
    try:
        doc = obj.Document
        key = (doc.Name, obj.Name)
    except Exception:
        return False
    if key not in _before:
        return False
    before, tx_then = _before.pop(key)
    gdoc = Gui.getDocument(doc.Name)
    if gdoc is None:
        return False
    try:
        in_edit = gdoc.getInEdit()
        if in_edit is None or in_edit.Object is not obj:
            return False
    except Exception:
        return False
    tx_now = App.getActiveTransaction()
    try:
        Gui.Control.closeDialog()
        if tx_now:
            # the panel's edit step: dropped, as Cancel does. The tree's double-click opens that
            # step before the edit starts (tx_now == tx_then), and kept, it was an Undo step of its

            App.closeActiveTransaction(True)
        gdoc.resetEdit()
    except Exception:
        return False
    for o in doc.Objects:
        try:
            if o.Name not in before and "Touched" in o.State:
                o.purgeTouched()
        except Exception as _fw_err:
            _fw_log("quietedit.py:81", _fw_err)
    return True
