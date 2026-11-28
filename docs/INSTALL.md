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
`git clone https://github.com/PlasticBuild/FreeWorks.git "%APPDATA%\FreeCAD\v1-1\Mod\FreeWorks"` on Windows (see the table below for other folders). Run `git pull` in that folder to update, with FreeCAD closed. See [Install from source](../README.md#install-from-source) for more detail.

## Windows installer (optional)

Each release can also carry **FreeWorks-0.4.0-alpha-Setup.exe**. It asks your FreeCAD where its user `Mod` folder is, usually `%APPDATA%\FreeCAD\v1-1\Mod`, and installs the add-on there as `FreeWorks` for your Windows user only. You need no administrator rights. If a `FreeWorks` folder is already there, setup moves it aside as a backup and does not delete it. It needs FreeCAD 1.1 to be installed already, and it never installs, changes, or removes FreeCAD itself. To remove the add-on, use **FreeWorks add-on for FreeCAD** in Windows Settings > Apps.

## Manual install

1. Download **FreeWorks-0.4.1-alpha.zip** from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.4.1-alpha). The zip is built from the tagged source in this repository.
2. Close FreeCAD. Extract the add-on into your user `Mod` folder as `FreeWorks`. Check that `InitGui.py` sits directly inside `Mod/FreeWorks`.
3. Restart FreeCAD.

| Operating system | User `Mod` folder |
| --- | --- |
| Windows | `%APPDATA%\FreeCAD\v1-1\Mod` (older profiles: `%APPDATA%\FreeCAD\Mod`) |
| macOS | Locate it using the Python console as described below. |
| Linux | `~/.local/share/FreeCAD/v1-1/Mod` (older profiles: `~/.local/share/FreeCAD/Mod`) |

To find your user folder, enter `App.getUserAppDataDir()` in the FreeCAD Python console and look for the `Mod` folder inside that path.

## First launch

Open FreeCAD and choose **Set Up FreeCAD** when the Welcome box offers it. Open a part and follow the [first sketch walkthrough](../README.md#first-15-minutes).

## Update

In FreeWorks, open **Options > General > Software updates** and set the repository to PlasticBuild/FreeWorks. When FreeWorks offers an update, accept it and restart FreeCAD to apply it. You can turn off checks or roll back from the same page.

For a manual update, close FreeCAD, keep a backup of your installed FreeWorks folder, and copy in the new release. Restart FreeCAD.

## Uninstall and restore toolbars

1. Use the add-on’s **Uninstall** button to restore the stock toolbars.
2. If a stock toolbar is still missing, right-click the toolbar area and re-tick the toolbars you want to show.
