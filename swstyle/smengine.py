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

import os

import FreeCAD as App
import FreeCADGui as Gui

# what each workbench imports when it first opens (SheetMetal 0.8.26, FrameForge 0.2.1)
SHEETMETAL_MODULES = ("ExtrudedCutout", "SheetMetalBaseCmd", "SheetMetalBaseShapeCmd", "SheetMetalBend",
                      "SheetMetalCmd", "SheetMetalHem", "SheetMetalCornerReliefCmd", "SheetMetalExtendCmd",
                      "SheetMetalFoldCmd", "SheetMetalFormingCmd", "SheetMetalJunction", "SheetMetalRelief",
                      "SheetMetalUnfoldCmd", "SheetMetalUnfolder", "SketchOnSheetMetalCmd", "SheetMetalSketch",
                      "SheetMetalFromSolid")
FRAMEFORGE_MODULES = ("create_bom_tool", "create_custom_profiles_tool", "create_edit_balloons_tool",
                      "create_end_miter_tool", "create_extruded_cutout_tool", "create_link", "create_profiles_tool",
                      "create_trimmed_profiles_tool", "edit_profile_tool", "parametric_line", "populate_ids_tool",
                      "utilities")

_state = {}     # engine name -> True (loaded), or the reason it is not


def _version(folder):
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(os.path.join(folder, "package.xml")).getroot()
        for child in root:
            if child.tag.endswith("version"):
                return child.text.strip()
    except Exception as _fw_err:
        _fw_log("smengine.py:45", _fw_err)
    return "?"


def _load_sheetmetal():
    import importlib
    try:
        tools = importlib.import_module("SheetMetalTools")
        source = "SheetMetal add-on"
    except Exception:

        import sys
        core = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "smcore")
        if not os.path.isfile(os.path.join(core, "SheetMetalTools.py")):
            return "no sheet metal engine: neither the SheetMetal add-on nor the bundled smcore is there"
        if core not in sys.path:
            sys.path.append(core)
        tools = importlib.import_module("SheetMetalTools")
        source = "bundled smcore"
    _state["SheetMetalSource"] = source
    for name in SHEETMETAL_MODULES:
        importlib.import_module(name)
    try:
        Gui.addIconPath(tools.icons_path)
        Gui.addPreferencePage(os.path.join(tools.mod_path, "Resources", "panels", "SMprefs.ui"), "SheetMetal")
    except Exception as _fw_err:
        _fw_log("smengine.py:71", _fw_err)
    App.Console.PrintLog("FreeCAD: sheet metal engine %s %s\n" % (source, _version(tools.mod_path)))
    from . import smbaseflange, smbreakcorner, smedgeflange, smflatten, smhem, smjog, smsketchedbend, smunfold
    from . import smmiterflange
    from . import smclosedcorner, smcornerrelief, smrip, smweldedcorner
    from . import smconvert, smcrossbreak, smdxf, smgusset, smloftedbend, smnobends, smnormalcut, smsweptflange
    from . import smbendtable, smcornertrim, smformingtool, smstamp, smtabslot, smvent
    from . import smextrude, smbendnotch
    smbaseflange.register()
    smedgeflange.register()
    smhem.register()
    smsketchedbend.register()
    smbreakcorner.register()
    smflatten.register()
    smjog.register()
    smunfold.register()
    smmiterflange.register()
    smclosedcorner.register()
    smweldedcorner.register()
    smcornerrelief.register()
    smrip.register()
    smconvert.register()
    smdxf.register()
    smnormalcut.register()
    smcrossbreak.register()
    smvent.register()
    smnobends.register()
    smgusset.register()
    smtabslot.register()
    smloftedbend.register()
    smsweptflange.register()
    smformingtool.register()
    smstamp.register()
    smbendtable.register()
    smcornertrim.register()
    smbendnotch.register()
    smextrude.register()         # Link to thickness, Normal cut (Extrude and Extruded Cut in sheet metal)
    return True


def _load_frameforge():
    """FrameForge is optional: when it is installed its commands load too (its aluminium extrusion
    tables show in Structural Member). Weldments themselves need only stock FreeCAD (weprofile)."""
    import importlib
    try:
        package = importlib.import_module("freecad.frameforge")
    except Exception as error:
        return "the FrameForge add-on is not installed (%s); weldments use FreeCAD's own members" % error
    for name in FRAMEFORGE_MODULES:
        importlib.import_module("freecad.frameforge." + name)
    folder = os.path.dirname(os.path.dirname(list(package.__path__)[0]))     # Mod/frameforge
    App.Console.PrintLog("FreeCAD: FrameForge %s found (optional)\n" % _version(folder))
    return True


_weldments = [False]


def _load_weldments():
    ""
    if _weldments[0]:
        return True
    from . import weconnection, wecutlist, weendcap, wegusset, wemember, wepierce, westructure, wetrim, weweld
    wecutlist.register()
    wemember.register()
    westructure.register()
    wetrim.register()
    weendcap.register()
    wegusset.register()
    weweld.register()
    weconnection.register()
    wepierce.register()
    from . import wechamfer, wecut
    wecut.register()
    wechamfer.register()
    _weldments[0] = True
    return True


def install():
    for name, load in (("SheetMetal", _load_sheetmetal), ("FrameForge", _load_frameforge),
                       ("Weldments", _load_weldments)):
        if _state.get(name) is True:
            continue
        try:
            _state[name] = load()
        except Exception as error:
            _state[name] = "%s did not load: %s" % (name, error)
        if _state[name] is not True:
            App.Console.PrintLog("FreeCAD: %s\n" % _state[name])
    if _state.get("SheetMetal") is not True:
        # no sheet metal engine at all: the tab's buttons offer to install the SheetMetal add-on (never greyed)
        try:
            from . import smoffer
            smoffer.register()
        except Exception as _fw_err:
            _fw_log("smengine:smoffer", _fw_err)


def loaded(name):
    return _state.get(name) is True


def reason(name):
    state = _state.get(name)
    return None if state is True else (state or "%s is not loaded" % name)
