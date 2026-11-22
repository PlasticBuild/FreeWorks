# FreeWorks — FreeCAD add-on

[![Donate on Ko-fi](https://img.shields.io/badge/Donate-Ko--fi-FF5E5B?style=for-the-badge)](https://ko-fi.com/plasticbuild)

**0.3.3-alpha · FreeCAD 1.1.4 · Windows**

**Like the SOLIDWORKS interface and want to work in FreeCAD?** FreeWorks brings a familiar commercial-CAD workflow to stock FreeCAD 1.1.4, from the first sketch through parts, assemblies, and drawings.

FreeWorks is an independent add-on for FreeCAD. Install it into your existing FreeCAD setup. The application still appears as **FreeCAD**.

[**Download FreeWorks 0.3.3-alpha**](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.3-alpha)

0.3.3-alpha fixes CommandManager tabs for workbenches that load after startup, including SubD. See the [release notes](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.3-alpha) for details and known issues.

The icons in this alpha are AI-generated and inspired by SOLIDWORKS icons.

[Download the six-column icon comparison PDF](https://raw.githubusercontent.com/PlasticBuild/FreeWorks/main/docs/FreeWorks-Icon-Comparison.pdf)

## What you can try

| Area | Workflow |
| --- | --- |
| Interface | Find commands on ribbon-style tabs, edit feature settings in task panels, and step through the model with the feature tree and rollback bar. Light and dark themes are available. |
| Sketching | Snap to endpoints, midpoints, and centres. Use inference lines and automatic relations as you draw, then set sizes with Smart Dimension. |
| Part modelling | Turn sketches into parts with extrudes, revolves, sweeps, and lofts. Refine them with fillets, holes, patterns, and mirrors. |
| Assemblies | Insert components and position them with mates. Check for interference or create an exploded view. |
| Drawings | Create projected, section, and detail views, add dimensions and annotations, and export to PDF or DXF. |

Sketching is the best place to start. The walkthrough below takes you from a snapped rectangle to an extruded part. This is an early alpha, so expect rough edges and verify results before relying on them.

## Screenshots

![FreeWorks part workspace showing the bearing mount, ribbon, feature tree, and rollback bar](docs/images/freeworks-part-alpha1.png)

![FreeWorks sketch editor showing the shaded bearing mount profile](docs/images/freeworks-sketch-alpha1.png)

## Requirements and quick install

- Use stock FreeCAD **1.1.4**. Windows has been tested. Other operating systems are untested.
- Download **FreeWorks-0.3.3-alpha.zip** from [GitHub Releases](https://github.com/PlasticBuild/FreeWorks/releases/tag/v0.3.3-alpha), then follow the [manual installation guide](docs/INSTALL.md).

Orca, Bambu, PrusaSlicer, and Diotopo are optional in-app downloads. Each is downloaded separately. The add-on package excludes all four.

## First 15 minutes

1. Open a new part, select a plane, and open a sketch.
2. Draw a rectangle. Start a line near a corner or the midpoint of an edge and watch the snap cue. Move the pointer horizontally or vertically to see the inference line and relation appear as you draw.
3. Remove the practice line so the rectangle is the only profile. Use Smart Dimension on two adjacent edges and enter their lengths in the Modify box.
4. Exit the sketch, select the rectangle sketch, and use Extrude. Enter a depth and accept the preview.

## Status · 0.3.0-alpha1

These notes cover 0.3.0-alpha1. Everyone is welcome to report bugs, suggest features, or share feedback in [GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues). See the [feedback guide](docs/FEEDBACK.md) for what to include.

### Known problems

- **Parting Surface.** The Sharp and Smooth corner options leave corners unfilled.
- **Dimension Text.** Inspection, Justify, Offset, and the second text line are unavailable. Add Parentheses works.
- A Distance-Distance chamfer that meets a Vertex chamfer corner can fail to build.
- Some files may freeze when rebuilding complex surfaces after an edit or during certain drawing steps. Save often.
- Some drawings may reopen blank. If that happens, try rebuilding with **Ctrl+Q**.
- Some panel wording and layouts may differ from the intended workflow.

### Shortcomings

- FreeWorks runs on stock FreeCAD 1.1.4 and inherits limits from its geometry kernel and assembly solver.
- Sheet metal, weldments, and mold tools have had less testing than parts, assemblies, and drawings.
- Drawing flat patterns, weldment cut-list tables, and the Sketch Blocks and Library Feature panels are still pending.

### Actively being worked on (coming in the next version)

- **Sketching:** smarter snapping and inference lines, and more automatic relations while you draw.
- **Features:** Thin cut from an open line, Full Round on slot ends, and more fillet and chamfer options on surfaces.
- **Sheet metal and weldments:** a full pass on flanges, hems, fold and unfold, structural members and cut lists.
- **Mold tools:** Parting Surface corner options and the rest of the mold panels.
- **Drawings:** flat pattern views, weldment cut-list tables, and Dimension Text options (Inspection, Justify, Offset, second text line).
- **Assemblies:** more mate types, Motion Study polish, and Make Independent.
- **Interface:** panel-by-panel layout and wording polish, Sketch Blocks, and Library Features.
- **Stability:** fixes from automated tutorial walk-throughs and from tester reports.

## Guides

- [Install, update, or remove FreeWorks](docs/INSTALL.md)
- [Give feedback](docs/FEEDBACK.md)
- [Alpha status, known problems, and planned work](STATUS.md)
