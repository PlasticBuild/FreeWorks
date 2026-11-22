# SPDX-License-Identifier: LGPL-2.1-or-later


import FreeCAD

try:
    from swstyle import stockrestore as _fw_stockrestore
    _fw_stockrestore.uninstall()
except Exception as _fw_error:
    FreeCAD.Console.PrintError("FreeWorks uninstall: %s\n" % _fw_error)
