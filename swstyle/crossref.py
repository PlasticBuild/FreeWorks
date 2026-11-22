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
from PySide import QtCore, QtWidgets

NAME = "PartDesignGui__DlgReference"      # a plain QDialog built from DlgReference.ui


def _ask():
    try:
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks").GetBool("AskOutsideBody", False)
    except Exception:
        return False


def _answer(dlg):
    try:
        radio = dlg.findChild(QtWidgets.QRadioButton, "radioDependent")
        if radio is None:
            return
        radio.setChecked(True)
        dlg.accept()
        App.Console.PrintLog("FreeCAD: outside-body pick taken as a dependent copy\n")
    except RuntimeError as _fw_err:
        _fw_log("crossref.py:44", _fw_err)
    except Exception as error:
        App.Console.PrintLog("FreeCAD crossref: %s\n" % error)


def _handler(obj, event):
    try:
        if isinstance(obj, QtWidgets.QDialog) and obj.objectName() == NAME and not _ask():
            QtCore.QTimer.singleShot(0, lambda d=obj: _answer(d))
    except Exception as _fw_err:
        _fw_log("crossref.py:54", _fw_err)
    return False


def install():
    from . import events
    events.register("crossref", (QtCore.QEvent.Show,), _handler)
