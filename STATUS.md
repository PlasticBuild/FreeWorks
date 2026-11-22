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

## Actively being worked on

- Checking alpha stability on clean installs.
- Confirming and fixing issues found by automated tutorial walkthroughs.
- Completing the Dimension Text options and fixing Parting Surface corners.

## Planned next

- Include the fixes for thin cuts from an open line and Full Round on slot ends in the next build.
- Add drawing flat patterns and weldment cut lists, and test sheet metal and weldments more thoroughly.
- Add Sketch Blocks, Library Feature, and Make Independent.
- Refine sketch snapping and automatic relations.
- Fix issues reported by testers.
