# FreeWorks 0.3.2-alpha

FreeWorks gives stock FreeCAD a familiar mainstream-CAD look and feel: a command ribbon, property panels for the
features, a feature tree with a rollback bar, sketch tools with inference snapping and automatic relations, assemblies,
drawings, simulation and more. It is a pure Python add-on; FreeCAD itself is not changed. Inside the program it is
simply called FreeCAD; "FreeWorks" is the name of this add-on and its folder.

This is the **0.3.2-alpha public alpha**. Download the install ZIP from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.2-alpha) and follow the manual install steps below.

## What you need

- **FreeCAD 1.1.4**, the official build from freecad.org (Windows installer or portable zip). 1.1.0 or newer should work,
  but 1.1.4 is what this alpha is tested on. Windows is the main test system; Linux has had less testing and macOS has not
  been tested.
- **Graphics:** OpenGL 2.1 or newer (any graphics card or integrated graphics from about 2010 on, with a current driver).
  On older graphics, FreeCAD 1.1 itself crashes at start, with or without this add-on.
- Less than 100 MB of disk space, and write access to your FreeCAD user folder.
- Nothing else. No slicer, no other program and no other add-on is needed (see "Optional downloads").

## Install (by hand, on a fresh profile)

Use a fresh FreeCAD profile, so that your own settings are not mixed up with the alpha and you can go back to them.

1. Close FreeCAD.
2. Keep your own settings: rename the folder `%APPDATA%\FreeCAD` to `FreeCAD-mine`. FreeCAD makes a new, empty one the next time it starts. (If you have never used FreeCAD on this computer there is nothing to rename.)
3. Start FreeCAD 1.1.4 once and close it, so that the new profile exists.
4. Unpack the zip. You should have a folder called `FreeWorks` with `InitGui.py` directly inside it. If the zip made a folder with another name, such as `FreeWorks-main`, rename it to `FreeWorks`.
5. Move that folder to `%APPDATA%\FreeCAD\Mod\FreeWorks`. Create `Mod` if it is not there. Not sure where your user folder is? In FreeCAD's Python console (View, Panels, Python console) type `App.getUserAppDataDir()` and press Enter.
6. Start FreeCAD. The first start takes a few seconds longer while FreeCAD compiles the add-on's files. On a new profile the Welcome box opens with **Set Up FreeCAD** on it (Theme, Language, Units, Dimension standard, Mouse navigation): pick what you use and press Done. If FreeCAD's own first-start page appears first instead, it offers the same FreeCAD Light and FreeCAD Dark themes: choose one there. The window then changes to the ribbon layout.
7. Press Ctrl+N to start a part, an assembly or a drawing. Press **F1** at any time for the page of the built-in guide that fits what you are doing (Help, User Guide opens the contents).

New here? `FIRST-15-MINUTES.md` is a one-page walk-through that starts with sketch snapping and relations, and `QUICKSTART-ALPHA.md` takes you from install to a first part.

## What is in this alpha besides modelling

- **Design Library** (task pane tab): a folder tree you can search, with Add to Library for parts, components and features. A library feature drops onto a face of another part, and one Undo takes it back. Parts drop into an assembly where you let go.
- **Toolbox** (inside the Design Library): ANSI Inch, ANSI Metric, DIN and ISO screws, bolts, nuts, pins and washers. Drop a fastener on a hole and it is sized from the hole; Smart Fasteners fills every hole in an assembly.
- **MBD** (3D annotations on the model): dimensions, datums, geometric tolerances, notes, surface finish and weld symbols; tolerance status and stack-up in the document's unit; Publish to PDF and to STEP with the annotations.
- **Weld cut list, Hole data, Material, Molds:** lengths, angles and weights per weld profile; standard tap-drill sizes; a material library with density for mass; Parting Line, Shut-Off Surfaces, Parting Surface and Tooling Split.
- **Opening and saving files:** a file that cannot be opened (moved, damaged, or not what its name says) gets a box that names it and says why, and the other files still open. Open and the first Save As start in the folder you used last. Save As will not write over a file that is open in FreeCAD, and a failed save says why. Open read-only lasts for the session only. While a file is open, FreeCAD keeps a small hidden `.~$<name>.lck` file beside it; a file that is open elsewhere opens read-only, and Save asks before it overwrites a file that changed on disk.
- **ScanRuler:** a tab that opens a web tool for 3D scans in your browser, and sends a part (STEP) or a mesh (STL) to it. It needs a network connection.

## Optional downloads (not in this zip)

The slicers and Diotopo are not part of this download. Each is a separate program, fetched only when you ask, and everything
else works without them. Do not download them unless you want to test them.

- **Slicers** (Orca Slicer, Bambu Studio, PrusaSlicer): the 3D Slicer tab, Slicer Updates.
- **Diotopo** (topology optimisation, by its own author): Tools, Add-Ins, Download Diotopo... A box explains what it fetches; the default answer is No.
- Diotopo downloads with a progress box and a Cancel button; a failed or cancelled download installs nothing and says how to try again.
- Downloads are kept in FreeCAD's user data folder, with a slicer's own settings beside it. A slicer you already have installed is not touched.

## How to report a problem

Send these to **[GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues)**:

1. What you did, step by step, and what you expected to happen.
2. What happened instead, with a screenshot.
3. The lines in View, Panels, Report view: right-click it and switch on Log messages first, repeat the step, and copy the lines that mention an error or that start with "FreeWorks".
4. Your FreeCAD version (Help, About FreeCAD), your Windows version and the add-on version: **0.3.2-alpha**.
5. If it needs a file to repeat, a small file that shows it (please do not send models that are confidential).

The list of problems already known is in `KNOWN-ISSUES.md`; check it first.

If FreeCAD does not start, a box asks for a download, you have no network, or you want to reset or remove the add-on, see `TROUBLESHOOTING-ALPHA.md`.

## How to remove it

**On a fresh profile (recommended).** Close FreeCAD. Delete the new `%APPDATA%\FreeCAD` folder, then rename `FreeCAD-mine` back to `FreeCAD`. Your own FreeCAD is exactly as it was.

**Without a fresh profile.** Take care: deleting the folder by hand does **not** run the add-on's uninstall step, so FreeCAD's own settings are not put back. FreeCAD's toolbars come back by themselves, because the add-on shows them again each time FreeCAD closes; if they are ever missing, see `TROUBLESHOOTING-ALPHA.md`, "FreeCAD starts with no toolbars at all".
- Close FreeCAD normally first (the add-on puts FreeCAD's toolbars back each time it closes), then delete `%APPDATA%\FreeCAD\Mod\FreeWorks`.
- Some FreeCAD settings that the add-on changed (sketcher options, theme colours, shortcuts, units and a few others) stay as the add-on left them. The values from before the add-on are kept in `%APPDATA%\FreeCAD\FreeWorks\stock-baseline.json`, which stays after you delete the add-on. Do not delete it until you are sure you do not need it.
- Your documents are ordinary FreeCAD files and open in any FreeCAD.

## Licence

LGPL-2.1-or-later, see `LICENSE`. Third-party parts and their licences are listed in `THIRD-PARTY.md`.
