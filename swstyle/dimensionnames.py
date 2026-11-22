# SPDX-License-Identifier: LGPL-2.1-or-later
""








import FreeCAD as App

SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks"
KEY = "ShowDimensionalName"


def register():
    p = App.ParamGet(PARAMS)
    if not p.GetBool("DimensionNamesDefaultSet", False):
        App.ParamGet(SKETCHER).SetBool(KEY, False)
        p.SetBool("DimensionNamesDefaultSet", True)

    # dimension reads 40, not 40 mm (FreeCAD's Sketcher HideUnits; Options > Show units after this)
    if not p.GetBool("DimensionUnitsDefaultSet", False):
        App.ParamGet(SKETCHER).SetBool("HideUnits", True)
        p.SetBool("DimensionUnitsDefaultSet", True)
