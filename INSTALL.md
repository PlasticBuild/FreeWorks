# Installing (alpha)

Requires stock **FreeCAD 1.1.4** (1.1.0 or newer should work). Windows is the main test system.

1. Close FreeCAD. To keep your own settings, rename `%APPDATA%\FreeCAD` to `FreeCAD-mine` (a fresh profile is recommended).
2. Start FreeCAD once and close it, so the new profile exists.
3. Download [FreeWorks-0.3.1-alpha.zip](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.1-alpha) and unpack it.
4. Rename the unpacked folder to exactly `FreeWorks` (GitHub zips unpack as `FreeWorks-main`). `InitGui.py` must sit directly inside it.
5. Move it to your FreeCAD user folder: `%APPDATA%\FreeCAD\Mod\FreeWorks` on Windows, `~/.local/share/FreeCAD/Mod/FreeWorks` on Linux. Not sure where it is? In FreeCAD's Python console type `App.getUserAppDataDir()`.
6. Start FreeCAD. The first start takes a little longer; the Welcome box offers Set Up FreeCAD.

Slicers (Orca Slicer, Bambu Studio, PrusaSlicer) and Diotopo are **not** included. Each is an optional download from inside FreeCAD, only when you ask for it.

**Removing:** close FreeCAD and delete the `FreeWorks` folder. Deleting by hand does not restore FreeCAD's own layout settings; rename `FreeCAD-mine` back to `FreeCAD` to return to your old profile. See `TROUBLESHOOTING-ALPHA.md` and `KNOWN-ISSUES.md`.
