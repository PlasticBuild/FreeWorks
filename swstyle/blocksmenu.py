# SPDX-License-Identifier: LGPL-2.1-or-later
""
import FreeCAD as App
import FreeCADGui as Gui

NAMES = ("SWStyle_MakeBlock", "SWStyle_EditBlock", "SWStyle_InsertBlock", "SWStyle_AddRemoveBlockEntities",
         "SWStyle_RebuildBlocks", "SWStyle_SaveBlock", "SWStyle_ExplodeBlock")


class BlocksMenu:
    def GetCommands(self):
        have = set(Gui.listCommands())
        return tuple(name for name in NAMES if name in have)

    def GetResources(self):
        return {"MenuText": "Blocks", "ToolTip": "Make, edit and insert sketch blocks",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return App.ActiveDocument is not None


def register():
    from . import blocks
    blocks.register()
    if "SWStyle_BlocksMenu" not in Gui.listCommands():
        Gui.addCommand("SWStyle_BlocksMenu", BlocksMenu())


def menu_items(have):
    """Tools > Blocks, with the look's other Tools entries (before Measure)."""
    if "SWStyle_BlocksMenu" not in have:
        return []
    return [{"insert": "SWStyle_BlocksMenu", "menuItem": "Std_Measure"}]
