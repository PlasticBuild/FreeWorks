# FreeWorks 0.3.0-alpha1 status

These notes cover 0.3.0-alpha1. Everyone is welcome to report bugs, suggest features, or share feedback in [GitHub Issues](https://github.com/PlasticBuild/FreeWorks/issues). See the [feedback guide](docs/FEEDBACK.md) for what to include.

## Known problems

- **Parting Surface.** The Sharp and Smooth corner options leave corners unfilled.
- **Dimension Text.** Inspection, Justify, Offset, and the second text line are unavailable. Add Parentheses works.
- A Distance-Distance chamfer that meets a Vertex chamfer corner can fail to build.
- Some files may freeze when rebuilding complex surfaces after an edit or during certain drawing steps. Save often.
- Some drawings may reopen blank. If that happens, try rebuilding with **Ctrl+Q**.
- Some panel wording and layouts may differ from the intended workflow.

## Shortcomings

- FreeWorks runs on stock FreeCAD 1.1.4 and inherits limits from its geometry kernel and assembly solver.
- Sheet metal, weldments, and mold tools have had less testing than parts, assemblies, and drawings.
- Drawing flat patterns, weldment cut-list tables, and the Sketch Blocks and Library Feature panels are still pending.

## Actively being worked on (coming in the next version)

- **Sketching:** smarter snapping and inference lines, and more automatic relations while you draw.
- **Features:** Thin cut from an open line, Full Round on slot ends, and more fillet and chamfer options on surfaces.
- **Sheet metal and weldments:** a full pass on flanges, hems, fold and unfold, structural members and cut lists.
- **Mold tools:** Parting Surface corner options and the rest of the mold panels.
- **Drawings:** flat pattern views, weldment cut-list tables, and Dimension Text options (Inspection, Justify, Offset, second text line).
- **Assemblies:** more mate types, Motion Study polish, and Make Independent.
- **Interface:** panel-by-panel layout and wording polish, Sketch Blocks, and Library Features.
- **Stability:** fixes from automated tutorial walk-throughs and from tester reports.
