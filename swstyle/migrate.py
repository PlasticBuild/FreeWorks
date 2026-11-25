# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App

ROOT = "User parameter:BaseApp/Preferences/Mod/"
OLD, NEW = ROOT + "SolidWorksStyle", ROOT + "FreeWorks"
DONE = "MigratedFromSolidWorksStyle"

# Key our options.py writes into a saved document's Meta (drafting standard)
DOC_META_OLD, DOC_META_NEW = "SolidWorksDraftingStandard", "FreeWorksDraftingStandard"

_SETTERS = {
    "Boolean": "SetBool",
    "Integer": "SetInt",
    "Float": "SetFloat",
    "String": "SetString",
    "Unsigned Long": "SetUnsigned",
}


def _empty(grp):
    return not grp.GetContents() and not grp.GetGroups()


def _copy(src, dst):
    for kind, name, value in src.GetContents() or []:
        setter = _SETTERS.get(kind)
        if setter:
            getattr(dst, setter)(name, value)
    for name in src.GetGroups():
        _copy(src.GetGroup(name), dst.GetGroup(name))


def run():
    """Copy the old settings once. Returns True when it copied something."""
    new = App.ParamGet(NEW)
    if new.GetBool(DONE, False):
        return False
    old = App.ParamGet(OLD)
    copied = False
    if _empty(new) and not _empty(old):
        _copy(old, new)
        copied = True
    new.SetBool(DONE, True)
    return copied


def doc_meta(doc, key=DOC_META_NEW):
    """Read the drafting standard from a document, falling back to the old key."""
    meta = doc.Meta
    return meta.get(key) or meta.get(DOC_META_OLD)
