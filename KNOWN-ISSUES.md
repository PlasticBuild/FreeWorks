# Known issues in this alpha

This list names what testers are likely to meet, not every bug. If you find something that is not here, please report it
(see README). Each line says where it happens, what you will see, and what to do instead.

## Installing and removing
- **Removing by hand:** deleting the add-on's folder does not run its uninstall step, so some FreeCAD settings stay changed. Use a fresh profile (see README) and delete it when you are done. FreeCAD's own toolbars stay in place after a normal close; if FreeCAD was ever closed by a crash while the add-on was on, it may start with none: see TROUBLESHOOTING-ALPHA.md.
- **First start:** slower, while FreeCAD compiles the add-on's files.
- **Systems:** Windows is the main test system. Linux has had less testing, and macOS has not been tested.

## Guide and help
- The built-in guide has no pictures yet. F1, the "?" on panels and the Help buttons open its pages. If a step does not match what you see, please report it.

## Sketching
- **Fully Define Sketch on a very large sketch** (hundreds of lines): it can take 20 to 30 seconds before anything changes. Wait for it, or pick part of the sketch first.

## Features, sheet metal and weldments
- **Fillet on surface bodies:** the Fillet panel offers Constant Size (with Multi Radius Fillet) and Face Fillet only (no Variable Size, Full Round, setback or conic profile on surfaces). Knit the surfaces into a solid first (Knit Surface, Create solid) and fillet the solid.
- **Structural Member in a metric part:** the Standard list may open on "ansi inch" (the opening default, or your last choice). Choose iso (or your standard) first, then Type and Size.

## Assemblies and Motion Study
- **Intel graphics:** Edit Component, Lock All or closing External References can leave FreeCAD not responding for a minute or more. Set FreeCAD.exe to the dedicated GPU (Windows Settings, Display, Graphics) and wait; nothing is lost. Under investigation.
- **Basic Motion and Motion Analysis** move only a component that turns or slides on a mate to a fixed component; a free component stays where it is. Mate it first (Hinge, Concentric), or use an Animation study.

## Simulation
- **Large parts with many small holes** can take several minutes to mesh and solve. Coarsen the mesh first (right-click Mesh, Create Mesh..., move the slider toward Coarse).
- **Mesh, Fixtures and Study Properties panels** get only the top half of the left pane, so some boxes sit below the fold. Scroll the panel, or drag the splitter down.
- **Force panel:** one arrow is drawn at the middle of each picked face; the load is still spread over the whole face.
- **Connectors and contact** (Local Interactions, Component Interaction, Connectors) are new and lightly tested on real assemblies. Check the result and report any setup that will not solve.

## Design Library, Toolbox, MBD and other tabs
- **ScanRuler and Diotopo** need a network connection and the author's GitHub page for their first download; there is no offline copy.
- **Weldments:** ANSI inch profile types and sizes, and a few inch default tolerances, are still waiting on a check against published tables, so they may differ.
- **Toolbox:** the label of the inch pan head screw may be reworded. On a 1366 x 768 screen the Fastener panel starts with Part Numbers closed.
- **New in this alpha, least tested:** MBD in inch parts, and the ScanRuler and Diotopo tabs. Please report anything odd there.

## Drawings
- **Geometric Tolerance** is built from the panel's symbol and value boxes; there is no step-by-step popup. Pick the symbol, type the tolerance and datums, then click the sheet.

## View and display
- **Level of detail** (Options, Performance): while you turn, pan or zoom an assembly, small components are drawn as grey outline boxes and come back when the view stops. Move the slider to Off to keep every component drawn.

## 3D printing and files
- **No slicer is included.** The first time, FreeCAD offers to download Orca Slicer, Bambu Studio or PrusaSlicer (internet needed). Accept the download. A slicer already installed on your computer is not used by the 3D Slicer tab; to keep the printers and presets of one you already have, tick "Use my installed slicer's settings" in Slicer Updates.
- **Sending a job to a printer** needs a sign-in inside the slicer, and FreeCAD asks before anything is sent. Slicing and saving G-code work without it.
- **File formats:** Inventor, CATIA V5, Fusion 360, Rhino, Creo View and ACIS files are not listed in Open or Import, because they need a converter that is not included, and Save As has no Rhino type. Exchange those files as STEP. Other part and assembly file types appear under Save As only when the program that owns them is installed; they still open.
- **Save As:** there is no Parasolid (x_t) type. Use STEP AP242.
- **Opening a DXF:** the first DXF opened in a session may fail once; FreeCAD retries by itself. FreeCAD 1.1's own DXF Import box sometimes fails to build on the first DXF of a session and shows an error that mentions `QWidgetItem` and `toggled` or `setText`. That is an upstream FreeCAD fault and comes and goes (about 1 run in 4 on our bench). FreeCAD now tries once more without showing anything; if you still see the error, open the file again, and the second try works. Please report it, with the DXF.
- **Lock files:** while a .FCStd is open, FreeCAD keeps a small hidden file named `.~$<name>.lck` beside it and removes it when the file closes, so you may see it if you show hidden files (do not send it with a report). A file that is open somewhere else opens read-only, with a File In Use box; Save asks before it overwrites a file that changed on disk (the default answer is No).

## Please also tell us
- Anything that looks like a dead control: a button that is greyed out and should work, or does nothing when clicked.
- Anything that differs from what the built-in guide says.
