# SPDX-License-Identifier: LGPL-2.1-or-later
""





import FreeCAD as App

_STYLE_ACTION = "Indicator_NavigationSolidWorks"
_BRAND = "SolidWorks"
_OURS = "Default"
_state = {"hooked": False}


def _fw_log(site, err):
    try:
        App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


def relabel():
    """Our wording on the indicator's action and button; returns how many labels changed."""
    try:
        import FreeCADGui as Gui
        from PySide import QtGui, QtWidgets
        mw = Gui.getMainWindow()
        if mw is None:
            return 0
        n = 0
        for a in mw.findChildren(QtGui.QAction):
            if a.objectName() == _STYLE_ACTION:
                for get, put in ((a.text, a.setText), (a.toolTip, a.setToolTip), (a.statusTip, a.setStatusTip)):
                    v = get()
                    if v and _BRAND in v:
                        put(v.replace(_BRAND, _OURS))
                        n += 1
        for b in mw.findChildren(QtWidgets.QWidget, "NavigationIndicator"):
            for get, put in ((getattr(b, "text", None), getattr(b, "setText", None)), (b.toolTip, b.setToolTip)):
                if get is None or put is None:
                    continue
                v = get()
                if v and _BRAND in v:
                    put(v.replace(_BRAND, _OURS))
                    n += 1
            menu = b.menu() if hasattr(b, "menu") else None
            if menu is not None and not _state["hooked"]:
                menu.aboutToShow.connect(relabel)
                _state["hooked"] = True
        return n
    except Exception as _fw_err:
        _fw_log("navlabel.py:relabel", _fw_err)
        return 0


def install():
    try:
        from PySide import QtCore
        for ms in (1500, 6000):
            QtCore.QTimer.singleShot(ms, relabel)
    except Exception as _fw_err:
        _fw_log("navlabel.py:install", _fw_err)
