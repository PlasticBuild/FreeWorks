"""Pictures for the Simulation, Flow Simulation, MBD and MotionManager buttons.

The icon pack has no SIM_, FLOW_ or MOTION_ families, so those buttons fell back to FreeCAD's own FEM icons
(or to initials). resources/simicons holds original drawings in the CommandManager style (made by
_make_icons.py there; nothing comes from another program). A pack picture always wins: a key whose pack
has png/FW_<key> uses it, and only keys with no picture of their own take the drawing."""
import os

FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "simicons")


# keys whose icon family the pack has no picture for: they take our drawing
REDRAWN = ("PenTouch", "PenAutoShape", "PenAutoSketchEntities", "Instant2D")


def svg(name):
    """Path of our drawing for a key or a MOTION_ family, or None."""
    path = os.path.join(FOLDER, name + ".svg")
    return path if os.path.isfile(path) else None


def picture(name, pack=None):
    """A QIcon: the pack's family when it has one (pack, else name), else our drawing of name, else empty."""
    from . import icons
    for fam in (pack, name):
        if fam and _pack_has(fam):
            return icons.family(fam)
    path = svg(name)
    from PySide import QtGui
    return QtGui.QIcon(path) if path else QtGui.QIcon()


def family_or_drawing(name):
    """The pack family name when the pack has it, else the path of our drawing (icons.family loads either)."""
    return name if _pack_has(name) or not svg(name) else svg(name)


def _pack_has(name):
    try:
        from . import icons
        root = icons._ROOT
        return root is not None and (root / "png" / name).is_dir()
    except Exception:
        return False


def install():
    """Give every catalog key with no icon a picture: the pack's FW_<key> family, else our drawing."""
    from . import catalog
    done = 0
    for key, cmd in list(catalog.BY_KEY.items()):
        if cmd.icon and not (key in REDRAWN and isinstance(cmd.icon, str) and not os.path.isfile(cmd.icon)
                             and not _pack_has(cmd.icon)):
            continue
        if _pack_has("FW_" + key):
            cmd.icon = "FW_" + key
            done += 1
        elif svg(key):
            cmd.icon = svg(key)
            done += 1
    return done
