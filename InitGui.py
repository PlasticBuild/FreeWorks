# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD runs this file with exec(), so all logic lives in the swstyle package.
import swstyle.startup

swstyle.startup.init()

try:
    import swstyle.selfupdate
    swstyle.selfupdate.install()
except Exception as _fw_err:
    import FreeCAD as _fw_app
    _fw_app.Console.PrintLog("FreeCAD: update check not started: %s\n" % _fw_err)
