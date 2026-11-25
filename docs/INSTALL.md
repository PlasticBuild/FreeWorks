# Install, update, or remove

Use stock FreeCAD **1.1.4**. This alpha was tested on Windows. macOS and Linux are untested.

## Addon Manager

FreeWorks is not in the official Addon Manager list yet, so add this repository as a custom repository first.

1. In FreeCAD, open **Edit > Preferences > Addon Manager**.
2. Under **Custom repositories**, add the URL `https://github.com/PlasticBuild/FreeWorks` with the branch `main`, then press OK.
3. Open **Tools > Addon Manager**, find **FreeWorks**, and choose **Install**.
4. Restart FreeCAD.

## Install from source

Clone the repository into your user `Mod` folder as `FreeWorks`, for example
`git clone https://github.com/PlasticBuild/FreeWorks.git "%APPDATA%\FreeCAD\Mod\FreeWorks"` on Windows. Run `git pull` in that folder to update, with FreeCAD closed. See [Install from source](../README.md#install-from-source) for more detail.

## Manual install

1. Download **FreeWorks-0.3.3-alpha.zip** from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.3-alpha). The zip is built from the tagged source in this repository.
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

In FreeWorks, open **Options > General > Software updates** and set the repository to PlasticBuild/FreeWorks. When FreeWorks offers an update, accept it and restart FreeCAD to apply it. You can turn off checks or roll back from the same page.

For a manual update, close FreeCAD, keep a backup of your installed FreeWorks folder, and copy in the new release. Restart FreeCAD.

## Uninstall and restore toolbars

1. Use the add-on’s **Uninstall** button to restore the stock toolbars.
2. If a stock toolbar is still missing, right-click the toolbar area and re-tick the toolbars you want to show.
