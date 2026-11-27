# FreeWorks

FreeWorks gives stock FreeCAD a familiar mainstream-CAD look and feel: a command ribbon with Features,
Sketch, Surfaces, Sheet Metal, Weldments and Evaluate tabs, property panels for the features, a feature tree
with a rollback bar, a view selector, and sketch tools with inference snapping, automatic relations and smart
dimensions. It is a pure Python add-on; FreeCAD itself is not changed.

## Requirements

- FreeCAD 1.1.0 or newer (developed and tested on 1.1.4, Windows and Linux).
- Optional, for the Sheet Metal and Weldments tabs: the SheetMetal and FrameForge add-ons from the Addon Manager.

## Install

Addon Manager: Tools, Addon Manager, search for FreeWorks, Install, restart FreeCAD.

By hand: copy this folder to `Mod/FreeWorks` inside your FreeCAD user data folder
(on a new FreeCAD 1.1 profile: Windows `%APPDATA%\FreeCAD\v1-1\Mod`, Linux `~/.local/share/FreeCAD/v1-1/Mod`; `App.getUserAppDataDir()` in the Python console shows yours)
and restart FreeCAD.

FreeWorks restyles the main window at every start. To go back to plain FreeCAD, uninstall it in the Addon
Manager or remove the folder; your documents are ordinary FreeCAD files and open without it.

## Settings

Edit, Options opens the FreeWorks options (sketch snapping, relations, colours, keys, display). Settings are
stored under `BaseApp/Preferences/Mod/FreeWorks` in your FreeCAD user settings.

## Licence

LGPL-2.1-or-later, see LICENSE. The icons in `icons/` are original drawings under the same licence.
