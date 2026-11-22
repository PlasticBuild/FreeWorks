# SPDX-License-Identifier: LGPL-2.1-or-later
# Nothing to register without the GUI; the style lives in InitGui.py.

# selfupdate: a downloaded update is put in place first, before any other part of the add-on is loaded
try:
    import fwupdate_boot as _fw_boot
    _fw_boot.apply_pending()
    del _fw_boot
except Exception as _fw_err:
    import FreeCAD as _fw_app
    _fw_app.Console.PrintLog("FreeCAD: update step: %s\n" % _fw_err)


# regtypes98: each type only when its reader / writer is there (as Save As lists them, saveas.py), so
# File > Import / Export has no entry that cannot work
import FreeCAD as _App


def _fw_register_cad_types():
    import importlib.util
    try:
        if importlib.util.find_spec("swfiles") is None:
            return
    except Exception:
        return
    # opened by swfiles itself, without the other CAD system
    _App.addImportType("Part (*.sldprt *.SLDPRT)", "importFreeWorksCAD")
    _App.addImportType("Assembly (*.sldasm *.SLDASM)", "importFreeWorksCAD")
    _App.addImportType("Parasolid (*.x_t *.X_T *.x_b *.X_B)", "importFreeWorksCAD")
    try:
        from swfiles import cadconv
        cadmpeg = bool(cadconv.executable())
    except Exception:
        cadmpeg = False
    if cadmpeg:
        _App.addImportType("Inventor (*.ipt *.IPT *.iam *.IAM)", "importFreeWorksCAD")
        _App.addImportType("CATIA V5 Part (*.CATPart *.catpart)", "importFreeWorksCAD")
        _App.addImportType("Fusion 360 (*.f3d *.F3D)", "importFreeWorksCAD")
        _App.addImportType("Rhino (*.3dm *.3DM)", "importFreeWorksCAD")
        _App.addImportType("Creo View (*.pvz *.PVZ)", "importFreeWorksCAD")
        _App.addImportType("ACIS (*.sat *.SAT *.sab *.SAB)", "importFreeWorksCAD")
    try:
        from swfiles import swapp
        solidworks = bool(swapp.solidworks_installed())
    except Exception:
        solidworks = False
    if solidworks:          # written by that CAD system itself
        _App.addExportType("Part (*.sldprt)", "importFreeWorksCAD")
        _App.addExportType("Assembly (*.sldasm)", "importFreeWorksCAD")
    if cadmpeg:
        _App.addExportType("Rhino (*.3dm)", "importFreeWorksCAD")


try:
    _fw_register_cad_types()
except Exception as _fw_err:
    _App.Console.PrintLog("FreeCAD: CAD file types: %s\n" % _fw_err)
del _fw_register_cad_types
del _App
