# Install, update, or remove

Use stock FreeCAD **1.1.4**. This alpha was tested on Windows. macOS and Linux are untested.

## Addon Manager

Use the manual installation steps below for this alpha.

## Manual install

1. Download **FreeWorks-0.3.1-alpha.zip** from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.1-alpha).
2. Close FreeCAD. Extract the add-on into your user `Mod` folder as `FreeWorks`. Check that `InitGui.py` sits directly inside `Mod/FreeWorks`.
3. Restart FreeCAD.

| Operating system | User `Mod` folder |
| --- | --- |
| Windows | `%APPDATA%\FreeCAD\Mod` |
| macOS | Locate it using the Python console as described below. |
| Linux | `~/.local/share/FreeCAD/Mod` |

To find your user folder, enter `App.getUserAppDataDir()` in the FreeCAD Python console and look for the `Mod` folder inside that path.

## First launch

Open FreeCAD and choose **Set Up FreeCAD** when the Welcome box offers it. Open a part and follow the [first sketch walkthrough](../README.md#first-15-minutes).

## Update

In 0.3.1-alpha, open **Options > General > Software updates** and set the repository to PlasticBuild/FreeWorks. When FreeWorks offers an update, accept it and restart FreeCAD to apply it. You can turn off checks or roll back from the same page.

For a manual update, close FreeCAD, keep a backup of your installed FreeWorks folder, and copy in the new release. Restart FreeCAD.

## Uninstall and restore toolbars

1. Use the add-on’s **Uninstall** button to restore the stock toolbars.
2. If a stock toolbar is still missing, right-click the toolbar area and re-tick the toolbars you want to show.
