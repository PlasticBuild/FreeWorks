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

PAGE = "Weldments"
RENAME = "Rename cut list folders with Description property value"
ASSIGN = {"Description": "Assign custom properties: Description", "Length": "Assign custom properties: Length",
          "Angle1": "Assign custom properties: Angle 1", "Angle2": "Assign custom properties: Angle 2"}
DERIVED = "Create derived configurations"
DERIVED_NAMES = ("<As Machined>", "<As Welded>")


def setting(doc, text, default):
    try:
        from . import optionspages
        return optionspages.doc_value(doc, PAGE, text, default)
    except Exception as _fw_err:
        _fw_log("weldprops.py:41", _fw_err)
        return default


def assigned(doc, prop):
    return bool(setting(doc, ASSIGN[prop], True))


def item_props(doc, props):
    """The cut list item's values with the properties that are not assigned left empty."""
    out = dict(props)
    for prop in ASSIGN:
        if prop in out and not assigned(doc, prop):
            out[prop] = "" if prop == "Description" else 0.0
    return out


def item_label(doc, default_label, props, count):
    if setting(doc, RENAME, False) and props.get("Description"):
        return "%s(%d)" % (props["Description"], count)
    return default_label


def on_new_weldment(doc):
    """Create derived configurations: <active><As Machined> and <active><As Welded>."""
    if not setting(doc, DERIVED, True):
        return []
    try:
        from . import configs, configmanager as cm
        had = cm.table(doc) is not None
        t = configs.table(doc, create=True)
        if t is None:
            return []
        if not had:

            # them stays out of the tree (Insert > Tables > Design Table brings it back)
            try:
                from . import cmflows
                cmflows.delete_table(doc, ask=False)
            except Exception as error:
                App.Console.PrintLog("FreeCAD weldment design table: %s\n" % error)
        parent = t.active() or (t.names()[0] if t.names() else "Default")
        made = []
        for suffix in DERIVED_NAMES:
            name = parent + suffix
            if name not in t.names() and cm.add_derived(t, parent, name):
                made.append(name)
            t = configs.table(doc, create=False) or t
        if parent in t.names() and t.active() != parent:
            cm.show(t, parent)
        return made
    except Exception as error:
        App.Console.PrintLog("FreeCAD weldment configurations: %s\n" % error)
        return []
