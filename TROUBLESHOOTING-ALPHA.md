# Troubleshooting (public alpha)

If your problem is not here, report it (see `README.md`, "How to report a problem", or `FEEDBACK-TEMPLATE.md`). Save your work first and close FreeCAD normally before trying any of these: the add-on puts FreeCAD's toolbars back each time FreeCAD closes.

## FreeCAD does not start, or closes at once, or the window stays black
FreeCAD 1.1, with or without this add-on, needs **OpenGL 2.1 or newer**. Almost every graphics chip from about 2010 on has it, with a current driver. On older graphics, FreeCAD itself crashes while starting. What to try:
1. Update the graphics driver (from the maker of your graphics card or of the computer).
2. Use the computer's own screen: a remote desktop session or a virtual machine often offers only OpenGL 1.x.
3. Start FreeCAD without the add-on to be sure which one is at fault: rename `%APPDATA%\FreeCAD\Mod\FreeWorks` to `FreeWorks-off` while FreeCAD is closed, and start FreeCAD. If it still closes, the cause is the graphics, not the add-on. Rename the folder back afterwards.
4. If it only fails with the add-on: report it, with your graphics card and driver version.

## A box asks to set up a small helper (pywin32)
It shows only on Windows, when **another CAD program is installed on the same computer** and what you are doing needs it: a file whose shape FreeCAD cannot read by itself, an assembly tree or its mates, or saving in that program's format. Opening any other file never shows it. The box says FreeCAD talks to that program through a small helper (pywin32, about 10 MB, downloaded once from the Python Package Index) and asks "Set it up now?"; Yes is the default.
- You do not need it for anything else. Modelling, sketching, assemblies, drawings and the guide work without it.
- Answer **No** if you are not testing that feature. Nothing is downloaded and no folder is made. The Report view gets a warning that no Python with pywin32 was found, and the box does not come back until you restart FreeCAD.
- If you answered Yes with no network, the Report view says that setting up the helper failed, with the installer's own output. The rest of FreeCAD is not affected. A file whose shape could be read without the helper still opens, with a warning; a file that needs the helper does not open. Connect, restart FreeCAD and open the file again to be asked again.

## Diotopo and the slicers, with no network
They are optional downloads and nothing downloads by itself.
- **Slicer Updates** (on the 3D Slicer tab), **Check Now**: with no connection it says "Could not reach the release pages (is there a network connection?). Nothing was changed; try again later." A slicer you already have is not changed.
- **Tools, Add-Ins**: the daily update check reads "no connection to GitHub" when offline, or "GitHub is limiting requests, try again later". **Download Diotopo...** asks first, and the default answer is No.
- A slicer download shows its size on the button ("Download 2.3.1 (128 MB)") and the button reads **Cancel** while it runs. If the free disk space is too little it says how much is needed and does not start. A download that stops half way says so ("the download stopped at 3 MB of 6 MB (the connection was lost)... press Download to try again"); a cancelled or failed download leaves no partial file, so press Download again.
- Diotopo's download shows a progress box with a Cancel button. If it fails, the box says "the download failed (no connection to GitHub)" and to choose Diotopo again to try again; nothing is installed.
- Everything else works with no network. Only the downloads need one; ScanRuler needs one to open its page.

## A file will not open, or will not save
- **Open says a file was not found, is damaged, or has nothing to read:** the box names the file and the reason. A file that moved or was renamed can be browsed to again; a damaged FreeCAD file may still open with what could be read ("Keep what was read with Save As under a new name"); an empty mesh file says it has no triangles. Backup files (.FCBak, .FCStd1) open as FreeCAD files.
- **Save As says a file "is open in FreeCAD":** you chose the name of another open document. Close that document first, or save under a different name; nothing was written.
- **Save says why it could not write:** check that the folder can be written to and that the file is not open in another program (a file locked on Windows lands here). A read-only document refuses Save: use Save As. Save All skips read-only documents and saves the rest.
- **A box says the file is in use, or a file opens read-only:** another copy of FreeCAD (or another computer) has it open. FreeCAD marks an open file with a hidden `.~$<name>.lck` file beside it and removes it when the file closes. Close it there and open it again; if you need to keep changes made in the read-only copy, use Save As under a new name.
- **Save asks about overwriting:** the file changed on disk after you opened it. The default answer is No; use Save As to keep both.
- **A STEP or IGES comes in as Imported1, Imported2...:** that is the name FreeCAD gives an imported body. A mesh file (STL, OBJ) is read in millimetres unless you set Options, Import, Mesh body options, Unit.

## Reset the profile (go back to a clean start, keep the add-on)
Use this when something looks wrong after you changed many settings, or after a crash.
1. Close FreeCAD.
2. Rename `%APPDATA%\FreeCAD` to `FreeCAD-broken` (do not delete it).
3. Start FreeCAD once and close it. FreeCAD makes a new, empty profile.
4. Copy the folder `Mod\FreeWorks` from `FreeCAD-broken` into the new `%APPDATA%\FreeCAD\Mod\` (or unpack the zip there again; see the README install steps).
5. Start FreeCAD. You get the first-start Welcome with Set Up, as on a new computer.
Your documents are ordinary FreeCAD files and are not in the profile. Keep `FreeCAD-broken` until you have what you need from it, for example your recent files list or your own macros.

## Uninstall
- **If you installed on a fresh profile (recommended in the README):** close FreeCAD, delete the new `%APPDATA%\FreeCAD`, rename `FreeCAD-mine` back to `FreeCAD`. Your own FreeCAD is exactly as before.
- **If you installed in your own profile:** use the Addon Manager's **Uninstall** button if the add-on is listed there (it runs the add-on's own uninstall step). Otherwise close FreeCAD normally, then delete `%APPDATA%\FreeCAD\Mod\FreeWorks`. Deleting by hand does not run the add-on's uninstall step, so some FreeCAD settings the add-on changed (sketcher options, theme colours, shortcuts, units and a few others) stay as the add-on left them. The values from before are in `%APPDATA%\FreeCAD\FreeWorks\stock-baseline.json`, which stays: do not delete it until you are sure you do not need it.
- Slicers or Diotopo you downloaded are in FreeCAD's user data folder, beside the add-on's settings; they are not removed with the add-on. A slicer you installed yourself is never touched.

## FreeCAD starts with no toolbars at all
A normal removal no longer causes this: the add-on shows FreeCAD's own toolbars again each time FreeCAD closes normally, so they are saved as showing. This works once FreeCAD has been closed normally at least once with the add-on installed. It can still happen if FreeCAD only ever ended by a crash or by being killed while the add-on was on, and the add-on was removed afterwards. To get the toolbars back:
- Right-click the empty toolbar area and tick the toolbars you want (File, Edit, View and so on); or
- put the add-on back, start FreeCAD once, and use the Addon Manager's **Uninstall** button (this also puts FreeCAD's settings back), then close FreeCAD normally.
Nothing is lost: your documents and settings are still there.

## Where things are
- The Report view: View, Panels, Report view. Right-click it and switch on **Log messages** to see more.
- The built-in guide: **F1**, or Help, User Guide.
- Your user folder: in FreeCAD's Python console (View, Panels, Python console) type `App.getUserAppDataDir()` and press Enter.
