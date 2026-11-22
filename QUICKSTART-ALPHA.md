# Quick start (public alpha)

Ten minutes from install to your first part. The full walk-through (bracket, assembly, drawing) is in the built-in guide: press **F1**, or Help, User Guide, "Your first hour".

## 1. Install

The long version, with every step, is in `README.md`. In short:

1. Close FreeCAD. Rename `%APPDATA%\FreeCAD` to `FreeCAD-mine` (your own settings, kept safe).
2. Start FreeCAD 1.1.4 once, then close it.
3. Put the `FreeWorks` folder (the one with `InitGui.py` directly inside) into `%APPDATA%\FreeCAD\Mod\`.
4. Start FreeCAD. The first start is slower, because FreeCAD compiles the add-on's files.

You need OpenGL 2.1 or newer (any graphics from about 2010 on, with a current driver).

## 2. First start

1. The **Welcome** box opens alone, with **Set Up FreeCAD** on it: Theme, Language, Units, Dimension standard and Mouse navigation. Pick what you use, then **Done**. (You can change all of these later in Options.)
2. Choose the Light or the Dark theme here; the Welcome follows your choice at once.

## 3. Your first part

1. **Part** on the Welcome row (or Ctrl+N, Part, OK). The tree shows History, Sensors, Annotations, Material, Front Plane, Top Plane, Right Plane and Origin. The status bar says "Editing Part".
2. Click **Front Plane** in the tree, then **Sketch** on the pop-up toolbar. The view turns to face the plane.
3. **Corner Rectangle** on the Sketch tab: click the origin, move up and to the right, click. Look at the small square beside the pointer: it shows the relation the next click will add. You never add the horizontal and vertical relations by hand.
4. **Smart Dimension**: click a side, click where the number should sit, type 60, Enter. Do the same for the other side. When nothing can move the lines turn black and the status bar says **Fully Defined**.
5. **Exit Sketch** (the confirmation corner, top right of the view, or the Sketch tab).
6. **Extruded Boss/Base** on the Features tab. Type a depth (for example 10), press Enter. The tree shows a **Solid Bodies** folder with **Boss-Extrude1** in it, and its sketch under that.
7. Ctrl+S saves the part: a box asks for a name (it suggests the part's own name, Part1). Type one and save. Ctrl+Z takes the last feature back; each feature is one undo step.

## 4. Your second day: open it again

1. Open the file from the Welcome's Recent Documents (or File, Open).
2. In the tree, click **Sketch1**, then **Edit Sketch**. Change a dimension (60 to 80), then Exit Sketch: the part rebuilds.
3. Pick an edge, then **Fillet**. Type a radius, Enter.
4. File, Make Drawing from Part: pick a sheet size and OK, and the Model View panel and the View Palette open beside the sheet. Pick **Front** and click on the sheet to place the first view.

## 5. When something goes wrong

Please report it. Send these to **[GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues)**:

1. What you did, step by step, and what you expected.
2. What happened instead, with a screenshot.
3. The lines in View, Panels, Report view (right-click it, switch on Log messages, repeat the step, copy the lines that mention an error or start with "FreeWorks").
4. Your FreeCAD version (Help, About FreeCAD), your Windows version and the add-on version **0.3.2-alpha**.
5. A small file that shows it, if it needs one (not a confidential model).

Check `KNOWN-ISSUES.md` and `TROUBLESHOOTING-ALPHA.md` first. If you are stuck, save your work, close FreeCAD and start it again: nothing else needs resetting.
