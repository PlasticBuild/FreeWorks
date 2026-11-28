"""The full Orca Slicer and Bambu Studio (and slicers added by dropping an installer) as tabs; the
CommandManager buttons that open them."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import os

import FreeCAD as App

from . import slicer as backend


def _picture(key):
    """The button's own drawing (resources/slicer/full_<key>.svg)."""
    from pathlib import Path
    from . import icons     # v2last-1127: the V2 pack's PNG for this theme
    return icons.v2_file(str(Path(__file__).resolve().parent / "resources" / "slicer" / ("full_%s.svg" % key)))


SAID = []       # what the full buttons last told the person (newest last; checks read it)


class FullCommand:
    def __init__(self, key):
        self.key = key

    def GetResources(self):
        s = backend.get(self.key)
        return {"MenuText": s.title + " (full)", "ToolTip": "The real %s inside FreeCAD, with every tool it has." % s.title,
                "Pixmap": _picture(self.key)}

    def Activated(self):
        from . import slicertab
        s = backend.get(self.key)
        exe = s.exe()
        if exe is None:
            text = ("%s is not installed on this computer, and FreeCAD has no copy of its own. Slicer Updates "
                    "downloads one; or use Slicer Apps in this tab to add its installer (drop the file on the box)."
                    % s.title)
            App.Console.PrintMessage(text + "\n")
            SAID.append(text)
            del SAID[:-10]
            if os.environ.get("SWSTYLE_NO_SLICER") == "1":      # an unattended run: never a window to answer
                return
            try:
                import FreeCADGui as Gui
                from PySide import QtWidgets
                box = QtWidgets.QMessageBox(Gui.getMainWindow())
                box.setObjectName("SWStyle_SlicerGet")
                box.setWindowTitle(s.title)
                box.setText("%s is not on this computer yet. It is not part of the add-on: Slicer Updates downloads "
                            "it from its release page.\n\nOpen Slicer Updates to download it now?" % s.title)
                get = box.addButton("Download", QtWidgets.QMessageBox.AcceptRole)
                box.addButton(QtWidgets.QMessageBox.Cancel)
                box.exec()
                if box.clickedButton() is get:
                    from . import slicerupdate
                    updates = slicerupdate.open_box(Gui.getMainWindow())
                    if updates is not None and updates.busy is None and not slicerupdate.status(self.key)["latest"]:
                        updates.check()
            except Exception as _fw_err:
                _fw_log("slicerfull.py:46", _fw_err)
            return
        note = s.fallback_note()
        if note:
            App.Console.PrintMessage(note + "\n")
            if self._offer_download(s):
                return
        tab = slicertab.open_tab(self.key, s.title, exe)
        if note and tab is not None:
            tab.status.setText(note)

    def _offer_download(self, s):
        ""

        from . import slicerupdate
        if backend.params().GetBool(self.key + "UseInstalled", False):
            return False
        try:
            import FreeCADGui as Gui
            from PySide import QtWidgets
            box = QtWidgets.QMessageBox(Gui.getMainWindow())
            box.setWindowTitle(s.title)
            box.setText("FreeCAD has no copy of %s of its own yet.\n\nDownload one now, or use the copy installed "
                        "on this computer?" % s.title)
            get = box.addButton("Download a copy", QtWidgets.QMessageBox.AcceptRole)
            use = box.addButton("Use the installed copy", QtWidgets.QMessageBox.ActionRole)
            box.addButton(QtWidgets.QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is get:
                slicerupdate.open_box(Gui.getMainWindow())
                return True
            if box.clickedButton() is use:
                backend.params().SetBool(self.key + "UseInstalled", True)
                return False
            return True
        except Exception as _fw_err:
            _fw_log("slicerfull.py:100", _fw_err)
            return False

    def IsActive(self):
        return True


COMMANDS = (("SWStyle_SlicerFullOrca", lambda: FullCommand("orca")),
            ("SWStyle_SlicerFullBambu", lambda: FullCommand("bambu")),
            ("SWStyle_SlicerFullPrusa", lambda: FullCommand("prusa")))

BUTTONS = (("SlicerFullOrca", "Orca Slicer (full)", "SWStyle_SlicerFullOrca",
            "The real Orca Slicer inside FreeCAD, with every tool it has.", "Orca\nFull", "full_orca"),
           ("SlicerFullBambu", "Bambu Studio (full)", "SWStyle_SlicerFullBambu",
            "The real Bambu Studio inside FreeCAD, with every tool it has.", "Bambu\nFull", "full_bambu"),
           ("SlicerFullPrusa", "PrusaSlicer (full)", "SWStyle_SlicerFullPrusa",
            "The real PrusaSlicer inside FreeCAD, with every tool it has.", "Prusa\nFull", "full_prusa"))
