# SPDX-License-Identifier: LGPL-2.1-or-later
"""editobj-1126: the object a view provider belongs to, without raising for a view provider that has none.

FreeCAD 1.1's AssemblyGui.ViewProviderAssembly (what Gui.ActiveDocument.getInEdit() returns while an assembly is
being edited, and what slotInEdit / slotResetEdit hand to a document observer) has no `Object` attribute: reading
`vp.Object` raised "'AssemblyGui.ViewProviderAssembly' object has no attribute 'Object'" at selcolour, featureflow,
pmkeys, shell and sketch3d (PC log 11-26, just before the Insert Component crash). Every read of that kind goes
through these helpers now; for a view provider that has an Object they answer exactly what the plain read answered.
"""


def of(vp):
    """vp.Object, or None when vp is None or has no Object (an assembly's view provider)."""
    if vp is None:
        return None
    try:
        return vp.Object
    except Exception:
        return None


def type_id(vp):
    """vp.Object.TypeId, or "" when there is no object."""
    obj = of(vp)
    if obj is None:
        return ""
    try:
        return obj.TypeId
    except Exception:
        return ""


def derived(vp, type_name):
    """vp.Object.isDerivedFrom(type_name), or False when there is no object."""
    obj = of(vp)
    if obj is None:
        return False
    try:
        return bool(obj.isDerivedFrom(type_name))
    except Exception:
        return False
