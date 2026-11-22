# SPDX-License-Identifier: LGPL-2.1-or-later
""






import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

_waiting = {}
_opening = set()


class opening:
    """The feature was just made and its PM opens right after the first recompute."""

    def __init__(self, obj, on=True):
        self.key = _key(obj) if on else None

    def __enter__(self):
        if self.key is not None:
            _opening.add(self.key)
        return self

    def __exit__(self, *exc):
        _opening.discard(self.key)
        return False


def _key(obj):
    try:
        return (obj.Document.Name, obj.Name)
    except Exception:
        return None


def _in_pm(obj):
    if Gui is None or not App.GuiUp:
        return False
    if _key(obj) in _opening:
        return True
    try:
        if not Gui.Control.activeDialog():
            return False
        gdoc = Gui.getDocument(obj.Document.Name)
        vp = gdoc.getInEdit() if gdoc is not None else None
        if vp is not None and getattr(vp, "Object", None) is obj:
            return True
        from . import surfacepms
        last = getattr(surfacepms, "_LAST", None)
        return last is not None and getattr(last, "obj", None) is obj
    except Exception:
        return False


_NOT_PICKS = ("BaseFeature", "AttachmentSupport", "Support", "_Body", "Group", "ExpressionEngine", "Origin")


def _nothing_picked(obj):
    """No pick box of the feature holds anything yet (a wrong pick is still an error)."""
    try:
        for name in obj.PropertiesList:
            if name in _NOT_PICKS or not obj.getTypeIdOfProperty(name).startswith("App::PropertyLink"):
                continue
            if getattr(obj, name):
                return False
    except Exception:
        return False
    return True


def waits(obj, error):
    """True when error is a missing pick, nothing is picked and obj's PM is open: the caller then
    builds nothing."""
    key = _key(obj)
    if key is not None and str(error).startswith("Pick") and _nothing_picked(obj) and _in_pm(obj):
        _waiting[key] = str(error)
        return True
    return False


def done(obj):
    """execute() made the feature: it waits no more."""
    key = _key(obj)
    if key is not None:
        _waiting.pop(key, None)


def forget(doc_name, name):
    """The feature is cancelled (or gone): drop what it waited for."""
    _waiting.pop((doc_name, name), None)


def message(obj):
    """What the feature still waits for ("" when nothing)."""
    key = _key(obj)
    return _waiting.get(key, "") if key is not None else ""
