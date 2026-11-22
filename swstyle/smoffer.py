# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sheet Metal without an engine (PM thread, look audit I4).

The Sheet Metal tab runs on the SheetMetal add-on, or on the copy of its engine that ships with this add-on (smcore).
When neither loads, the tab's buttons would draw greyed (dead). Instead each one stays live and offers to install the
free SheetMetal add-on with FreeCAD's own Addon Manager installer (one click, its own progress window); after a
restart the tab works. Without the Addon Manager the Addon Manager window opens instead.
"""

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

NAME = "SheetMetal"
URL = "https://github.com/shaise/FreeCAD_SheetMetal"
BRANCH = "master"
_state = {"installer": None, "registered": []}


def _ask(title):
    from PySide import QtWidgets
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setIcon(QtWidgets.QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText("%s needs FreeCAD's free SheetMetal add-on, which is not installed." % title)
    box.setInformativeText("Install it now? FreeCAD downloads it with the Addon Manager; restart FreeCAD afterwards "
                           "to use the Sheet Metal tools.")
    install = box.addButton("Install", QtWidgets.QMessageBox.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(install)
    box.setObjectName("FW_SheetMetalOffer")
    box.exec_()
    return box.clickedButton() is install


def _done():
    from PySide import QtWidgets
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Sheet Metal",
                                      "The SheetMetal add-on is installed. Restart FreeCAD to use the Sheet Metal tools.")


def install_addon():
    """FreeCAD's Addon Manager installer for the SheetMetal add-on; the Addon Manager window when it is missing."""
    try:
        import sys, os
        here = os.path.join(App.getHomePath(), "Mod", "AddonManager")
        if os.path.isdir(here) and here not in sys.path:
            sys.path.append(here)
        from Addon import Addon
        from addonmanager_installer_gui import AddonInstallerGUI
    except Exception as _fw_err:
        _fw_log("smoffer:import", _fw_err)
        try:
            Gui.Command.get("Std_AddonMgr").run()
        except Exception as _fw_err2:
            _fw_log("smoffer:addonmgr", _fw_err2)
        return None
    gui = AddonInstallerGUI(Addon(NAME, URL, branch=BRANCH))
    _state["installer"] = gui           # kept alive while its dialogs and worker thread run
    try:
        gui.success.connect(lambda *_a: _done())
    except Exception as _fw_err:
        _fw_log("smoffer:signal", _fw_err)
    gui.run()
    return gui


def offer(title):
    if _ask(title):
        return install_addon()
    return None


class _Offer:
    def __init__(self, title, tip):
        self.title, self.tip = title, tip

    def GetResources(self):
        return {"MenuText": self.title, "ToolTip": "%s (installs FreeCAD's SheetMetal add-on first)" % self.tip}

    def IsActive(self):
        return True

    def Activated(self):
        offer(self.title)


# FreeCAD's own workbenches register their commands after start-up: an offer under one of their names would replace
# the real command (look audit AC4: PartDesign_NewSketch became the install offer, so the Sketch button made no sketch)
STOCK = ("PartDesign_", "Sketcher_", "Part_", "Std_", "TechDraw_", "Assembly_", "FEM_", "Draft_", "Spreadsheet_")
NO_OFFER = ("SM_NewSketch",)        # a plain sketch works without the engine


def register():
    """Each Sheet Metal button's command, when the engine did not load: the install offer (no greyed button)."""
    from . import catalog
    have = set(Gui.listCommands())
    done = []
    for cmd in catalog.BY_KEY.values():
        if not cmd.key.startswith("SM_") or not cmd.natives:
            continue
        if any(n in have for n in cmd.natives if not n.startswith("SWStyle_TF_")):
            continue
        if cmd.key in NO_OFFER:
            continue
        name = next((n for n in cmd.natives if not n.startswith("SWStyle_TF_")), None)
        if name is None or name.startswith(STOCK):
            continue        # never take a stock command's name: it is registered later and would be shadowed
        Gui.addCommand(name, _Offer(cmd.label, getattr(cmd, "tip", "") or cmd.label))
        have.add(name)
        done.append(name)
    _state["registered"] = done
    return done
