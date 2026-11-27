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
import re

import FreeCAD as App
import FreeCADGui as Gui

TIPS = {
    # selection and view
    "Select Other": "Lists the items under the pointer so you can pick one hidden behind another.",
    "Selection Tools": "Box, lasso and the other ways of picking several items at once.",
    "Box Selection": "Drag a box to pick the items inside it.",
    "Lasso Selection": "Draw around the items to pick them.",
    "Selection Filters": "Limits picking to one kind of item: faces, edges, vertices...",
    "Magnified Selection": "Shows a magnified view under the pointer to pick small items.",
    "Previous Selection": "Picks again what was picked before.",
    "Select Tangency": "Adds the faces or edges tangent to the picked one.",
    "Select Midpoint": "Picks the middle point of the edge.",
    "Select Loop": "Picks the loop of edges that the edge belongs to.",
    "Select Partial Loop": "With two edges of a loop picked, adds the edges between them, the shorter way round.",
    "Select Connected": "Picks the faces connected to the picked one.",
    "Select Chain": "Picks the chain of sketch entities joined end to end.",
    "Invert Selection": "Picks everything that is not picked now, and drops what is.",
    "Contour Select": "Picks a closed contour of the sketch.",
    "Contour Select Tool": "Picks a closed contour of the sketch.",
    "Zoom/Pan/Rotate": "The view tools: zoom, pan, rotate and roll.",
    "Zoom to Fit": "Zooms so the whole model fits the window.",
    "Zoom to Area": "Zooms in on the box you drag.",
    "Zoom In/Out": "Drag up or down to zoom in or out.",
    "Zoom to Selection": "Zooms in on the picked items.",
    "Rotate View": "Drag to turn the view.",
    "Pan": "Drag to slide the view.",
    "Roll View": "Drag to turn the view about the axis toward you.",
    "Rotate About Scene Floor": "Drag to turn the model about the floor of the scene.",
    "View Orientation...": "Picks a standard or saved view of the model.",
    "Set Current View As...": "Makes the view on screen one of the standard views.",
    "Normal To": "Turns the view square onto the picked face or plane.",
    "Recent Commands": "The commands you used last.",
    "Edit Scene": "Changes the background, floor and lights of the scene.",
    "Display Grid": "Shows or hides the grid.",
    # features and tree
    "Edit Feature": "Opens the feature's PropertyManager to change it.",
    "Edit Sketch": "Opens the sketch to change it.",
    "Edit Sketch Plane": "Moves the sketch to another plane or flat face.",
    "Comment": "Adds a note to the item, or shows its notes.",
    "Parent/Child...": "Lists the items this one depends on and the items that depend on it.",
    "Configure Feature": "Sets the feature on or off in each configuration.",
    "Configure Dimension": "Sets the dimension's value in each configuration.",
    "Configure Component": "Sets the component's state in each configuration.",
    "Delete": "Deletes the picked items.",
    "Delete...": "Deletes the picked items, after asking what to do with the items that use them.",
    "Add to Favorites": "Adds the item to Favorites at the top of the FeatureManager tree.",
    "Remove from Favorites": "Takes the item out of Favorites.",
    "Save Selection": "Keeps what is picked as a selection set in the tree.",
    "Add to New Folder": "Puts the picked items in a new folder of the tree.",
    "Create New Folder": "Makes an empty folder in the tree.",
    "Feature Properties...": "Name, description and suppression of the feature.",
    "Properties...": "Shows and changes the item's properties.",
    "Change Transparency": "Makes the item see-through, or solid again.",
    "Go To...": "Finds an item of the tree by its name.",
    "Go To Feature (in Tree)": "Shows the feature in the FeatureManager tree.",
    "Rename tree item": "Gives the tree item a new name.",
    "Hide/Show Tree Items...": "Chooses which items the FeatureManager tree shows.",
    "Collapse Items": "Folds every item of the tree.",
    "Customize Menu": "Chooses which items this menu shows.",
    "Suppress": "Leaves the item out of the model until it is unsuppressed.",
    "Unsuppress": "Brings the suppressed item back into the model.",
    "Unsuppress with Dependents": "Brings the item and the items that depend on it back into the model.",
    "Rollback": "Rolls the part back to before this feature.",
    "Roll Forward": "Rolls the part forward one feature.",
    "Roll to Previous": "Rolls the part back to the feature before the bar.",
    "Roll to End": "Rolls the part forward to its last feature.",
    "What's Wrong?": "Lists the errors and warnings of the last rebuild.",
    "MateXpert...": "Finds the mates that keep the assembly from solving.",
    "Hide": "Hides the picked items.",
    "Show": "Shows the picked items again.",
    "Hide Components": "Hides the picked components.",
    "Show Components": "Shows the picked components again.",
    "Isolate": "Shows only the picked items until you exit Isolate.",
    "Appearance...": "Changes the color and look of the item.",
    "Appearances": "Changes the color and look of the item.",
    "Copy Appearance": "Copies the item's look to paste on another.",
    "Remove Appearance": "Takes the item's own look off.",
    "Face Properties...": "The face's name and appearance.",
    "Edge Properties...": "The edge's name and length.",
    "Body Properties...": "The body's name and properties.",
    "Delete Body...": "Deletes the body from the part.",
    "Insert into New Part...": "Saves the bodies as a new part linked to this one.",
    "Create Plane Parallel to Screen": "Makes a reference plane through the pick, facing you.",
    "Export to DXF / DWG": "Saves the face or sketch as a DXF or DWG file.",
    "Feature Recognition...": "Finds features in imported geometry.",
    "Edit Library Feature": "Opens the library feature to change it.",
    "Update Library Feature": "Brings the library feature up to date with its file.",
    "Dissolve Library Feature": "Turns the library feature into ordinary features.",
    # sketch
    "Exit Sketch": "Closes the sketch and keeps the changes.",
    "Relations/Snaps Options...": "The options for sketch relations and snaps.",
    "Sketch Entities": "The sketch tools: line, rectangle, circle, arc...",
    "Sketch Tools": "Fillet, trim, offset, mirror and the other sketch tools.",
    "More Dimensions": "The other dimension tools: horizontal, vertical, ordinate...",
    "Quick Snaps": "Snaps the next pick to one kind of point.",
    "Selected Entity": "The commands for the picked sketch entity.",
    "Detach Segment on Drag": "Drags the entity off what it is joined to.",
    "End chain": "Ends the chain of lines here.",
    "Switch to arc": "Draws an arc from the end of the line instead.",
    "Make Horizontal": "Adds a Horizontal relation.",
    "Make Vertical": "Adds a Vertical relation.",
    "Fix": "Fixes the item where it is.",
    "Make Fixed": "Fixes the entity where it is.",
    "Construction Geometry": "Turns the entity into construction geometry, or back.",
    "Display/Delete Relations...": "Lists the relations of the sketch to check or delete them.",
    "Preview Sketch Dimension": "Shows the entity's size while you point at it.",
    "Sketch Numeric Input": "Type the sizes while you sketch.",
    "Clear Selections": "Empties the selection box.",
    # assembly
    "Edit Part": "Edits the part in the context of the assembly.",
    "Edit Subassembly": "Edits the subassembly in the context of the assembly.",
    "Open Part": "Opens the part in its own window.",
    "Open Subassembly": "Opens the subassembly in its own window.",
    "Open Part in Position": "Opens the part turned as it is in the assembly.",
    "Open Drawing": "Opens the drawing of the part.",
    "Float": "Lets the component move again.",
    "View Mates": "Lists the mates of the component.",
    "Component Properties...": "Name, configuration and state of the component.",
    "Form New Subassembly": "Makes a subassembly of the picked components.",
    "Dissolve Subassembly": "Moves the subassembly's components up into this assembly.",
    "Make Subassembly Flexible": "Lets the subassembly's parts move as their mates allow.",
    "Make Subassembly Rigid": "Makes the subassembly move as one piece.",
    "Make Independent": "Makes this instance its own copy of the part.",
    "Copy with Mates": "Copies the component and its mates.",
    "Temporary Fix/Group": "Holds the components still while you mate others.",
    "Replace Components": "Puts another file in place of the component.",
    "Reload": "Reads the component's file again.",
    "Component Display": "Draws the component as wireframe, shaded and so on.",
    "Set to Lightweight": "Loads only what is needed to show the component.",
    "Set to Resolved": "Loads the whole component.",
    "Add/Edit Mates": "Opens the Mate PropertyManager for the component.",
    "Edit Assembly": "Goes back to editing the assembly.",
    "Component Preview Window": "Shows the component alone in a side view.",
    "Make Virtual": "Saves the component inside the assembly instead of its own file.",
    "Flip Mate Alignment": "Turns the mate's alignment the other way.",
    "Replace Mate Entities": "Picks other faces or edges for the mate.",
    # drawings
    "Edit Sheet Format": "Edits the sheet format: border and title block.",
    "Edit Sheet": "Goes back to editing the sheet.",
    "Lock Sheet Focus": "Keeps editing the sheet when you double-click a view.",
    "Unlock Sheet Focus": "Lets a double-click on a view edit it again.",
    "Add Sheet...": "Adds a sheet to the drawing.",
    "Copy": "Copies the picked item.",
    "Paste": "Pastes what was copied.",
    "Lock View Position": "Keeps the view where it is.",
    "Unlock View Position": "Lets the view be dragged again.",
    "Lock View Focus": "Keeps editing the view when you click outside it.",
    "Unlock View Focus": "Lets clicks outside the view leave it.",
    "Alignment": "Lines the view up with another view, or breaks the line-up.",
    "Tangent Edge": "Shows tangent edges visible, with a line style, or not at all.",
    "Hide/Show Edges": "Hides or shows the picked edges of the view.",
    "Line Color": "Changes the color of the picked edges.",
    "Line Thickness": "Changes the thickness of the picked edges.",
    "Line Style": "Changes the line style of the picked edges.",
    "Title Block Fields...": "Fills in the title block of the sheet.",
    "Automatic Border...": "Draws the border and zones of the sheet.",
    "Insert Bend Lines": "Shows the bend lines of the flat pattern.",
    # lists and panes
    "Correct Selected": "Fixes the picked check where it can be fixed.",
    "Correct All": "Fixes every check that can be fixed.",
    "Run Again": "Runs the checks again.",
    "Save Report...": "Saves the results as a report.",
    "Edit Table...": "Opens the table to change it.",
    "Show Configuration": "Makes this configuration the active one.",
    "Add Configuration...": "Adds a configuration of the model.",
    "Go To Feature": "Picks the feature in the tree.",
    "Delete All": "Deletes every row of the list.",
    "Add Existing Folder...": "Adds a folder from your computer to the Design Library.",
    "Open Folder...": "Opens the folder in the file browser.",
    "Forming Tools Folder": "Marks the folder as holding forming tools.",
    "Assemblies Folder": "Marks the folder as holding assemblies.",
    "New Folder": "Makes a new folder here.",
    "Rename": "Gives the item a new name.",
    "Properties": "Shows the folder's location, size and contents.",
    "Open": "Opens the file.",
    "Insert": "Puts the file into the active document.",
    "Explore": "Opens the folder in the file browser.",
    "Customize": "Changes the toolbars, menus and keys.",
    # more from the menus (FW_RC_TIPS audit, 2026-11-05)
    "Unlink Value": "Takes the dimension off its shared value; it keeps its number.",
    "Enable CommandManager": "Shows the tabbed CommandManager above the graphics area, or plain toolbars.",
    "Use Large Buttons with Text": "Shows the CommandManager buttons large, with their names under them.",
    "Toolbars": "Shows or hides the toolbars.",
    "Keep Visible": "Pins the PropertyManager so it stays open for the next one.",
    "Help": "Opens the help for this PropertyManager.",
    "Body": "Commands for the body the picked item belongs to.",
    "New Selection Set": "Saves what is picked now as a selection set in the tree.",
    "Annotations": "Shows or hides kinds of annotations, and the annotation commands.",
    "Change Layer": "Moves the picked items to another layer.",
    "Tables": "The drawing's tables: BOM, hole, revision and general tables.",
    "Drawing Views": "Adds a view: projected, section, detail, broken-out...",
    "Relations": "Adds a relation between the picked sketch entities.",
    "Reset sketch visibility": "Hides again the sketches of the model shown in the view.",
    "Convert View to Sketch": "Copies the view's edges into a sketch.",
    "Show/Hide": "Shows or hides the item.",
    "Offset Text": "Puts the dimension text off to the side, with a leader.",
    "Display Options": "How the dimension is shown: as radius, diameter, centered...",
    "Center Dimension": "Keeps the dimension text centered between its extension lines.",
    "Reverse Direction": "Turns the direction the other way.",
    "OK": "Accepts the PropertyManager and closes it.",
    "Cancel": "Closes the PropertyManager without the changes.",
    "Reference Geometry Display": "Shows or hides planes, axes and points.",
    "Mark For Drawing": "Brings the dimension into drawings made of the part.",
    "Link Values": "Shares one value between several dimensions.",
    "Driven": "Makes the dimension follow the geometry instead of driving it.",
    "Material": "Picks the part's material.",
    "Default Display": "Puts the item back to the document's display.",
    "Reattach": "Attaches the annotation to another item.",
    "Up To Vertex": "Ends the feature at a picked point.",
    "Up To Surface": "Ends the feature at a picked face or plane.",
    "Up To Body": "Ends the feature at a picked body.",
    "Offset From Surface": "Ends the feature at a distance from a face or plane.",
    "Blind": "Ends the feature at a set depth.",
    "Mid Plane": "Builds the feature the same depth to both sides.",
    "Toggle Suppression": "Suppresses the item, or brings it back.",
    "Set Vertical": "Turns the dimension text upright.",
    "Jump to Parent View": "Picks the view this one was made from.",
    "Jump to Section View": "Picks the section view made from this line.",
    "Jump to Detail View": "Picks the detail view made from this circle.",
    "Align to edge": "Lines the item up with an edge.",
    "Sort": "Sorts the rows of the table.",
    "Revisions": "Adds or changes revisions in the revision table.",
    "Pin Dialog": "Keeps the PropertyManager open after OK.",
    "Manual View Label Text": "Types the view's label yourself.",
    "Hidden Tree Items": "Shows the tree items that are hidden.",
    "Formatting": "Font, alignment and the other text formats.",
    "Display As Radius": "Shows the dimension as a radius.",
    "Display As Diameter": "Shows the dimension as a diameter.",
    "Display As Linear": "Shows the circle's dimension as a linear dimension across it.",
    "Direction 2": "Builds the feature in the second direction too.",
    "Direction 2 Off": "Builds the feature in one direction only.",
    "Direction 1": "The first direction of the feature.",
    "Anchor": "Where the table is held on the sheet.",
    "Set as Anchor": "Makes this corner the table's anchor.",
    "Shell Outward": "Adds the wall thickness outside the faces.",
    "Keep trimmed entities as construction geometry": "Turns trimmed pieces into construction geometry instead of deleting them.",
    "Ignore trimming of construction geometry": "Leaves construction geometry out of trimming.",
    "Display Mesh": "Shows the mesh of the surface.",
    "Display Curvature": "Colors the surface by its curvature.",
    "Default": "Uses the default setting.",
    "Check Body/Faces": "Checks the geometry for errors.",
    "Table Header": "Puts the header at the top or bottom of the table.",
}

PATTERNS = (
    (r"^Edit (.+)$", "Opens the {0} to change it."),
    (r"^Hide (.+)$", "Hides the {0}."),
    (r"^Show (.+)$", "Shows the {0}."),
    (r"^Delete (.+)$", "Deletes the {0}."),
    (r"^Add (.+?)\.*$", "Adds {0}."),
    (r"^Insert (.+?)\.*$", "Inserts {0}."),
    (r"^Open (.+)$", "Opens {0}."),
    (r"^Select (.+)$", "Picks {0}."),
    (r"^(?:Feature|Component|Mate|Body|Sheet|View|Face|Edge|Folder|Sketch) \((.+)\)$", "The commands for {0}."),
)

_CATALOG = {}
HEAD = re.compile(r"^(?:(?:Selected Entity|Dimension|Table|Feature|Component|Mate|Body|Sheet|View|Face|Edge|Vertex|"
                  r"Folder|Sketch|Note|Balloon|Assembly|Part|Drawing) \(.+\)|Face|Edge|Vertex)$")


def _catalog():
    if not _CATALOG:
        try:
            from . import catalog
            for cmd in catalog._ALL:
                tip = getattr(cmd, "tip", None)
                if tip:
                    _CATALOG.setdefault(cmd.label.replace("&", "").rstrip("."), tip)
        except Exception as _fw_err:
            _fw_log("rctips.py:293", _fw_err)
    return _CATALOG


def _plain(text):
    return (text or "").replace("&", "").split("\t")[0].strip()


def _command_tip(name):
    try:
        cmd = Gui.Command.get(name)
        info = cmd.getInfo() if cmd is not None else None
    except Exception:
        info = None
    if not info:
        return ""
    tip = info.get("statusTip") or info.get("toolTip") or ""
    tip = re.sub(r"<[^>]+>", "", tip).strip()
    return tip.splitlines()[0] if tip else ""


# whole menus whose items share one line: {} is the item
MENU_TIPS = {
    "SWToolMenu_CommandManagerTabs": "Shows or hides the {} tab of the CommandManager.",
}


# FreeCAD's generic lines, which say nothing about the item (pkg231: our own line instead)
_LEFTOVER = re.compile(r"^(?:Toggles this dockable window|Opens a dialog to (?:record|execute) a (?:recorded )?macro)")


def _menu_line(action, menu, text):
    """pkg231: the menu bar's line: by the submenu it is in, then by its command (kept as the
    action's data), then by its text (menutips.py)."""
    try:
        from . import menutips
    except Exception as _fw_err:
        _fw_log("rctips.py:menutips", _fw_err)
        return ""
    parent = _plain(menu.title()) if menu is not None else ""
    base = text.rstrip(".").strip()
    tip = menutips.PLACE.get((parent, base))
    if tip:
        return tip
    shared = menutips.PARENT.get(parent)
    if shared and base and action.isCheckable():        # the toggles only (View > Toolbars > Customize... is a command)
        return shared.format(base)
    shared = getattr(menutips, "PARENT_ALL", {}).get(parent)
    if shared and base:
        return shared.format(base)
    name = action.data()
    if isinstance(name, str) and name:
        tip = menutips.COMMAND.get(name)
        if tip:
            return tip
    return menutips.LABEL.get(base, "")


def _data_command_tip(action, text):
    """The menu bar item's own command's tooltip, when nothing else describes it (pkg231)."""
    name = action.data()
    if not isinstance(name, str) or not name:
        return ""
    tip = _command_tip(name)
    if tip and tip.rstrip(".") != text.rstrip(".").strip() and not _LEFTOVER.match(tip):
        return tip
    return ""


def describe(action, menu=None):
    """The status bar line for a menu item, or ''."""
    text = _plain(action.text())
    own = action.statusTip()
    if own and own.rstrip(".") != text.rstrip(".") and not _LEFTOVER.match(own):
        return own
    if action.property("swHeading"):
        return ""
    text = re.sub(r"\s*\((?:\s*\w\s*|double-click)\)$", "", text)     # "Switch to arc ( A )", "End chain (double-click)"
    tip = _menu_line(action, menu, text)
    if tip:
        return tip
    shared = MENU_TIPS.get(menu.objectName() if menu is not None else "")
    if shared and text and text not in TIPS:
        return shared.format(text)
    if not text or text == "»":
        return "Shows every item of the menu." if text else ""
    if text in TIPS:
        return TIPS[text]
    name = action.property("swCommand") or ""
    if name:
        tip = _command_tip(name)
        if tip:
            return tip
    catkey = action.property("swCatKey")
    if isinstance(catkey, str) and catkey:
        # tooltips-1126: a menu bar row from a catalog entry says that entry's line; the label lookup below
        # would find the first entry with the same label (Insert > Cut > Revolve said "Freeshape Revolve")
        try:
            from . import catalog
            entry = catalog.BY_KEY.get(catkey)
            tip = getattr(entry, "tip", None) if entry is not None else None
        except Exception as _fw_err:
            _fw_log("rctips.py:catkey", _fw_err)
            tip = None
        if tip:
            return tip
    tip = None if isinstance(catkey, str) and catkey else _catalog().get(text.rstrip("."))
    if tip:
        return tip
    if text.rstrip(".") in TIPS:
        return TIPS[text.rstrip(".")]
    tip = _data_command_tip(action, text)
    if tip:
        return tip
    if action.toolTip() and _plain(action.toolTip()) != text:
        return _plain(action.toolTip()).splitlines()[0]
    for pat, out in PATTERNS:
        m = re.match(pat, text)
        if m:
            return out.format(m.group(1))
    return ""


def _bar():
    try:
        return Gui.getMainWindow().statusBar()
    except Exception:
        return None


def _show(action):
    """The pointer is on action: its line in the status bar (Qt's own status tip does not reach the
    main window from a shortcut menu opened over the 3D view or a pane)."""
    bar = _bar()
    if bar is None:
        return
    tip = action.statusTip() if action is not None else ""
    if tip:
        bar.showMessage(tip)
    else:
        bar.clearMessage()


def _clear():
    bar = _bar()
    if bar is not None:
        bar.clearMessage()


def apply(menu):
    """Status tips on every item of menu (submenus get theirs as they are decorated)."""
    missing = []
    for a in menu.actions():
        if a.isSeparator() or not a.text() or a.property("swHeading") or (
                HEAD.match(_plain(a.text())) and not a.isCheckable()):      # pkg231: View (Heads-Up) is a toolbar toggle
            continue
        tip = describe(a, menu)
        if tip:
            a.setStatusTip(tip)
        else:
            missing.append(_plain(a.text()))
    if not menu.property("swTipsHooked"):
        menu.setProperty("swTipsHooked", True)
        menu.hovered.connect(_show)
        menu.aboutToHide.connect(_clear)
    path = os.environ.get("FW_RC_TIPS")
    if path and missing:
        try:
            with open(path, "a") as f:
                f.write("%s\t%s\n" % (menu.objectName(), "|".join(missing)))
        except Exception as _fw_err:
            _fw_log("rctips.py:401", _fw_err)
    chev = os.environ.get("FW_RC_CHEV")
    if chev and menu.property("swLong") is not None:
        try:
            labels = ["-" if a.isSeparator() else _plain(a.text()) for a in menu.actions()]
            with open(chev, "a") as f:
                f.write("%s\t%s\t%s\n" % (menu.objectName(), "long" if menu.property("swLong") else "short",
                                          "|".join(labels)))
        except Exception as _fw_err:
            _fw_log("rctips.py:410", _fw_err)
    return missing
