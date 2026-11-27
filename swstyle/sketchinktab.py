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


COLOURS = (("Black", (0x20, 0x20, 0x20)), ("Blue", (0x1A, 0x4D, 0xE6)), ("Red", (0xD8, 0x1E, 0x1E)),
           ("Green", (0x1E, 0x96, 0x32)), ("Orange", (0xF0, 0x8C, 0x00)), ("Purple", (0x80, 0x30, 0xB0)))
PREFIX = "FreeWorks_InkColor"


def set_colour(rgb):
    from . import pentools
    r, g, b = rgb
    pentools.params().SetUnsigned("InkColor", (r << 24) | (g << 16) | (b << 8) | 255)
    page = pentools._page
    if page is not None and getattr(page, "_sets", None):
        try:
            page.node.getChild(0).getChild(1).rgb.setValue(*pentools.ink_colour())
        except Exception as _fw_err:
            _fw_log("sketchinktab.py:36", _fw_err)


def current():
    from . import pentools
    r, g, b = pentools.ink_colour()
    return tuple(int(round(v * 255)) for v in (r, g, b))


def _swatch(rgb):
    """A square of the colour as the button's icon."""
    try:
        from PySide import QtGui
        pm = QtGui.QPixmap(32, 32)
        pm.fill(QtGui.QColor(*rgb))
        return QtGui.QIcon(pm)
    except Exception:
        return None


class ColourCommand:
    def __init__(self, name, rgb):
        self.name, self.rgb = name, rgb

    def GetResources(self):
        return {"MenuText": self.name, "ToolTip": "Draws the ink in %s." % self.name.lower(), "Pixmap": "Std_RandomColor",
                "Checkable": current() == self.rgb, "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, checked=None):
        set_colour(self.rgb)
        _sync()


class ColourFlyout:
    """The flyout's own button: the ink's colour now; clicked, Pen Properties (any colour, width)."""

    def GetResources(self):
        return {"MenuText": "Color", "ToolTip": "The color of the ink.", "Pixmap": "Std_RandomColor",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        Gui.runCommand("FreeWorks_PenProperties", 0)
        _sync()


def _sync():
    try:
        from PySide import QtWidgets
        for a in Gui.getMainWindow().findChildren(QtWidgets.QAction):
            name = a.objectName() or ""
            for text, rgb in COLOURS:
                if name == PREFIX + text and a.isCheckable():
                    a.blockSignals(True)
                    a.setChecked(current() == rgb)
                    a.blockSignals(False)
    except Exception as _fw_err:
        _fw_log("sketchinktab.py:98", _fw_err)


def register():
    have = Gui.listCommands()
    for text, rgb in COLOURS:
        if PREFIX + text not in have:
            Gui.addCommand(PREFIX + text, ColourCommand(text, rgb))
    if PREFIX not in have:
        Gui.addCommand(PREFIX, ColourFlyout())
